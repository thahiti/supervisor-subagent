"""슬롯 시나리오 레지스트리 단위 테스트."""

from __future__ import annotations

import pytest

from src.slot_agent.registry import Scenario, ScenarioRegistry, Slot


def _country_lookup(repo, slots):
    return repo.all("countries")


def _branch_lookup(repo, slots):
    return repo.where("branches", country_id=slots["country"])


def _metric(repo, slots):
    return {"label": "x", "columns": ["a"], "rows": [(1,)]}


def _scenario() -> Scenario:
    return Scenario(
        id="regional_sales",
        label="지역별 매출",
        slots=(
            Slot(name="country", description="나라", lookup=_country_lookup),
            Slot(name="branch", description="지점", lookup=_branch_lookup,
                 parent="country"),
        ),
        metric=_metric,
    )


class TestRegister:
    def test_register_then_get(self) -> None:
        reg = ScenarioRegistry()
        reg.register(_scenario())
        assert reg.get("regional_sales").label == "지역별 매출"

    def test_get_unknown_returns_none(self) -> None:
        assert ScenarioRegistry().get("nope") is None

    def test_duplicate_id_raises(self) -> None:
        reg = ScenarioRegistry()
        reg.register(_scenario())
        with pytest.raises(ValueError, match="중복"):
            reg.register(_scenario())

    def test_duplicate_slot_name_raises(self) -> None:
        reg = ScenarioRegistry()
        with pytest.raises(ValueError, match="슬롯명"):
            reg.register(Scenario(
                id="dup", label="l",
                slots=(Slot("x", "x1", lookup=_country_lookup),
                       Slot("x", "x2", lookup=_country_lookup)),
                metric=_metric,
            ))

    def test_parent_must_precede_raises(self) -> None:
        reg = ScenarioRegistry()
        with pytest.raises(ValueError, match="parent"):
            reg.register(Scenario(
                id="bad", label="l",
                slots=(Slot("child", "c", lookup=_branch_lookup,
                            parent="missing"),),
                metric=_metric,
            ))


class TestCatalog:
    def test_router_description_lists_labels(self) -> None:
        reg = ScenarioRegistry()
        reg.register(_scenario())
        desc = reg.build_router_description()
        assert "지역별 매출" in desc

    def test_catalog_lists_scenario_and_slots(self) -> None:
        reg = ScenarioRegistry()
        reg.register(_scenario())
        cat = reg.build_catalog_for_llm()
        assert "scenario_id: regional_sales" in cat
        assert "country" in cat and "branch" in cat
        assert "상위 슬롯: country" in cat  # parent 노출
