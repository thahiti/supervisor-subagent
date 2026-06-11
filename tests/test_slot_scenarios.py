"""도메인 시나리오 lookup/metric을 실제 가상 DB로 검증."""

from __future__ import annotations

from src.slot_agent.registry import Scenario, ScenarioRegistry
from src.slot_agent.repository import Repository, _DEFAULT_DATA_DIR
from src.slot_agent.resolve import Ready, resolve


def _registry() -> ScenarioRegistry:
    # scenarios 모듈 import는 전역 scenario_registry에 등록하는 부수효과를 낸다.
    from src.slot_agent import scenarios  # noqa: F401
    from src.slot_agent.registry import scenario_registry
    return scenario_registry


def _repo() -> Repository:
    return Repository.from_dir(_DEFAULT_DATA_DIR)


class TestRegistration:
    def test_three_scenarios_registered(self) -> None:
        ids = {s.id for s in _registry().scenarios}
        assert {"regional_sales", "product_stock", "new_signups"} <= ids


class TestRegionalSales:
    def test_full_resolve_then_metric(self) -> None:
        sc = _registry().get("regional_sales")
        out = resolve(_repo(), sc, {"country": "한국", "branch": "강남점"})
        assert isinstance(out, Ready)
        result = sc.metric(_repo(), out.slots)
        # 강남점(11)의 월별 매출 3건이 month 오름차순.
        assert result["columns"] == ["month", "amount"]
        assert result["rows"][0] == ("2026-01", 1200)
        assert len(result["rows"]) == 3


class TestProductStock:
    def test_category_filters_products(self) -> None:
        sc = _registry().get("product_stock")
        out = resolve(_repo(), sc, {"category": "전자"})
        # category 채워짐 → product 후보는 전자 카테고리만.
        from src.slot_agent.resolve import AskSlot
        assert isinstance(out, AskSlot)
        assert {c["name"] for c in out.candidates} == {"노트북", "모니터"}

    def test_metric_returns_stock(self) -> None:
        sc = _registry().get("product_stock")
        out = resolve(_repo(), sc, {"category": "전자", "product": "노트북"})
        assert isinstance(out, Ready)
        result = sc.metric(_repo(), out.slots)
        assert result["rows"] == [("노트북", 34)]


class TestNewSignups:
    def test_independent_filters_and_free_month(self) -> None:
        sc = _registry().get("new_signups")
        out = resolve(_repo(), sc, {"channel": "검색광고", "month": "2026-01"})
        assert isinstance(out, Ready)
        result = sc.metric(_repo(), out.slots)
        assert result["rows"] == [("검색광고", "2026-01", 120)]
