"""query_rewriter / router 파이프라인 단위 테스트.

LLM 호출 없이 조립 로직만 검증한다. 워크플로우(`rewrite`, `route_trace`)는
각각 `scripts.cli.query_rewriter`와 `scripts.cli.query_rewriter_router`
모듈이 직접 소유하므로, 패치 타겟은 각 모듈에서 import된 이름이다.

실제 LLM 검증은 scripts/ 스모크 스크립트가 in-process로 워크플로우
함수들을 직접 호출해 수행한다.
"""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from scripts.cli._common import (
    CliState,
    add_common_args,
    parse_history,
    patched_now,
    to_messages,
)
from scripts.cli.query_rewriter import rewrite
from scripts.cli.query_rewriter_router import route_trace


class TestToMessages:
    def test_builds_in_order(self) -> None:
        msgs = to_messages([("human", "q1"), ("ai", "a1")])
        assert [type(m).__name__ for m in msgs] == ["HumanMessage", "AIMessage"]
        assert [m.content for m in msgs] == ["q1", "a1"]

    def test_empty(self) -> None:
        assert to_messages([]) == []


class TestRewrite:
    @patch("scripts.cli.query_rewriter.query_rewriter_node")
    def test_returns_state_with_rewritten_field(self, mock_rw: MagicMock) -> None:
        mock_rw.return_value = {"messages": [HumanMessage(content="확장된 질의")]}
        state: CliState = {
            "messages": [HumanMessage(content="원본")],
            "next_agent": "",
            "chat_history": [],
        }
        result = rewrite(state)
        assert result["rewritten"] == "확장된 질의"
        # 원본 messages + 리라이팅 메시지가 모두 누적
        contents = [m.content for m in result["messages"] if isinstance(m, HumanMessage)]
        assert "원본" in contents and "확장된 질의" in contents

    @patch("scripts.cli.query_rewriter.query_rewriter_node")
    def test_falls_back_to_original_when_no_change(self, mock_rw: MagicMock) -> None:
        mock_rw.return_value = {"messages": []}
        state: CliState = {
            "messages": [HumanMessage(content="원본")],
            "next_agent": "",
            "chat_history": [],
        }
        result = rewrite(state)
        assert result["rewritten"] == "원본"


class TestRouteTrace:
    @patch("scripts.cli.query_rewriter_router.router_conditional")
    @patch("scripts.cli.query_rewriter_router.router_node")
    @patch("scripts.cli.query_rewriter_router.query_rewriter_node")
    def test_returns_state_with_rewritten_and_next_node(
        self, mock_rw: MagicMock, mock_router: MagicMock, mock_cond: MagicMock
    ) -> None:
        mock_rw.return_value = {"messages": [HumanMessage(content="확장된 질의")]}
        mock_router.return_value = {
            "messages": [AIMessage(content='{"next": "math"}')],
            "next_agent": "math",
        }
        mock_cond.return_value = "math_agent"

        state: CliState = {
            "messages": [HumanMessage(content="3 더하기 4")],
            "next_agent": "",
            "chat_history": [AIMessage(content="prev")],
        }
        result = route_trace(state)

        assert result["rewritten"] == "확장된 질의"
        assert result["next_agent"] == "math"
        assert result["next_node"] == "math_agent"
        # router_node가 받은 state에는 원본+리라이팅 메시지가 둘 다 누적되어 있어야 함
        router_state = mock_router.call_args[0][0]
        contents = [m.content for m in router_state["messages"] if isinstance(m, HumanMessage)]
        assert "3 더하기 4" in contents and "확장된 질의" in contents
        assert mock_cond.call_args[0][0]["next_agent"] == "math"


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
    @patch("scripts.cli.query_rewriter.rewrite")
    def test_prints_query_and_rewritten(
        self, mock_rw: MagicMock, capsys, monkeypatch
    ) -> None:
        import scripts.cli.query_rewriter as cli

        mock_rw.return_value = {
            "messages": [HumanMessage(content="지난주(2026-04-20~2026-04-26) 매출 알려줘")],
            "next_agent": "",
            "chat_history": [],
            "rewritten": "지난주(2026-04-20~2026-04-26) 매출 알려줘",
        }
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


class TestQueryRewriterRouterCli:
    @patch("scripts.cli.query_rewriter_router.route_trace")
    def test_prints_query_rewritten_destination(
        self, mock_rt: MagicMock, capsys, monkeypatch
    ) -> None:
        import scripts.cli.query_rewriter_router as cli

        mock_rt.return_value = {
            "messages": [HumanMessage(content="공장2의 제품 재고를 조사해줘")],
            "next_agent": "tool_call",
            "chat_history": [],
            "rewritten": "공장2의 제품 재고를 조사해줘",
            "next_node": "tool_call_agent",
        }
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "공장2",
                "--history",
                '[{"role":"human","content":"재고 조사"},'
                '{"role":"ai","content":"어떤 브랜치?"}]',
            ],
        )
        try:
            cli.main()
        except SystemExit as e:
            assert e.code == 0
        out = capsys.readouterr().out
        assert "query      : 공장2" in out
        assert "rewritten  : 공장2의 제품 재고를 조사해줘" in out
        assert "destination: tool_call_agent" in out
