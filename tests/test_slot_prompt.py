"""슬롯 에이전트 시스템 프롬프트 빌더 테스트."""

from __future__ import annotations

from src.slot_agent.prompt import build_system_prompt
from src.slot_agent.registry import Scenario, ScenarioRegistry, Slot


def _registry() -> ScenarioRegistry:
    reg = ScenarioRegistry()
    reg.register(Scenario(
        id="regional_sales", label="지역별 매출",
        slots=(
            Slot("country", "나라", lookup=lambda r, s: []),
            Slot("branch", "지점", lookup=lambda r, s: [], parent="country"),
        ),
        metric=lambda r, s: {"label": "x", "columns": [], "rows": []},
    ))
    return reg


def test_prompt_embeds_catalog() -> None:
    prompt = build_system_prompt(_registry())
    assert "scenario_id: regional_sales" in prompt
    assert "country" in prompt and "branch" in prompt


def test_prompt_specifies_json_output() -> None:
    prompt = build_system_prompt(_registry())
    assert '"scenario_id"' in prompt
    assert '"slots"' in prompt


def test_prompt_forbids_guessing() -> None:
    prompt = build_system_prompt(_registry())
    assert "추측" in prompt or "임의" in prompt
