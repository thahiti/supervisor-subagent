"""단발성 라우터 노드: 사용자 요청에 가장 적합한 단일 서브에이전트를 선택한다.

Supervisor와 달리 반복 호출 없이 한 번만 라우팅 결정을 내리며,
선택된 서브에이전트 실행 후 곧바로 response_generator로 흐른다.
"""

import json

from langchain_core.messages import AIMessage, SystemMessage

from src.registry import registry
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.state import State

logger = get_logger("router")
router_logger = get_logger("router.router")

ROUTER_SYSTEM_PROMPT = """당신은 멀티 에이전트 시스템의 라우터입니다.

사용자의 요청을 분석하고, 가장 적합한 워커 에이전트 하나만 선택하세요.
적합한 워커가 없으면 "FINISH"를 선택하세요.

## 사용 가능한 워커:
{workers}

## 응답 형식:
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요.

```json
{{"next": "{agent_choices}", "reason": "이유 설명"}}
```

## 규칙:
1. 정확히 하나의 워커만 선택합니다. 여러 워커가 필요해 보이면 사용자의 주된 의도에 가장 부합하는 하나만 고르세요.
2. 적합한 워커가 없으면 "FINISH"를 선택하세요.
3. 선택된 워커는 한 번만 실행된 후 곧바로 최종 답변 단계로 이동합니다."""


FINISH = "FINISH"
RESPONSE_GENERATOR_NODE = "response_generator"


def _extract_json_from_text(text: str) -> dict:
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


def _build_system_prompt() -> str:
    """레지스트리 정보를 기반으로 router 시스템 프롬프트를 생성한다."""
    agent_names = registry.agent_names
    choices = '" 또는 "'.join(agent_names + [FINISH])

    return ROUTER_SYSTEM_PROMPT.format(
        workers=registry.build_workers_prompt(),
        agent_choices=choices,
    )


@log_node("router")
def router_node(state: State) -> dict:
    """라우터: 요청을 분석하여 단일 서브에이전트를 선택한다."""
    llm = get_chat_model()

    system_prompt = _build_system_prompt()
    messages = [SystemMessage(content=system_prompt)] + state["messages"]

    logger.info("LLM 호출 시작")
    try:
        response = llm.invoke(messages)
    except Exception:
        logger.error("LLM 호출 실패", exc_info=True)
        raise

    content: str = response.content  # type: ignore[assignment]
    logger.info("LLM 응답: %s", content)

    try:
        parsed = _extract_json_from_text(content)
        next_agent = parsed.get("next", FINISH)
        reason = parsed.get("reason", "")
        logger.info("라우팅 결정: next=%s, reason=%s", next_agent, reason)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "JSON 파싱 실패: %s → FINISH로 안전 종료. 원본: %s",
            e, content,
        )
        next_agent = FINISH

    return {
        "messages": [AIMessage(content=content)],
        "next_agent": next_agent,
    }


def router_conditional(state: State) -> str:
    """라우터의 결정에 따라 다음 노드를 선택한다."""
    next_agent = state.get("next_agent", FINISH)

    entry = registry.get(next_agent)
    if entry is not None:
        router_logger.info("라우팅: → %s", entry.node_name)
        return entry.node_name

    router_logger.info("라우팅: → response_generator (FINISH)")
    return RESPONSE_GENERATOR_NODE
