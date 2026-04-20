"""response_generator 단위 테스트.

LLM 호출 없이 프롬프트 구성과 노드 로직을 검증한다.
"""

from __future__ import annotations

from src.agents.response_generator.prompt import RESPONSE_GENERATOR_SYSTEM_PROMPT


class TestPrompt:
    def test_prompt_is_nonempty_string(self) -> None:
        assert isinstance(RESPONSE_GENERATOR_SYSTEM_PROMPT, str)
        assert len(RESPONSE_GENERATOR_SYSTEM_PROMPT) > 0

    def test_prompt_instructs_to_ignore_json(self) -> None:
        assert "JSON" in RESPONSE_GENERATOR_SYSTEM_PROMPT
