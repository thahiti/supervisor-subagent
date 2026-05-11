"""templated_sql 에이전트: 사전 정의 SQL 템플릿 기반 조회.

단일 LLM 호출로 4-action(execute_main/ask_clarification/execute_lookup/
no_match)을 분류하고 분기 실행한다. 멀티턴 흐름은 query_rewriter가
처리하므로 이 에이전트는 chat_history를 보지 않는다.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage

from src.registry import registry
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.sql_agent.tools import get_executor  # 모듈 레벨 SqlExecutor 인스턴스 재활용 (set_executor 교체 반영)
from src.state import State
from src.templated_sql_agent import templates  # noqa: F401 - 등록 트리거
from src.templated_sql_agent.prompt import build_system_prompt
from src.templated_sql_agent.registry import SqlTemplate, template_registry
from src.templated_sql_agent.render import TemplateRenderError, render

logger = get_logger("agent.templated_sql")


def _emit(content: str) -> dict:
    """그래프 반환 dict 표준 형식 (다른 서브에이전트들과 동일한 태깅)."""
    return {"messages": [AIMessage(content=f"[조회 결과]\n{content}")]}


def _parse_action_json(text: str) -> dict[str, Any] | None:
    """LLM 응답에서 JSON 객체를 추출한다. 실패 시 None."""
    stripped = text.strip()
    # ```json 블록 펜스가 섞여 있으면 안의 내용만 추출.
    if "```" in stripped:
        try:
            start = stripped.index("```")
            after = stripped[start + 3:]
            if after.startswith("json"):
                after = after[4:]
            end = after.index("```")
            stripped = after[:end].strip()
        except ValueError:
            pass
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None


def _no_match_message() -> str:
    """no_match 상황에서 사용자에게 보여줄 안내 메시지."""
    if not template_registry.templates:
        return "처리 가능한 질의가 등록되어 있지 않습니다."
    lines = ["이 에이전트가 처리할 수 있는 질의 종류는 다음과 같습니다:"]
    for t in template_registry.templates:
        lines.append(f"- {t.intent}")
    lines.append("위 질의 중 하나로 다시 질문해 주세요.")
    return "\n".join(lines)


def _run_main(template: SqlTemplate, extracted: dict[str, Any]) -> str:
    """메인 SQL을 실행하고 markdown 결과(or 사용자 안내) 문자열을 반환."""
    try:
        sql, params = render(template, extracted)
    except TemplateRenderError as exc:
        logger.info("render 실패: %s", exc)
        return (
            f"다음 변수가 잘못되었거나 누락되었습니다: {exc}\n"
            "값을 확인해 다시 알려주세요."
        )
    result = get_executor().execute(sql, params)
    return result["markdown"]


def _run_lookups(
    template: SqlTemplate,
    lookup_vars: list[str],
) -> str:
    """후보값 조회 SQL을 실행하고 결과 표들을 묶어 markdown 문자열로 반환."""
    candidates = [
        v for v in template.variables
        if v.name in lookup_vars and v.lookup_sql is not None
    ]
    if not candidates:
        return (
            "조회 가능한 후보값이 없습니다. 변수 값을 직접 알려주세요.\n"
            "필요한 변수:\n"
            + "\n".join(
                f"- {v.name} ({v.sql_type}): {v.description}"
                for v in template.variables
            )
        )

    blocks: list[str] = []
    for v in candidates:
        assert v.lookup_sql is not None
        r = get_executor().execute(v.lookup_sql)
        header = f"[{v.description} 후보값]"
        if r["ok"]:
            blocks.append(f"{header}\n{r['markdown']}")
        else:
            blocks.append(f"{header}\n조회 실패: {r['error']}")

    blocks.append("원하시는 값을 알려주시면 조회를 진행합니다.")
    return "\n\n".join(blocks)


@registry.agent(
    "templated_sql",
    description=template_registry.build_router_description(),
)
@log_node("templated_sql")
def templated_sql_wrapper(state: State) -> dict:
    """사전 정의된 SQL 템플릿 기반 조회를 처리한다."""
    llm = get_chat_model()
    system_prompt = build_system_prompt(template_registry)
    messages = [SystemMessage(content=system_prompt)] + state["messages"]

    logger.info("LLM 호출 시작 (templates=%d)", len(template_registry.templates))
    try:
        response = llm.invoke(messages)
    except Exception:
        logger.error("LLM 호출 실패", exc_info=True)
        raise

    parsed = _parse_action_json(response.content)
    if parsed is None:
        logger.warning("JSON 파싱 실패 → no_match 폴백. 원본: %s", response.content)
        return _emit(_no_match_message())

    action = parsed.get("action")
    template_id = parsed.get("template_id")

    if action in {"ask_clarification", "no_match"}:
        clarification = parsed.get("clarification") or _no_match_message()
        return _emit(clarification)

    template = template_registry.get(template_id) if template_id else None
    if template is None:
        logger.warning("미등록 template_id: %s → no_match 폴백", template_id)
        return _emit(_no_match_message())

    if action == "execute_lookup":
        lookup_vars = parsed.get("lookup_vars") or []
        return _emit(_run_lookups(template, lookup_vars))

    if action == "execute_main":
        extracted = parsed.get("extracted") or {}
        return _emit(_run_main(template, extracted))

    logger.warning("알 수 없는 action: %s → no_match 폴백", action)
    return _emit(_no_match_message())
