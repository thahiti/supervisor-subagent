"""response_generator 단위 테스트.

LLM 호출 없이 프롬프트 구성과 노드 로직을 검증한다.
"""

from __future__ import annotations

from src.response_generator.prompt import RESPONSE_GENERATOR_SYSTEM_PROMPT


class TestPrompt:
    def test_prompt_is_nonempty_string(self) -> None:
        assert isinstance(RESPONSE_GENERATOR_SYSTEM_PROMPT, str)
        assert len(RESPONSE_GENERATOR_SYSTEM_PROMPT) > 0

    def test_prompt_instructs_to_ignore_json(self) -> None:
        assert "JSON" in RESPONSE_GENERATOR_SYSTEM_PROMPT


from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from src.response_generator.generator import response_generator_node


class TestResponseGeneratorNode:
    @patch("src.response_generator.generator.get_chat_model")
    def test_returns_ai_message(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="연봉 5천만원 이상 직원은 3명입니다.")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="연봉이 5천만원 이상인 직원은 몇 명인가요?"),
                AIMessage(content='{"next": "sql", "reason": "SQL 조회 필요", "plan": "sql 실행"}'),
                AIMessage(content="[SQL 결과]\n| count |\n|-------|\n| 3 |"),
                AIMessage(content='{"next": "FINISH", "reason": "완료", "plan": "완료"}'),
            ],
            "next_agent": "FINISH",
            "plan": "완료",
            "completed_agents": ["sql"],
        }

        result = response_generator_node(state)
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert "3명" in result["messages"][0].content

    @patch("src.response_generator.generator.get_chat_model")
    def test_passes_system_prompt_and_messages(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="답변")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="질문"),
                AIMessage(content="결과"),
            ],
            "next_agent": "FINISH",
            "plan": "",
            "completed_agents": [],
        }

        response_generator_node(state)

        call_args = mock_llm.invoke.call_args[0][0]
        # 시스템 프롬프트 1개 + 대화 메시지 2개 = 총 3개
        assert len(call_args) == 3

    @patch("src.response_generator.generator.get_chat_model")
    def test_handles_multi_agent_results(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content="123 곱하기 456은 56,088입니다. In English: 56,088.",
        )
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="123 곱하기 456을 계산하고 영어로 설명해줘"),
                AIMessage(content='{"next": "math", "reason": "계산", "plan": "math → translate"}'),
                AIMessage(content="[수학 계산 결과]\n56088"),
                AIMessage(content='{"next": "translate", "reason": "번역", "plan": "translate"}'),
                AIMessage(content="[번역 결과]\n56,088"),
                AIMessage(content='{"next": "FINISH", "reason": "완료", "plan": "완료"}'),
            ],
            "next_agent": "FINISH",
            "plan": "완료",
            "completed_agents": ["math", "translate"],
        }

        result = response_generator_node(state)
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)

    @patch("src.response_generator.generator.get_chat_model")
    def test_returns_chat_history_with_two_messages(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="최종 출력")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="리라이팅된 질의"),
                AIMessage(content="에이전트 결과"),
            ],
            "next_agent": "FINISH",
            "chat_history": [],
        }

        result = response_generator_node(state)
        assert "chat_history" in result
        assert len(result["chat_history"]) == 2

    @patch("src.response_generator.generator.get_chat_model")
    def test_chat_history_first_is_last_human_message(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="최종 출력")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="원본 질의"),
                HumanMessage(content="리라이팅된 질의"),
                AIMessage(content="에이전트 결과"),
            ],
            "next_agent": "FINISH",
            "chat_history": [],
        }

        result = response_generator_node(state)
        first = result["chat_history"][0]
        assert isinstance(first, HumanMessage)
        assert first.content == "리라이팅된 질의"

    @patch("src.response_generator.generator.get_chat_model")
    def test_chat_history_second_is_generated_ai_message(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="최종 출력")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="질의"),
                AIMessage(content="에이전트 결과"),
            ],
            "next_agent": "FINISH",
            "chat_history": [],
        }

        result = response_generator_node(state)
        second = result["chat_history"][1]
        assert isinstance(second, AIMessage)
        assert second.content == "최종 출력"

    @patch("src.response_generator.generator.get_chat_model")
    def test_omits_chat_history_when_no_human_message(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="최종 출력")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [AIMessage(content="ai only")],
            "next_agent": "FINISH",
            "chat_history": [],
        }

        result = response_generator_node(state)
        assert "chat_history" not in result
        assert "messages" in result

from src.supervisor.supervisor import supervisor_router


class TestSupervisorRouterChange:
    def test_finish_routes_to_response_generator(self) -> None:
        state = {
            "messages": [],
            "next_agent": "FINISH",
            "plan": "",
            "completed_agents": [],
        }
        result = supervisor_router(state)
        assert result == "response_generator"

    def test_max_iterations_routes_to_response_generator(self) -> None:
        state = {
            "messages": [],
            "next_agent": "math",
            "plan": "",
            "completed_agents": ["a", "b", "c", "d", "e"],
        }
        result = supervisor_router(state)
        assert result == "response_generator"

    def test_agent_routes_normally(self) -> None:
        import src  # noqa: F401
        state = {
            "messages": [],
            "next_agent": "math",
            "plan": "",
            "completed_agents": [],
        }
        result = supervisor_router(state)
        assert result == "math_agent"
