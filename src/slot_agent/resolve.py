"""결정적 슬롯 해소.

확정된 상위 슬롯으로 후보를 조회하고, 사용자가 준 값이 후보에 존재하면
정규값(value_key)으로 매칭한다(grounding). 첫 번째로 채워지지 않은 슬롯을
만나면 그 슬롯을 묻는다. LLM에 의존하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.slot_agent.registry import Scenario, Slot
from src.slot_agent.repository import Repository


@dataclass
class AskSlot:
    """다음으로 채워야 할 슬롯과 그 후보값들. free-value면 candidates는 []."""

    slot: Slot
    candidates: list[dict[str, Any]]


@dataclass
class Ready:
    """모든 슬롯이 확정됨. slots는 슬롯명 → 정규값."""

    slots: dict[str, Any]


def resolve(
    repo: Repository,
    scenario: Scenario,
    extracted: dict[str, Any],
) -> AskSlot | Ready:
    """슬롯을 선언 순서대로 해소한다.

    슬롯 순서가 의존성을 보장한다(parent는 항상 앞에 있음). 채워지지 않았거나
    grounding에 실패한 첫 슬롯에서 AskSlot을 반환하고, 모두 확정되면 Ready.
    """
    confirmed: dict[str, Any] = {}
    for slot in scenario.slots:
        raw = extracted.get(slot.name)

        if slot.lookup is None:
            value = _accept_free(raw, slot)
            if value is None:
                return AskSlot(slot=slot, candidates=[])
            confirmed[slot.name] = value
            continue

        candidates = slot.lookup(repo, confirmed)
        value = _match(raw, slot, candidates) if raw is not None else None
        if value is None:
            return AskSlot(slot=slot, candidates=candidates)
        confirmed[slot.name] = value

    return Ready(slots=confirmed)


def _accept_free(raw: Any, slot: Slot) -> Any | None:
    """free-value 슬롯 값 수용. 비었으면 None, validator 실패해도 None."""
    if raw is None or str(raw).strip() == "":
        return None
    if slot.validator is not None:
        try:
            return slot.validator(raw)
        except (ValueError, TypeError):
            return None
    return str(raw).strip()


def _match(raw: Any, slot: Slot, candidates: list[dict[str, Any]]) -> Any | None:
    """raw를 후보의 value_key 또는 label_key와 매칭해 정규값을 반환.

    매칭 순서: (1) value_key 정확 일치(원시/문자열 양쪽 비교),
    (2) label_key 대소문자 무시 일치. 어느 것도 없으면 None(grounding 실패).
    """
    for cand in candidates:
        cv = cand.get(slot.value_key)
        if cv == raw or str(cv) == str(raw).strip():
            return cv

    needle = str(raw).strip().casefold()
    for cand in candidates:
        lv = cand.get(slot.label_key)
        if lv is not None and str(lv).strip().casefold() == needle:
            return cand.get(slot.value_key)

    return None
