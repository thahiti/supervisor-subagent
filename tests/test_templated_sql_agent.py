"""templated_sql 에이전트 단위 테스트.

LLM 호출 없이 프롬프트 합성과 wrapper 분기 로직을 검증한다.
"""

from __future__ import annotations

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
