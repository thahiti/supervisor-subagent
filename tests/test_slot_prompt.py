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


def test_prompt_names_extraction_targets() -> None:
    prompt = build_system_prompt(_registry())
    # 구조화 출력 스키마와 짝을 이루는 추출 항목을 언급해야 한다.
    assert "scenario_id" in prompt
    assert "slots" in prompt


def test_prompt_does_not_instruct_json_output() -> None:
    prompt = build_system_prompt(_registry())
    # 더 이상 LLM에게 JSON을 출력하라고 지시하지 않는다(구조화 출력으로 대체).
    assert "JSON" not in prompt


def test_prompt_forbids_guessing() -> None:
    prompt = build_system_prompt(_registry())
    assert "추측" in prompt or "임의" in prompt


def test_slot_extraction_schema_defaults() -> None:
    from src.slot_agent.prompt import SlotExtraction

    e = SlotExtraction()
    assert e.scenario_id is None
    assert e.slots == {}
