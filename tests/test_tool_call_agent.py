"""tool_call 에이전트 wrapper + 서브그래프 단위 테스트.

LLM은 mock으로 tool_calls / 최종 응답을 시드한다.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from res.sample_db.factory import seed
from src.tool_call_agent import tools


@pytest.fixture
def factory_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """factory DB를 tmp에 시드하고, tools 모듈의 경로 상수를 리다이렉트."""
    monkeypatch.setattr(seed, "FACTORY_DIR", tmp_path)
    monkeypatch.setattr(seed, "META_DB_PATH", tmp_path / "meta.db")
    monkeypatch.setattr(tools, "_FACTORY_DB_ROOT", tmp_path)
    monkeypatch.setattr(tools, "_META_DB", tmp_path / "meta.db")
    seed.run()
    return tmp_path


def _state(user_text: str) -> dict:
    return {
        "messages": [HumanMessage(content=user_text)],
        "next_agent": "",
        "chat_history": [],
    }


def _ai_with_tool_calls(calls: list[dict]) -> AIMessage:
    msg = AIMessage(content="")
    msg.tool_calls = calls  # type: ignore[attr-defined]
    return msg


def _llm_sequence(responses: list) -> MagicMock:
    """LLM을 mock으로 만들어 invoke 호출마다 순서대로 응답을 반환."""
    llm = MagicMock()
    bound = MagicMock()
    bound.invoke = MagicMock(side_effect=responses)
    llm.bind_tools.return_value = bound
    return llm


class TestSubgraphFlow:
    @patch("src.tool_call_agent.agent.get_chat_model")
    def test_single_tool_call_then_finish(
        self, mock_chat: MagicMock, factory_tmp: Path
    ) -> None:
        from src.tool_call_agent.agent import tool_call_subgraph

        mock_chat.return_value = _llm_sequence([
            _ai_with_tool_calls([
                {"id": "c1", "name": "list_branches", "args": {}},
            ]),
            AIMessage(content="다음 브랜치가 있습니다: F-A, F-B, F-C"),
        ])

        result = tool_call_subgraph.invoke(
            {"messages": [HumanMessage("어떤 브랜치 있어?")]}
        )
        final = result["messages"][-1]
        assert isinstance(final, AIMessage)
        assert "F-A" in final.content

    @patch("src.tool_call_agent.agent.get_chat_model")
    def test_three_step_chain(
        self, mock_chat: MagicMock, factory_tmp: Path
    ) -> None:
        from src.tool_call_agent.agent import tool_call_subgraph

        db_path = str((factory_tmp / "branch_A.db").resolve())
        mock_chat.return_value = _llm_sequence([
            _ai_with_tool_calls([
                {"id": "c1", "name": "list_branches", "args": {}},
            ]),
            _ai_with_tool_calls([
                {"id": "c2", "name": "get_branch_db_path",
                 "args": {"branch_code": "F-A"}},
            ]),
            _ai_with_tool_calls([
                {"id": "c3", "name": "get_machine_status",
                 "args": {"db_path": db_path, "machine_id": "M-001"}},
            ]),
            AIMessage(content="F-A의 M-001 머신 상태입니다: running"),
        ])

        result = tool_call_subgraph.invoke(
            {"messages": [HumanMessage("아산 1공장 M-001 상태")]}
        )
        final = result["messages"][-1]
        assert isinstance(final, AIMessage)
        assert "running" in final.content

    @patch("src.tool_call_agent.agent.get_chat_model")
    def test_clarification_without_tool_call(
        self, mock_chat: MagicMock, factory_tmp: Path
    ) -> None:
        from src.tool_call_agent.agent import tool_call_subgraph

        mock_chat.return_value = _llm_sequence([
            AIMessage(content="어느 브랜치의 어느 머신을 조회할까요?"),
        ])

        result = tool_call_subgraph.invoke(
            {"messages": [HumanMessage("머신 상태")]}
        )
        final = result["messages"][-1]
        assert isinstance(final, AIMessage)
        assert "어느 브랜치" in final.content

    @patch("src.tool_call_agent.agent.get_chat_model")
    def test_unknown_tool_name_recovers(
        self, mock_chat: MagicMock, factory_tmp: Path
    ) -> None:
        from src.tool_call_agent.agent import tool_call_subgraph

        mock_chat.return_value = _llm_sequence([
            _ai_with_tool_calls([
                {"id": "c1", "name": "does_not_exist", "args": {}},
            ]),
            AIMessage(content="죄송합니다. 다시 시도하겠습니다."),
        ])

        result = tool_call_subgraph.invoke(
            {"messages": [HumanMessage("아무거나")]}
        )
        # 에러 ToolMessage가 LLM에게 전달되고, LLM이 자연어로 종료.
        tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert any("알 수 없는 tool" in m.content for m in tool_msgs)

    @patch("src.tool_call_agent.agent.get_chat_model")
    def test_tool_exception_surfaced_as_error(
        self, mock_chat: MagicMock, factory_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.tool_call_agent import agent as agent_mod

        def _raising_tool(*args, **kwargs):
            raise RuntimeError("boom")

        broken = MagicMock()
        broken.invoke = _raising_tool
        monkeypatch.setitem(agent_mod.TOOLS_BY_NAME, "list_branches", broken)

        mock_chat.return_value = _llm_sequence([
            _ai_with_tool_calls([
                {"id": "c1", "name": "list_branches", "args": {}},
            ]),
            AIMessage(content="실패했습니다."),
        ])

        result = agent_mod.tool_call_subgraph.invoke(
            {"messages": [HumanMessage("어떤 브랜치?")]}
        )
        tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert any("실행 중 예외" in m.content for m in tool_msgs)


class TestWrapper:
    @patch("src.tool_call_agent.agent.get_chat_model")
    def test_wrapper_tags_output(
        self, mock_chat: MagicMock, factory_tmp: Path
    ) -> None:
        from src.tool_call_agent.agent import tool_call_wrapper

        mock_chat.return_value = _llm_sequence([
            AIMessage(content="브랜치 F-A, F-B, F-C"),
        ])

        result = tool_call_wrapper(_state("어떤 브랜치"))
        assert result["messages"][0].content.startswith("[조회 결과]\n")

    def test_wrapper_registered(self) -> None:
        from src.registry import registry
        import src.tool_call_agent  # noqa: F401  - 등록 트리거

        names = registry.agent_names
        assert "tool_call" in names

    def test_wrapper_description_has_routing_hints(self) -> None:
        from src.registry import registry
        import src.tool_call_agent  # noqa: F401

        entry = registry.get("tool_call")
        assert entry is not None
        desc = entry.description
        assert "브랜치" in desc
        assert "머신" in desc
        assert "ecommerce" in desc  # 라우팅 배제 가이드
