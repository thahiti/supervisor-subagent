"""쿼리 리라이터 단위 테스트.

LLM 호출 없이 프롬프트 생성과 노드 로직을 검증한다.
실제 LLM 기반 리라이팅 품질 검증은 evals/에 위임한다.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.query_rewriter.prompt import (
    _format_dictionary,
    build_rewriter_system_prompt,
)
from src.agents.query_rewriter.rewriter import _find_last_human_message, query_rewriter_node


class TestPrompt:
    def test_build_prompt_includes_current_time(self) -> None:
        now = datetime(2026, 4, 20, 14, 30)
        prompt = build_rewriter_system_prompt(now)
        assert "2026-04-20 14:30" in prompt

    def test_build_prompt_includes_weekday(self) -> None:
        now = datetime(2026, 4, 20, 14, 30)
        prompt = build_rewriter_system_prompt(now)
        assert "Monday" in prompt

    def test_build_prompt_includes_dictionary_terms(self) -> None:
        now = datetime(2026, 4, 20, 14, 30)
        dictionary = {"TEST_KEY": "테스트 정의"}
        prompt = build_rewriter_system_prompt(now, dictionary=dictionary)
        assert "TEST_KEY" in prompt
        assert "테스트 정의" in prompt

    def test_build_prompt_without_dictionary(self) -> None:
        now = datetime(2026, 4, 20, 14, 30)
        prompt = build_rewriter_system_prompt(now)
        assert "없음" in prompt

    def test_format_dictionary_empty(self) -> None:
        assert _format_dictionary({}) == "없음"

    def test_format_dictionary_entries(self) -> None:
        result = _format_dictionary({"A": "B", "C": "D"})
        assert "A → B" in result
        assert "C → D" in result


class TestFindLastHumanMessage:
    def test_finds_last_human_message(self) -> None:
        messages = [
            HumanMessage(content="first"),
            AIMessage(content="reply"),
            HumanMessage(content="second"),
        ]
        result = _find_last_human_message({"messages": messages})
        assert result is not None
        assert result.content == "second"

    def test_returns_none_when_no_human_message(self) -> None:
        messages = [AIMessage(content="only ai")]
        result = _find_last_human_message({"messages": messages})
        assert result is None

    def test_returns_none_on_empty_messages(self) -> None:
        result = _find_last_human_message({"messages": []})
        assert result is None


class TestQueryRewriterNode:
    @patch("src.agents.query_rewriter.rewriter.get_chat_model")
    def test_returns_rewritten_message(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="2026-04-13~2026-04-19 매출 알려줘")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [HumanMessage(content="지난주 매출 알려줘")],
            "next_agent": "",
            "plan": "",
            "completed_agents": [],
        }

        result = query_rewriter_node(state)
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], HumanMessage)
        assert "2026-04-13" in result["messages"][0].content

    @patch("src.agents.query_rewriter.rewriter.get_chat_model")
    def test_skips_when_no_change(self, mock_get_model: MagicMock) -> None:
        original = "3과 7을 더해주세요"
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=original)
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [HumanMessage(content=original)],
            "next_agent": "",
            "plan": "",
            "completed_agents": [],
        }

        result = query_rewriter_node(state)
        assert result["messages"] == []

    def test_skips_when_no_human_message(self) -> None:
        state = {
            "messages": [AIMessage(content="ai only")],
            "next_agent": "",
            "plan": "",
            "completed_agents": [],
        }

        result = query_rewriter_node(state)
        assert result["messages"] == []

    @patch("src.agents.query_rewriter.rewriter.get_chat_model")
    def test_passes_full_conversation_to_llm(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="이전 번역 결과를 영어로 다시 번역해줘")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="Hello를 한국어로 번역해줘"),
                AIMessage(content="안녕하세요"),
                HumanMessage(content="이거 다시 영어로 해줘"),
            ],
            "next_agent": "",
            "plan": "",
            "completed_agents": [],
        }

        query_rewriter_node(state)

        call_args = mock_llm.invoke.call_args[0][0]
        # 시스템 프롬프트 + 대화 메시지 3개 = 총 4개
        assert len(call_args) == 4
