import io
from typing import Iterator

from langchain_core.messages import AIMessage, HumanMessage

from src.cli.app import run_turn
from src.cli.streaming import NodeRenderer


class FakeGraph:
    """LangGraph CompiledStateGraph의 stream API를 흉내내는 더블."""

    def __init__(self, scripted_chunks: list[dict]) -> None:
        self._chunks = scripted_chunks
        self.last_state: dict | None = None

    def stream(self, state: dict, stream_mode: str) -> Iterator[dict]:
        assert stream_mode == "updates"
        self.last_state = state
        for chunk in self._chunks:
            yield chunk


def test_run_turn_accumulates_chat_history_from_response_generator() -> None:
    """response_generator delta의 chat_history가 누적되어 다음 turn으로 전달된다."""
    final_ai = AIMessage(content="이번 달 매출은 1,234만원입니다.")
    final_human = HumanMessage(content="이번 달 매출 합계는?")

    fake_chunks = [
        {"query_rewriter": {"messages": [final_human]}},
        {"router": {"next_agent": "sql"}},
        {"sql_agent": {"messages": [AIMessage(content="[SQL 조회 결과]\n…")]}},
        {
            "response_generator": {
                "messages": [final_ai],
                "chat_history": [final_human, final_ai],
            }
        },
    ]
    graph = FakeGraph(fake_chunks)

    buf = io.StringIO()
    renderer = NodeRenderer(stream=buf)

    new_history, last_ai = run_turn(
        graph,
        user_input="매출 알려줘",
        chat_history=[],
        renderer=renderer,
    )

    assert graph.last_state is not None
    assert graph.last_state["messages"][0].content == "매출 알려줘"
    assert graph.last_state["chat_history"] == []

    assert new_history == [final_human, final_ai]
    assert last_ai is final_ai

    out = buf.getvalue()
    assert "query_rewriter" in out
    assert "router" in out
    assert "next_agent: sql" in out
    assert "sql_agent" in out
    assert "이번 달 매출은 1,234만원입니다." in out


def test_run_turn_preserves_existing_history_when_no_response_generator_chunk() -> None:
    """response_generator chunk가 없으면 기존 history를 유지한다."""
    fake_chunks = [
        {"query_rewriter": {"messages": []}},
        {"router": {"next_agent": "FINISH"}},
    ]
    graph = FakeGraph(fake_chunks)
    renderer = NodeRenderer(stream=io.StringIO())

    prior = [HumanMessage(content="prev"), AIMessage(content="ans")]

    new_history, last_ai = run_turn(graph, "hi", prior, renderer)

    assert new_history == prior
    assert last_ai is None
