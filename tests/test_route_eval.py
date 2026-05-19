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


import argparse

from scripts.cli._common import add_common_args, parse_history, patched_now


class TestCliCommon:
    def test_query_is_positional_nargs_plus(self) -> None:
        parser = argparse.ArgumentParser()
        add_common_args(parser)
        args = parser.parse_args(["지난주", "매출", "알려줘"])
        assert " ".join(args.query) == "지난주 매출 알려줘"
        assert args.history == ""
        assert args.now == ""

    def test_parse_history_empty(self) -> None:
        assert parse_history("") == []
        assert parse_history("   ") == []

    def test_parse_history_json(self) -> None:
        raw = '[{"role":"human","content":"재고"},{"role":"ai","content":"어떤 브랜치?"}]'
        msgs = parse_history(raw)
        assert [type(m).__name__ for m in msgs] == ["HumanMessage", "AIMessage"]
        assert [m.content for m in msgs] == ["재고", "어떤 브랜치?"]

    def test_patched_now_noop_without_value(self) -> None:
        with patched_now(""):
            pass  # 예외 없이 통과하면 OK

    def test_patched_now_fixes_rewriter_datetime(self) -> None:
        from datetime import datetime

        with patched_now("2026-04-29T14:30"):
            import src.query_rewriter.rewriter as rw_mod

            assert rw_mod.datetime.now() == datetime(2026, 4, 29, 14, 30)


class TestQueryRewriterCli:
    @patch("evals.route_eval.rewrite", return_value="지난주(2026-04-20~2026-04-26) 매출 알려줘")
    def test_prints_query_and_rewritten(
        self, _mock_rw: MagicMock, capsys, monkeypatch
    ) -> None:
        import scripts.cli.query_rewriter as cli

        monkeypatch.setattr(
            "sys.argv",
            ["prog", "지난주", "매출", "알려줘", "--now", "2026-04-29T14:30"],
        )
        try:
            cli.main()
        except SystemExit as e:
            assert e.code == 0
        out = capsys.readouterr().out
        assert "query    : 지난주 매출 알려줘" in out
        assert "rewritten: 지난주(2026-04-20~2026-04-26) 매출 알려줘" in out
