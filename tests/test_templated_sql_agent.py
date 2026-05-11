"""templated_sql 에이전트 단위 테스트.

LLM 호출 없이 프롬프트 합성과 wrapper 분기 로직을 검증한다.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from src.templated_sql_agent.agent import templated_sql_wrapper
from src.templated_sql_agent.prompt import build_system_prompt
from src.templated_sql_agent.registry import (
    SqlTemplate,
    TemplateRegistry,
    TemplateVariable,
)


class TestPrompt:
    def _registry(self) -> TemplateRegistry:
        reg = TemplateRegistry()
        reg.register(SqlTemplate(
            id="sample",
            intent="샘플 의도",
            sql="SELECT * FROM t WHERE x = :x",
            variables=(
                TemplateVariable(
                    name="x", description="x 설명", sql_type="int",
                    lookup_sql="SELECT id, name FROM t ORDER BY name",
                ),
            ),
        ))
        return reg

    def test_prompt_lists_four_actions(self) -> None:
        prompt = build_system_prompt(self._registry())
        for action in ("execute_main", "ask_clarification", "execute_lookup", "no_match"):
            assert action in prompt

    def test_prompt_embeds_catalog(self) -> None:
        prompt = build_system_prompt(self._registry())
        assert "template_id: sample" in prompt
        assert "샘플 의도" in prompt
        assert "x (int)" in prompt

    def test_prompt_emphasizes_no_guessing(self) -> None:
        prompt = build_system_prompt(self._registry())
        # 변수 임의 추측 금지가 명시되어야 한다.
        assert "추측" in prompt or "임의" in prompt

    def test_prompt_specifies_json_output(self) -> None:
        prompt = build_system_prompt(self._registry())
        assert "JSON" in prompt
        assert '"action"' in prompt
        assert '"template_id"' in prompt
        assert '"extracted"' in prompt
        assert '"lookup_vars"' in prompt
        assert '"clarification"' in prompt


def _state(user_text: str) -> dict:
    return {
        "messages": [HumanMessage(content=user_text)],
        "next_agent": "",
        "chat_history": [],
    }


def _llm_returning(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.invoke.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))
    return mock


class TestAgentDispatch:
    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_ask_clarification_returns_text_verbatim(
        self, mock_get_model: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "ask_clarification",
            "template_id": "product_stock",
            "extracted": {},
            "lookup_vars": [],
            "clarification": "어느 제품을 조회할까요? 전체 제품 목록을 보여드릴까요?",
        })
        result = templated_sql_wrapper(_state("재고 알려줘"))
        msg = result["messages"][-1]
        assert isinstance(msg, AIMessage)
        assert "어느 제품을 조회할까요" in msg.content

    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_no_match_returns_catalog_intents(
        self, mock_get_model: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "no_match",
            "template_id": None,
            "extracted": {},
            "lookup_vars": [],
            "clarification": "처리 가능한 질의 종류는: …",
        })
        result = templated_sql_wrapper(_state("무엇이든"))
        content = result["messages"][-1].content
        assert "처리 가능한 질의" in content

    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_json_parse_failure_falls_back_to_no_match(
        self, mock_get_model: MagicMock,
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="이건 JSON이 아닙니다")
        mock_get_model.return_value = mock_llm
        result = templated_sql_wrapper(_state("ㅁㄴㅇㄹ"))
        content = result["messages"][-1].content
        assert "특정 제품의 현재 재고 조회" in content

    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_unknown_template_id_falls_back_to_no_match(
        self, mock_get_model: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "execute_main",
            "template_id": "definitely_not_registered",
            "extracted": {"x": 1},
            "lookup_vars": [],
            "clarification": "",
        })
        result = templated_sql_wrapper(_state("..."))
        content = result["messages"][-1].content
        assert "특정 제품의 현재 재고 조회" in content


class TestExecuteMain:
    @patch("src.templated_sql_agent.agent._executor")
    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_execute_main_calls_executor_with_named_params(
        self,
        mock_get_model: MagicMock,
        mock_executor: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "execute_main",
            "template_id": "product_stock",
            "extracted": {"product_id": "7"},
            "lookup_vars": [],
            "clarification": "",
        })
        mock_executor.execute.return_value = {
            "ok": True, "columns": ["id"], "rows": [(7,)],
            "markdown": "| id |\n|---|\n| 7 |", "error": None,
        }

        result = templated_sql_wrapper(_state("상품 7번 재고"))

        call = mock_executor.execute.call_args
        sql_arg, params_arg = call[0][0], call[0][1]
        assert ":product_id" in sql_arg
        assert params_arg == {"product_id": 7}
        assert "| 7 |" in result["messages"][-1].content

    @patch("src.templated_sql_agent.agent._executor")
    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_execute_main_render_error_reports_to_user(
        self,
        mock_get_model: MagicMock,
        mock_executor: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "execute_main",
            "template_id": "product_stock",
            "extracted": {"product_id": "abc"},
            "lookup_vars": [],
            "clarification": "",
        })
        result = templated_sql_wrapper(_state("..."))
        mock_executor.execute.assert_not_called()
        content = result["messages"][-1].content
        assert "product_id" in content


class TestExecuteLookup:
    @patch("src.templated_sql_agent.agent._executor")
    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_execute_lookup_runs_lookup_sql(
        self,
        mock_get_model: MagicMock,
        mock_executor: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "execute_lookup",
            "template_id": "product_stock",
            "extracted": {},
            "lookup_vars": ["product_id"],
            "clarification": "",
        })
        mock_executor.execute.return_value = {
            "ok": True, "columns": ["id", "name", "category"],
            "rows": [(1, "A", "X")],
            "markdown": "| id | name | category |\n| 1 | A | X |",
            "error": None,
        }

        result = templated_sql_wrapper(_state("응 보여줘"))

        called_args = mock_executor.execute.call_args
        assert len(called_args[0]) == 1, (
            f"lookup은 params 없이 호출되어야 함. 실제: {called_args}"
        )
        called_sql = called_args[0][0]
        assert "FROM products" in called_sql
        assert "ORDER BY" in called_sql
        content = result["messages"][-1].content
        assert "| name |" in content or "| id |" in content

    @patch("src.templated_sql_agent.agent._executor")
    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_execute_lookup_skips_vars_without_lookup_sql(
        self,
        mock_get_model: MagicMock,
        mock_executor: MagicMock,
    ) -> None:
        # category_top_n_revenue의 n은 lookup_sql=None이다.
        mock_get_model.return_value = _llm_returning({
            "action": "execute_lookup",
            "template_id": "category_top_n_revenue",
            "extracted": {},
            "lookup_vars": ["n", "category"],
            "clarification": "",
        })
        mock_executor.execute.return_value = {
            "ok": True, "columns": ["category"], "rows": [("X",)],
            "markdown": "| category |\n|---|\n| X |", "error": None,
        }

        result = templated_sql_wrapper(_state("응"))

        # category만 lookup 가능 → executor 1회만 호출되어야 한다.
        assert mock_executor.execute.call_count == 1
        called_sql = mock_executor.execute.call_args[0][0]
        assert "DISTINCT category" in called_sql

    @patch("src.templated_sql_agent.agent._executor")
    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_execute_lookup_when_no_lookup_available(
        self,
        mock_get_model: MagicMock,
        mock_executor: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "execute_lookup",
            "template_id": "monthly_order_count",
            "extracted": {},
            "lookup_vars": ["year_month"],  # lookup_sql=None
            "clarification": "",
        })
        result = templated_sql_wrapper(_state("응"))
        mock_executor.execute.assert_not_called()
        content = result["messages"][-1].content
        assert "직접" in content or "값을" in content
