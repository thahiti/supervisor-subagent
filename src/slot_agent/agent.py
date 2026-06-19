"""slot 에이전트: declarative 시나리오 기반 슬롯 채우기 조회.

단일 LLM 호출로 (시나리오 매칭 + 메시지에 드러난 슬롯)만 추출하고, 후보값
grounding·슬롯 해소·지표 조회는 결정적 Python(resolve/metric)이 수행한다.
멀티턴 HITL은 query_rewriter가 처리하므로 이 에이전트는 chat_history를
보지 않는다.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

from src.registry import registry
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.sql_agent.backend.formatter import to_markdown_table
from src.state import State
from src.slot_agent import scenarios  # noqa: F401 - 등록 트리거
from src.slot_agent.prompt import SlotExtraction, build_system_prompt
from src.slot_agent.registry import Scenario, scenario_registry
from src.slot_agent.repository import get_repository
from src.slot_agent.resolve import AskSlot, Ready, resolve

logger = get_logger("agent.slot")


def _emit(content: str) -> dict:
    """그래프 반환 dict 표준 형식 (다른 서브에이전트들과 동일한 태깅)."""
    return {"messages": [AIMessage(content=f"[조회 결과]\n{content}")]}


def _no_match_message() -> str:
    """no_match 상황에서 사용자에게 보여줄 안내 메시지."""
    if not scenario_registry.scenarios:
        return "처리 가능한 조회가 등록되어 있지 않습니다."
    lines = ["이 에이전트가 처리할 수 있는 조회 종류는 다음과 같습니다:"]
    for s in scenario_registry.scenarios:
        lines.append(f"- {s.label}")
    lines.append("위 조회 중 하나로 다시 질문해 주세요.")
    return "\n".join(lines)


def _object_particle(word: str) -> str:
    """한국어 목적격 조사(을/를)를 단어의 끝 글자 받침 유무로 고른다.

    끝 글자가 한글이 아니면 기본값 '를'을 사용한다.
    """
    if not word:
        return "를"
    last = word[-1]
    if "가" <= last <= "힣":
        has_final = (ord(last) - 0xAC00) % 28 != 0
        return "을" if has_final else "를"
    return "를"


def _format_ask(ask: AskSlot) -> str:
    """다음 빈 슬롯을 묻는 메시지. 후보값이 있으면 표로 제시(grounding)."""
    slot = ask.slot
    if not ask.candidates:
        return f"{slot.description} 값을 알려주세요."
    columns = [slot.value_key, slot.label_key]
    rows = [
        (c.get(slot.value_key), c.get(slot.label_key)) for c in ask.candidates
    ]
    table = to_markdown_table(columns, rows)
    particle = _object_particle(slot.description)
    return (
        f"어떤 {slot.description}{particle} 조회할까요? 아래에서 골라 알려주세요.\n\n"
        f"{table}"
    )


def _format_result(scenario: Scenario, result: dict[str, Any]) -> str:
    """확정된 슬롯으로 조회한 최종 지표를 표로 포매팅."""
    table = to_markdown_table(result["columns"], result["rows"])
    return f"[{scenario.label}] {result['label']}\n{table}"


@registry.agent(
    "slot",
    description=scenario_registry.build_router_description(),
)
@log_node("slot")
def slot_wrapper(state: State) -> dict:
    """declarative 시나리오 기반 슬롯 채우기 조회를 처리한다."""
    system_prompt = build_system_prompt(scenario_registry)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=state.get("rewritten_query", "")),
    ]
    # 프롬프트로 JSON을 지시하는 대신 구조화 출력으로 SlotExtraction을 강제한다.
    # include_raw=True → API 오류는 예외로 올라오고, 스키마 파싱 실패는 parsed=None으로 구분된다.
    llm = get_chat_model().with_structured_output(
        SlotExtraction, method="function_calling", include_raw=True
    )

    logger.info("LLM 호출 시작 (scenarios=%d)", len(scenario_registry.scenarios))
    try:
        result = llm.invoke(messages)
    except Exception:
        logger.error("LLM 호출 실패", exc_info=True)
        raise

    parsed: SlotExtraction | None = result.get("parsed")
    if parsed is None:
        logger.warning("구조화 출력 파싱 실패 → no_match. raw: %s", result.get("raw"))
        return _emit(_no_match_message())

    scenario_id = parsed.scenario_id
    if not scenario_id:
        return _emit(_no_match_message())

    scenario = scenario_registry.get(scenario_id)
    if scenario is None:
        logger.warning("미등록 scenario_id: %s → no_match", scenario_id)
        return _emit(_no_match_message())

    extracted = parsed.slots or {}
    repo = get_repository()
    outcome = resolve(repo, scenario, extracted)

    if isinstance(outcome, AskSlot):
        return _emit(_format_ask(outcome))

    if not isinstance(outcome, Ready):  # 방어 코드 — 이론상 도달 불가
        logger.error("resolve 반환 타입 오류: %r", outcome)
        return _emit(_no_match_message())
    result = scenario.metric(repo, outcome.slots)
    return _emit(_format_result(scenario, result))
