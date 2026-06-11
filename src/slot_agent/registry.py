"""슬롯 시나리오 레지스트리.

도메인 무지: 어떤 시나리오든 등록할 수 있고, 등록 검증과 조회/카탈로그
인터페이스만 제공한다. 실제 도메인 시나리오는 scenarios.py에서 정의한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.slot_agent.repository import Repository

# lookup: 확정된 상위 슬롯(slots)을 받아 후보 행 리스트를 반환.
LookupFn = Callable[[Repository, dict[str, Any]], list[dict[str, Any]]]
# metric: 확정된 모든 슬롯을 받아 {"label", "columns", "rows"} 결과를 반환.
MetricFn = Callable[[Repository, dict[str, Any]], dict[str, Any]]
# validator: free-value 슬롯의 원시 입력을 검증·정제. 실패 시 ValueError.
ValidatorFn = Callable[[Any], Any]


@dataclass(frozen=True)
class Slot:
    """시나리오의 단일 슬롯 정의.

    Attributes:
        name: 슬롯 키 (LLM 추출/resolve에서 사용).
        description: 사용자/LLM에 노출되는 의미.
        lookup: 후보값 조회 함수. None이면 free-value 슬롯(직접 입력).
        parent: 상위 의존 슬롯명. None이면 독립 필터.
        value_key: 후보 행에서 슬롯의 정규(canonical) 값으로 쓸 필드.
        label_key: 후보 행에서 사용자에게 보여줄 라벨 필드.
        validator: free-value 슬롯의 형식 검증/정제 함수.
    """

    name: str
    description: str
    lookup: LookupFn | None = None
    parent: str | None = None
    value_key: str = "id"
    label_key: str = "name"
    validator: ValidatorFn | None = None


@dataclass(frozen=True)
class Scenario:
    """단일 조회 시나리오 정의."""

    id: str
    label: str
    slots: tuple[Slot, ...]
    metric: MetricFn


class ScenarioRegistry:
    """시나리오 등록·조회 레지스트리."""

    def __init__(self) -> None:
        self._scenarios: list[Scenario] = []
        self._by_id: dict[str, Scenario] = {}

    def register(self, scenario: Scenario) -> None:
        """시나리오를 등록한다. 검증 실패 시 ValueError.

        검증: (1) id 중복 금지, (2) 슬롯명 중복 금지,
        (3) 각 슬롯의 parent는 앞선 슬롯에 존재해야 함(순서가 의존성을 보장).
        """
        if scenario.id in self._by_id:
            raise ValueError(f"중복 시나리오 id: {scenario.id}")

        seen: set[str] = set()
        for slot in scenario.slots:
            if slot.name in seen:
                raise ValueError(
                    f"시나리오 '{scenario.id}': 슬롯명 중복 {slot.name}"
                )
            if slot.parent is not None and slot.parent not in seen:
                raise ValueError(
                    f"시나리오 '{scenario.id}': 슬롯 '{slot.name}'의 parent "
                    f"'{slot.parent}'가 앞선 슬롯에 없습니다."
                )
            seen.add(slot.name)

        self._scenarios.append(scenario)
        self._by_id[scenario.id] = scenario

    @property
    def scenarios(self) -> list[Scenario]:
        """등록된 모든 시나리오를 등록 순서대로 반환(방어 복사)."""
        return list(self._scenarios)

    def get(self, scenario_id: str) -> Scenario | None:
        """id로 시나리오 조회. 없으면 None."""
        return self._by_id.get(scenario_id)

    def build_router_description(self) -> str:
        """라우터 description으로 쓸 문자열을 합성한다."""
        header = (
            "사전 정의된 조회 시나리오의 슬롯을 단계적으로 채워 최종 지표를 "
            "조회합니다. 빈 슬롯은 DB에서 후보값을 조회해 사용자에게 안내하고, "
            "사용자가 고르면 다음 슬롯으로 진행합니다."
        )
        if not self._scenarios:
            return header
        lines = [header, "다음 종류의 조회를 다룹니다:"]
        for s in self._scenarios:
            lines.append(f"- {s.label}")
        return "\n".join(lines)

    def build_catalog_for_llm(self) -> str:
        """slot 에이전트 시스템 프롬프트의 시나리오 카탈로그 섹션."""
        if not self._scenarios:
            return "(등록된 시나리오 없음)"
        blocks: list[str] = []
        for s in self._scenarios:
            lines = [f"### scenario_id: {s.id}", f"의도: {s.label}", "슬롯:"]
            for slot in s.slots:
                dep = f", 상위 슬롯: {slot.parent}" if slot.parent else ""
                kind = "DB 후보값 조회 가능" if slot.lookup else "직접 입력 값"
                lines.append(
                    f"- {slot.name}: {slot.description} ({kind}{dep})"
                )
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)


# 글로벌 시나리오 레지스트리 인스턴스
scenario_registry = ScenarioRegistry()
