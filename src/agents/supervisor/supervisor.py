import json

from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END

from src.agents.registry import registry
from src.logging import get_logger, log_node
from src.state import State

logger = get_logger("supervisor")
router_logger = get_logger("router.supervisor")

SUPERVISOR_SYSTEM_PROMPT = """당신은 멀티 에이전트 시스템의 슈퍼바이저입니다.

사용자의 요청을 분석하고, 적절한 워커 에이전트에게 작업을 위임하세요.

## 사용 가능한 워커:
{workers}

## 현재 상태:
- 실행 계획: {plan}
- 완료된 워커: {completed_agents}

## 응답 형식:
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요.

```json
{{"next": "{agent_choices}", "reason": "이유 설명", "plan": "전체 실행 계획"}}
```

## 규칙:
1. 모든 필요한 작업이 완료되면 "FINISH"를 선택하세요.
2. 각 워커는 한 번에 하나의 작업만 처리합니다.
3. 계획을 세우고 순서대로 워커를 호출하세요.
4. FINISH 선택 시, 워커들의 결과를 종합하여 reason에 최종 요약을 포함하세요."""


MAX_ITERATIONS = 5


def extract_json_from_text(text: str) -> dict:
    """텍스트에서 JSON을 추출한다. ```json 블록 또는 직접 파싱을 시도한다."""
    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + len("```")
        end = text.index("```", start)
        text = text[start:end].strip()
    return json.loads(text)


def _build_system_prompt(plan: str, completed_agents: list[str]) -> str:
    """레지스트리 정보를 기반으로 supervisor 시스템 프롬프트를 생성한다."""
    agent_names = registry.agent_names
    choices = '" 또는 "'.join(agent_names + ["FINISH"])

    return SUPERVISOR_SYSTEM_PROMPT.format(
        workers=registry.build_workers_prompt(),
        plan=plan,
        completed_agents=", ".join(completed_agents) if completed_agents else "없음",
        agent_choices=choices,
    )


@log_node("supervisor")
def supervisor_node(state: State) -> dict:
    """슈퍼바이저: 요청 분석, 계획 수립, 다음 워커 결정."""
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    plan = state.get("plan", "아직 계획 없음")
    completed = state.get("completed_agents", [])

    system_prompt = _build_system_prompt(plan, list(completed))

    messages = [SystemMessage(content=system_prompt)] + state["messages"]

    logger.info("LLM 호출 시작 (model=gpt-4o-mini)")
    try:
        response = llm.invoke(messages)
    except Exception:
        logger.error("LLM 호출 실패", exc_info=True)
        raise
    content: str = response.content  # type: ignore[assignment]
    logger.info("LLM 응답: %s", content)

    try:
        parsed = extract_json_from_text(content)
        next_agent = parsed.get("next", "FINISH")
        reason = parsed.get("reason", "")
        new_plan = parsed.get("plan", plan)

        logger.info(
            "LLM 결정: next=%s, reason=%s, plan=%s",
            next_agent, reason, new_plan,
        )

        return {
            "messages": [AIMessage(content=content)],
            "next_agent": next_agent,
            "plan": new_plan,
        }

    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "JSON 파싱 실패: %s → FINISH로 안전 종료. 원본: %s",
            e, content,
        )
        return {
            "messages": [AIMessage(content=content)],
            "next_agent": "FINISH",
            "plan": plan,
        }


def supervisor_router(state: State) -> str:
    """슈퍼바이저의 결정에 따라 다음 노드를 라우팅한다."""
    next_agent = state.get("next_agent", "FINISH")

    completed = state.get("completed_agents", [])
    if len(completed) >= MAX_ITERATIONS:
        router_logger.warning(
            "최대 반복 횟수(%d) 도달 → END", MAX_ITERATIONS,
        )
        return END

    entry = registry.get(next_agent)
    if entry is not None:
        router_logger.info("라우팅: → %s", entry.node_name)
        return entry.node_name

    router_logger.info("라우팅: → END (FINISH)")
    return END
