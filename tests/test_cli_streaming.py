import io
import re

from langchain_core.messages import AIMessage, HumanMessage

from src.cli.streaming import (
    NodeRenderer,
    format_agent,
    format_query_rewriter,
    format_response_generator,
    format_router,
)


def _strip_timing(text: str) -> str:
    """렌더러 출력에서 가변적인 (X.XXs) 부분을 마스킹한다."""
    return re.sub(r"\(\d+\.\d{2}s\)", "(T.TTs)", text)


def test_format_query_rewriter_with_change() -> None:
    delta = {"messages": [HumanMessage(content="rewritten query")]}
    assert format_query_rewriter(delta) == ["rewritten: rewritten query"]


def test_format_query_rewriter_no_change() -> None:
    assert format_query_rewriter({"messages": []}) == ["no change"]
    assert format_query_rewriter({}) == ["no change"]


def test_format_router_emits_next_agent() -> None:
    assert format_router({"next_agent": "sql"}) == ["next_agent: sql"]


def test_format_router_skips_when_empty() -> None:
    assert format_router({"next_agent": ""}) == []
    assert format_router({}) == []


def test_format_agent_emits_no_extra_lines() -> None:
    delta = {"messages": [AIMessage(content="[수학 계산 결과]\n12")]}
    assert format_agent(delta) == []


def test_format_response_generator_emits_no_extra_lines() -> None:
    delta = {"messages": [AIMessage(content="최종 답변")]}
    assert format_response_generator(delta) == []


def test_renderer_outputs_node_line_with_delta() -> None:
    buf = io.StringIO()
    renderer = NodeRenderer(stream=buf)
    renderer.turn_start()
    renderer.on_node_update("router", {"next_agent": "sql"})

    out = _strip_timing(buf.getvalue())
    assert "router" in out
    assert "done" in out
    assert "next_agent: sql" in out


def test_renderer_unknown_node_falls_back_to_node_name_only() -> None:
    buf = io.StringIO()
    renderer = NodeRenderer(stream=buf)
    renderer.turn_start()
    renderer.on_node_update("future_node", {"foo": "bar"})

    out = _strip_timing(buf.getvalue())
    assert "future_node" in out
    assert "done" in out
    # delta에서 임의 키를 끌어와 출력하지 않는다
    assert "foo: bar" not in out


def test_renderer_render_final_answer_wraps_with_separator() -> None:
    buf = io.StringIO()
    renderer = NodeRenderer(stream=buf)
    renderer.render_final_answer("최종 답변입니다.")

    out = buf.getvalue()
    assert "최종 답변입니다." in out
    assert out.count("─") >= 2 or out.count("-") >= 2  # 구분선 2개
