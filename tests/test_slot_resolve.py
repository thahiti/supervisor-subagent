"""결정적 슬롯 해소(resolve) 단위 테스트. LLM 없이 동작."""

from __future__ import annotations

from src.slot_agent.registry import Scenario, Slot
from src.slot_agent.repository import Repository
from src.slot_agent.resolve import AskSlot, Ready, resolve


def _repo() -> Repository:
    return Repository(tables={
        "countries": [{"id": 1, "name": "한국"}, {"id": 2, "name": "일본"}],
        "branches": [
            {"id": 11, "country_id": 1, "name": "강남점"},
            {"id": 21, "country_id": 2, "name": "도쿄점"},
        ],
    })


def _metric(repo, slots):
    return {"label": "x", "columns": ["a"], "rows": [(1,)]}


def _scenario() -> Scenario:
    return Scenario(
        id="regional_sales", label="지역별 매출",
        slots=(
            Slot("country", "나라", lookup=lambda r, s: r.all("countries")),
            Slot("branch", "지점", parent="country",
                 lookup=lambda r, s: r.where("branches", country_id=s["country"])),
        ),
        metric=_metric,
    )


class TestResolve:
    def test_no_slots_asks_first(self) -> None:
        out = resolve(_repo(), _scenario(), {})
        assert isinstance(out, AskSlot)
        assert out.slot.name == "country"
        assert {c["name"] for c in out.candidates} == {"한국", "일본"}

    def test_first_filled_asks_second_filtered_by_parent(self) -> None:
        out = resolve(_repo(), _scenario(), {"country": "한국"})
        assert isinstance(out, AskSlot)
        assert out.slot.name == "branch"
        # 한국(country_id=1) 지점만 후보로 나와야 한다 (grounding + 의존 필터).
        assert {c["name"] for c in out.candidates} == {"강남점"}

    def test_match_by_id(self) -> None:
        out = resolve(_repo(), _scenario(), {"country": 1, "branch": 11})
        assert isinstance(out, Ready)
        assert out.slots == {"country": 1, "branch": 11}

    def test_match_by_label_returns_canonical_id(self) -> None:
        out = resolve(_repo(), _scenario(), {"country": "한국", "branch": "강남점"})
        assert isinstance(out, Ready)
        assert out.slots == {"country": 1, "branch": 11}

    def test_invalid_value_not_in_db_is_rejected_and_reasked(self) -> None:
        # 존재하지 않는 지점명 → grounding 실패 → 다시 branch를 묻는다.
        out = resolve(_repo(), _scenario(), {"country": "한국", "branch": "없는점"})
        assert isinstance(out, AskSlot)
        assert out.slot.name == "branch"

    def test_label_match_is_case_insensitive(self) -> None:
        repo = Repository(tables={"items": [{"id": 1, "name": "Coffee"}]})
        sc = Scenario(
            id="s", label="l",
            slots=(Slot("it", "아이템", lookup=lambda r, s: r.all("items")),),
            metric=_metric,
        )
        out = resolve(repo, sc, {"it": "coffee"})
        assert isinstance(out, Ready) and out.slots == {"it": 1}


class TestFreeValueSlot:
    def _free_scenario(self) -> Scenario:
        def _validate_month(raw):
            text = str(raw).strip()
            if len(text) != 7 or text[4] != "-":
                raise ValueError("형식 오류")
            return text
        return Scenario(
            id="signups", label="가입",
            slots=(
                Slot("channel", "채널", lookup=lambda r, s: r.all("countries")),
                Slot("month", "월", lookup=None, validator=_validate_month),
            ),
            metric=_metric,
        )

    def test_missing_free_slot_is_asked_with_no_candidates(self) -> None:
        out = resolve(_repo(), self._free_scenario(), {"channel": 1})
        assert isinstance(out, AskSlot)
        assert out.slot.name == "month"
        assert out.candidates == []

    def test_valid_free_value_accepted(self) -> None:
        out = resolve(_repo(), self._free_scenario(),
                      {"channel": 1, "month": "2026-01"})
        assert isinstance(out, Ready)
        assert out.slots == {"channel": 1, "month": "2026-01"}

    def test_invalid_free_value_reasked(self) -> None:
        out = resolve(_repo(), self._free_scenario(),
                      {"channel": 1, "month": "2026/01"})
        assert isinstance(out, AskSlot)
        assert out.slot.name == "month"
