"""route_eval 코어 단위 테스트.

LLM 호출 없이 노드 조립 로직만 검증한다. 실제 LLM 검증은
scripts/ 스모크 스크립트가 CLI를 subprocess로 실행해 수행한다.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from evals.route_eval import rewrite, route_trace, to_messages


class TestToMessages:
    def test_builds_in_order(self) -> None:
        msgs = to_messages([("human", "q1"), ("ai", "a1")])
        assert [type(m).__name__ for m in msgs] == ["HumanMessage", "AIMessage"]
        assert [m.content for m in msgs] == ["q1", "a1"]

    def test_empty(self) -> None:
        assert to_messages([]) == []


class TestRewrite:
    @patch("evals.route_eval.query_rewriter_node")
    def test_returns_rewritten_text(self, mock_rw: MagicMock) -> None:
        mock_rw.return_value = {"messages": [HumanMessage(content="확장된 질의")]}
        assert rewrite("원본", []) == "확장된 질의"

    @patch("evals.route_eval.query_rewriter_node")
    def test_falls_back_to_original_when_no_change(self, mock_rw: MagicMock) -> None:
        mock_rw.return_value = {"messages": []}
        assert rewrite("원본", []) == "원본"


class TestRouteTrace:
    @patch("evals.route_eval.router_conditional")
    @patch("evals.route_eval.router_node")
    @patch("evals.route_eval.query_rewriter_node")
    def test_returns_rewritten_and_destination(
        self, mock_rw: MagicMock, mock_router: MagicMock, mock_cond: MagicMock
    ) -> None:
        mock_rw.return_value = {"messages": [HumanMessage(content="확장된 질의")]}
        mock_router.return_value = {
            "messages": [AIMessage(content='{"next": "math"}')],
            "next_agent": "math",
        }
        mock_cond.return_value = "math"

        rewritten, dest = route_trace("3 더하기 4", [AIMessage(content="prev")])

        assert rewritten == "확장된 질의"
        assert dest == "math"
        router_state = mock_router.call_args[0][0]
        contents = [m.content for m in router_state["messages"]]
        assert "3 더하기 4" in contents and "확장된 질의" in contents
        assert mock_cond.call_args[0][0]["next_agent"] == "math"
