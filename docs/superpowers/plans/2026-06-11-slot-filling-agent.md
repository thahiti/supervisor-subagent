# 슬롯 채우기(Slot-Filling) 에이전트 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 시나리오별 질문 흐름을 하드코딩하지 않고, 모든 조회를 "슬롯 채우기" 문제로 일반화한 독립 신규 서브에이전트(`slot`)를 추가한다. 빈 슬롯의 후보값은 가상 DB에서 grounding하여 안내하고, 모든 슬롯이 확정되면 최종 지표를 조회한다.

**Architecture:** 기존 `templated_sql_agent`와 동일한 단일 패스 노드 패턴을 따른다 — checkpointer/`interrupt()`를 쓰지 않고, 멀티턴 HITL은 `query_rewriter` + 매 턴 재호출로 처리한다. LLM은 (시나리오 매칭 + 메시지에 드러난 슬롯 추출)만 담당하고, 후보값 grounding·슬롯 의존성 해소·지표 조회는 결정적 Python 코드가 수행한다. 가상 DB는 JSON 파일을 메모리로 올린 repository로 추상화하여, 나중에 진짜 DB로 교체해도 시나리오/에이전트 코드는 그대로다.

**Tech Stack:** Python 3.11, LangGraph(기존 그래프), `langchain-core` 메시지, pytest. 신규 외부 의존성 없음.

---

## 설계 결정 (스펙 대비 차이)

원본 스펙은 LangGraph `interrupt()` + checkpointer 기반 HITL을 제안했으나, **본 프로젝트의 기존 패턴(checkpointer 없음, `query_rewriter` 의존 멀티턴)을 유지하기로 결정**했다. 따라서:

- 그래프는 기존대로 checkpointer 없이 컴파일되고, 슬롯 에이전트는 단일 패스 노드다.
- "다음 빈 슬롯을 묻는다"는 응답 메시지를 반환하고 종료한다. 사용자의 답은 다음 턴에 `query_rewriter`가 맥락 보충 → `router` → `slot` 노드로 다시 흐른다.
- 스펙의 나머지(JSON repository, declarative 슬롯 레지스트리, slot `parent` 의존, grounding, 독립 신규 서브시스템)는 그대로 반영한다.

LLM 책임을 "시나리오 매칭 + 슬롯 추출"로만 좁히고 resolve/grounding을 Python으로 옮긴 이유: (1) grounding(존재하지 않는 값 거부)이 결정적으로 검증 가능, (2) resolve 루프를 LLM 없이 단위 테스트 가능, (3) 슬롯 의존성 그래프를 코드로 한 곳에서 강제.

## 파일 구조

```
src/slot_agent/
├── __init__.py        # agent import로 등록 트리거 (slot_wrapper 노출)
├── repository.py      # 가상 DB: JSON 테이블 저장소 + 전역 인스턴스 접근자
├── registry.py        # Slot/Scenario dataclass + ScenarioRegistry + 전역 인스턴스
├── resolve.py         # 결정적 슬롯 해소 + 후보값 grounding (LLM 무관)
├── scenarios.py       # 3개 시나리오 선언 (lookup/metric 함수 포함, import 시 등록)
├── prompt.py          # 추출용 시스템 프롬프트 빌더
└── agent.py           # @registry.agent("slot") 노드 wrapper + 응답 포매팅

res/slot_db/           # 가상 DB 데이터 파일 (Task 2에서 생성)
├── countries.json  branches.json  sales.json          # regional_sales
├── categories.json products.json  inventory.json       # product_stock
└── channels.json   signups.json                        # new_signups

scripts/gen_slot_db.py # 테스트 데이터 결정적 생성 스크립트

tests/
├── test_slot_repository.py
├── test_slot_registry.py
├── test_slot_resolve.py
├── test_slot_scenarios.py
├── test_slot_prompt.py
└── test_slot_agent.py
```

각 파일은 단일 책임을 가진다: `repository`(데이터 접근), `registry`(시나리오 선언 구조 + 검증), `resolve`(슬롯 해소 알고리즘), `scenarios`(도메인 지식), `prompt`/`agent`(LLM 연동·표현). 도메인 지식은 `scenarios.py`에만 모이고, 나머지는 도메인 무지다 — 새 시나리오 추가가 `scenarios.py` 한 곳으로 끝난다.

---

## Task 1: 가상 DB Repository

JSON 파일을 메모리로 올려 도메인 무지한 테이블 조회(`all`/`where`)만 노출한다.

**Files:**
- Create: `src/slot_agent/__init__.py` (이 태스크에서는 빈 파일)
- Create: `src/slot_agent/repository.py`
- Test: `tests/test_slot_repository.py`

- [ ] **Step 1: 빈 패키지 파일 생성**

`src/slot_agent/__init__.py` 를 빈 파일로 생성한다 (Task 8에서 import 추가).

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_slot_repository.py`:

```python
"""슬롯 에이전트 가상 DB repository 단위 테스트."""

from __future__ import annotations

import json

import pytest

from src.slot_agent.repository import Repository


def _repo() -> Repository:
    return Repository(tables={
        "countries": [{"id": 1, "name": "한국"}, {"id": 2, "name": "일본"}],
        "branches": [
            {"id": 11, "country_id": 1, "name": "강남점"},
            {"id": 12, "country_id": 1, "name": "부산점"},
            {"id": 21, "country_id": 2, "name": "도쿄점"},
        ],
    })


class TestQuery:
    def test_all_returns_every_row(self) -> None:
        assert len(_repo().all("countries")) == 2

    def test_all_unknown_table_raises(self) -> None:
        with pytest.raises(KeyError):
            _repo().all("nope")

    def test_all_returns_defensive_copy(self) -> None:
        repo = _repo()
        repo.all("countries")[0]["name"] = "변조"
        assert repo.all("countries")[0]["name"] == "한국"

    def test_where_filters_by_equality(self) -> None:
        rows = _repo().where("branches", country_id=1)
        assert {r["name"] for r in rows} == {"강남점", "부산점"}

    def test_where_multiple_filters(self) -> None:
        rows = _repo().where("branches", country_id=1, name="강남점")
        assert len(rows) == 1 and rows[0]["id"] == 11

    def test_where_no_match_returns_empty(self) -> None:
        assert _repo().where("branches", country_id=999) == []


class TestFromDir:
    def test_from_dir_loads_files_by_stem(self, tmp_path) -> None:
        (tmp_path / "widgets.json").write_text(
            json.dumps([{"id": 1, "name": "a"}]), encoding="utf-8"
        )
        repo = Repository.from_dir(tmp_path)
        assert repo.all("widgets") == [{"id": 1, "name": "a"}]
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/test_slot_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.slot_agent.repository'`

- [ ] **Step 4: 최소 구현 작성**

`src/slot_agent/repository.py`:

```python
"""슬롯 에이전트의 가상 DB 레이어.

실제 DB 대신 JSON 파일을 읽어 메모리 dict로 올려두고, 도메인 무지한 테이블
조회 인터페이스(all/where)만 노출한다. 나중에 이 클래스의 내부 저장소만
진짜 DB로 교체하면 시나리오/에이전트 코드는 그대로다 — 핵심 추상화 경계.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# repository.py 기준: parents[0]=slot_agent, [1]=src, [2]=repo root
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "res" / "slot_db"


class Repository:
    """JSON 테이블 저장소. 테이블명(파일 stem) → 행(dict) 리스트."""

    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self._tables = tables

    @classmethod
    def from_dir(cls, data_dir: str | Path) -> "Repository":
        """디렉터리 내 모든 *.json을 로드한다. 파일명(stem)이 테이블명."""
        tables: dict[str, list[dict[str, Any]]] = {}
        for path in sorted(Path(data_dir).glob("*.json")):
            with path.open(encoding="utf-8") as f:
                tables[path.stem] = json.load(f)
        return cls(tables)

    def all(self, table: str) -> list[dict[str, Any]]:
        """테이블의 모든 행을 반환(행 단위 방어 복사). 미등록 테이블이면 KeyError."""
        if table not in self._tables:
            raise KeyError(f"등록되지 않은 테이블: {table}")
        return [dict(row) for row in self._tables[table]]

    def where(self, table: str, **filters: Any) -> list[dict[str, Any]]:
        """모든 filters를 동등 비교로 만족하는 행만 반환."""
        return [
            row for row in self.all(table)
            if all(row.get(k) == v for k, v in filters.items())
        ]


_repository: Repository | None = None


def get_repository() -> Repository:
    """전역 repository 인스턴스. 최초 호출 시 res/slot_db에서 lazy 로드."""
    global _repository
    if _repository is None:
        _repository = Repository.from_dir(_DEFAULT_DATA_DIR)
    return _repository


def set_repository(repo: Repository | None) -> None:
    """전역 repository를 교체(테스트용). None이면 다음 get에서 재로딩."""
    global _repository
    _repository = repo
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_slot_repository.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: 커밋**

```bash
git add src/slot_agent/__init__.py src/slot_agent/repository.py tests/test_slot_repository.py
git commit -m "feat(slot-agent): add JSON-backed virtual DB repository"
```

---

## Task 2: 테스트 데이터 생성 (테스트 데이터 생성 계획)

가상 DB의 데이터 파일을 **결정적**으로 생성하는 스크립트와 JSON 파일을 만든다.

### 데이터 설계 원칙

- **Star schema**: 차원(dimension) 테이블과 팩트(fact) 테이블을 분리한다. 슬롯 후보는 차원에서, 최종 지표는 팩트에서 조회된다.
- **세 가지 모양**을 의도적으로 포함해 같은 엔진이 모두 처리됨을 드러낸다:
  - 계층형 2슬롯 (`regional_sales`: country → branch)
  - 다른 도메인의 계층형 2슬롯 (`product_stock`: category → product)
  - 비계층형(독립 필터) + free-value 슬롯 (`new_signups`: channel + month)
- **결정성/재현성**: 난수·시간(`Date.now`)을 쓰지 않고 데이터를 코드 리터럴로 고정한다. 스크립트를 몇 번 돌려도 동일한 파일이 나와야 grounding 테스트가 안정적이다.
- **규모**: 단위 테스트·데모에 필요한 최소량(나라 2, 지점 3, 카테고리 2, 제품 3, 채널 2). grounding과 의존 필터링을 보이기엔 충분하고, 사람이 표를 읽기에도 부담이 없다.

### 테이블 스키마

| 파일 | 역할 | 컬럼 |
|---|---|---|
| `countries.json` | dim | `id, name` |
| `branches.json` | dim (country 종속) | `id, country_id, name` |
| `sales.json` | fact | `branch_id, month, amount` |
| `categories.json` | dim | `id, name` |
| `products.json` | dim (category 종속) | `id, category_id, name` |
| `inventory.json` | fact | `product_id, stock` |
| `channels.json` | dim | `id, name` |
| `signups.json` | fact | `channel_id, month, count` |

**Files:**
- Create: `scripts/gen_slot_db.py`
- Create (스크립트 산출물): `res/slot_db/*.json` (8개 파일)
- Test: `tests/test_slot_repository.py` 에 생성물 검증 테스트 추가

- [ ] **Step 1: 생성 스크립트 작성**

`scripts/gen_slot_db.py`:

```python
"""슬롯 에이전트 가상 DB(res/slot_db/*.json)를 결정적으로 생성한다.

난수·현재시각을 쓰지 않고 데이터를 리터럴로 고정한다. 재실행해도 동일한
파일이 생성되어 grounding 테스트가 안정적이다.

실행:
    uv run python scripts/gen_slot_db.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "res" / "slot_db"

TABLES: dict[str, list[dict]] = {
    # --- regional_sales: country -> branch -> 월별 매출 ---
    "countries": [
        {"id": 1, "name": "한국"},
        {"id": 2, "name": "일본"},
    ],
    "branches": [
        {"id": 11, "country_id": 1, "name": "강남점"},
        {"id": 12, "country_id": 1, "name": "부산점"},
        {"id": 21, "country_id": 2, "name": "도쿄점"},
    ],
    "sales": [
        {"branch_id": 11, "month": "2026-01", "amount": 1200},
        {"branch_id": 11, "month": "2026-02", "amount": 1500},
        {"branch_id": 11, "month": "2026-03", "amount": 1800},
        {"branch_id": 12, "month": "2026-01", "amount": 800},
        {"branch_id": 12, "month": "2026-02", "amount": 950},
        {"branch_id": 21, "month": "2026-01", "amount": 2200},
    ],
    # --- product_stock: category -> product -> 재고 ---
    "categories": [
        {"id": 1, "name": "전자"},
        {"id": 2, "name": "식품"},
    ],
    "products": [
        {"id": 101, "category_id": 1, "name": "노트북"},
        {"id": 102, "category_id": 1, "name": "모니터"},
        {"id": 201, "category_id": 2, "name": "원두커피"},
    ],
    "inventory": [
        {"product_id": 101, "stock": 34},
        {"product_id": 102, "stock": 12},
        {"product_id": 201, "stock": 240},
    ],
    # --- new_signups: channel + month(자유 입력) -> 신규 가입자 수 ---
    "channels": [
        {"id": 1, "name": "검색광고"},
        {"id": 2, "name": "추천"},
    ],
    "signups": [
        {"channel_id": 1, "month": "2026-01", "count": 120},
        {"channel_id": 1, "month": "2026-02", "count": 150},
        {"channel_id": 2, "month": "2026-01", "count": 80},
    ],
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in TABLES.items():
        path = OUT_DIR / f"{name}.json"
        path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 스크립트 실행하여 데이터 파일 생성**

Run: `uv run python scripts/gen_slot_db.py`
Expected: `wrote .../res/slot_db/countries.json (2 rows)` 등 8줄 출력. `res/slot_db/`에 8개 JSON 파일 생성.

- [ ] **Step 3: 생성물 검증 테스트 추가 (실패 확인)**

`tests/test_slot_repository.py` 끝에 추가:

```python
class TestGeneratedData:
    """scripts/gen_slot_db.py 산출물이 기대 구조로 로드되는지 검증."""

    def test_default_repository_loads_all_tables(self) -> None:
        from src.slot_agent.repository import Repository, _DEFAULT_DATA_DIR

        repo = Repository.from_dir(_DEFAULT_DATA_DIR)
        assert len(repo.all("countries")) == 2
        assert len(repo.where("branches", country_id=1)) == 2
        assert len(repo.all("products")) == 3
        assert repo.where("inventory", product_id=101)[0]["stock"] == 34
        assert len(repo.where("signups", channel_id=1, month="2026-01")) == 1
```

Run: `uv run pytest tests/test_slot_repository.py::TestGeneratedData -v`
Expected: 데이터 파일이 이미 Step 2에서 생성되었으므로 PASS. (파일이 없으면 FAIL — 그 경우 Step 2를 먼저 수행했는지 확인.)

- [ ] **Step 4: .gitignore 확인 후 커밋**

생성된 JSON은 테스트 fixture이므로 커밋 대상이다. `.gitignore`에 `res/slot_db/`가 없는지 확인한다.

```bash
git add scripts/gen_slot_db.py res/slot_db/*.json tests/test_slot_repository.py
git commit -m "feat(slot-agent): add deterministic virtual-DB test data generator"
```

---

## Task 3: 시나리오 레지스트리 (declarative 구조)

`Slot`/`Scenario` dataclass와 등록 검증을 제공한다. 도메인 무지.

**Files:**
- Create: `src/slot_agent/registry.py`
- Test: `tests/test_slot_registry.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_slot_registry.py`:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_slot_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.slot_agent.registry'`

- [ ] **Step 3: 최소 구현 작성**

`src/slot_agent/registry.py`:

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_slot_registry.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/slot_agent/registry.py tests/test_slot_registry.py
git commit -m "feat(slot-agent): add declarative scenario/slot registry"
```

---

## Task 4: 슬롯 해소(resolve) + 후보값 grounding

확정된 상위 슬롯으로 후보를 조회하고, 사용자가 준 값이 후보에 존재하면 정규값으로 매칭(grounding), 없으면 다음 빈 슬롯을 묻는 결정적 알고리즘. LLM 무관.

**Files:**
- Create: `src/slot_agent/resolve.py`
- Test: `tests/test_slot_resolve.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_slot_resolve.py`:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_slot_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.slot_agent.resolve'`

- [ ] **Step 3: 최소 구현 작성**

`src/slot_agent/resolve.py`:

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_slot_resolve.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/slot_agent/resolve.py tests/test_slot_resolve.py
git commit -m "feat(slot-agent): add deterministic slot resolution with grounding"
```

---

## Task 5: 도메인 시나리오 3종 선언

`scenarios.py`에 3개 시나리오를 lookup/metric 함수와 함께 선언한다. 모듈 import 시 `scenario_registry`에 등록된다.

**Files:**
- Create: `src/slot_agent/scenarios.py`
- Test: `tests/test_slot_scenarios.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_slot_scenarios.py`:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_slot_scenarios.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.slot_agent.scenarios'`

- [ ] **Step 3: 최소 구현 작성**

`src/slot_agent/scenarios.py`:

```python
"""슬롯 에이전트 도메인 시나리오 카탈로그.

모듈 import 시 부수효과로 scenario_registry에 모든 시나리오가 등록된다.
도메인 지식(lookup/metric, 테이블/컬럼명)은 이 파일에만 모인다. 새 시나리오
추가는 이 파일에 lookup/metric 함수와 Scenario 선언을 더하는 것으로 끝난다.
"""

from __future__ import annotations

import re
from typing import Any

from src.slot_agent.registry import Scenario, Slot, scenario_registry
from src.slot_agent.repository import Repository

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def _validate_month(raw: Any) -> str:
    text = str(raw).strip()
    if not _MONTH_RE.match(text):
        raise ValueError(f"YYYY-MM 형식이 아닙니다: {raw!r}")
    return text


# --- regional_sales: country → branch → 월별 매출 ---
def _list_countries(repo: Repository, slots: dict) -> list[dict]:
    return repo.all("countries")


def _list_branches(repo: Repository, slots: dict) -> list[dict]:
    return repo.where("branches", country_id=slots["country"])


def _get_sales(repo: Repository, slots: dict) -> dict:
    rows = repo.where("sales", branch_id=slots["branch"])
    rows.sort(key=lambda r: r["month"])
    return {
        "label": "월별 매출액",
        "columns": ["month", "amount"],
        "rows": [(r["month"], r["amount"]) for r in rows],
    }


scenario_registry.register(Scenario(
    id="regional_sales",
    label="지역별 매출 조회",
    slots=(
        Slot(name="country", description="나라", lookup=_list_countries),
        Slot(name="branch", description="지점", lookup=_list_branches,
             parent="country"),
    ),
    metric=_get_sales,
))


# --- product_stock: category → product → 재고 수량 ---
def _list_categories(repo: Repository, slots: dict) -> list[dict]:
    return repo.all("categories")


def _list_products(repo: Repository, slots: dict) -> list[dict]:
    return repo.where("products", category_id=slots["category"])


def _get_stock(repo: Repository, slots: dict) -> dict:
    products = repo.where("products", id=slots["product"])
    inventory = repo.where("inventory", product_id=slots["product"])
    name = products[0]["name"] if products else str(slots["product"])
    stock = inventory[0]["stock"] if inventory else 0
    return {
        "label": "제품 재고 수량",
        "columns": ["product", "stock"],
        "rows": [(name, stock)],
    }


scenario_registry.register(Scenario(
    id="product_stock",
    label="제품 재고 조회",
    slots=(
        Slot(name="category", description="제품 카테고리", lookup=_list_categories),
        Slot(name="product", description="제품", lookup=_list_products,
             parent="category"),
    ),
    metric=_get_stock,
))


# --- new_signups: channel + month(자유 입력, 독립 필터) → 신규 가입자 수 ---
def _list_channels(repo: Repository, slots: dict) -> list[dict]:
    return repo.all("channels")


def _get_signups(repo: Repository, slots: dict) -> dict:
    channels = repo.where("channels", id=slots["channel"])
    name = channels[0]["name"] if channels else str(slots["channel"])
    rows = repo.where("signups", channel_id=slots["channel"], month=slots["month"])
    count = rows[0]["count"] if rows else 0
    return {
        "label": "신규 가입자 수",
        "columns": ["channel", "month", "signups"],
        "rows": [(name, slots["month"], count)],
    }


scenario_registry.register(Scenario(
    id="new_signups",
    label="신규 가입자 분석",
    slots=(
        Slot(name="channel", description="유입 채널", lookup=_list_channels),
        Slot(name="month", description="조회 월(YYYY-MM)", lookup=None,
             validator=_validate_month),
    ),
    metric=_get_signups,
))
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_slot_scenarios.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/slot_agent/scenarios.py tests/test_slot_scenarios.py
git commit -m "feat(slot-agent): declare regional_sales, product_stock, new_signups scenarios"
```

---

## Task 6: 추출용 시스템 프롬프트 빌더

LLM에 (시나리오 매칭 + 메시지에 드러난 슬롯 추출)만 시키는 프롬프트.

**Files:**
- Create: `src/slot_agent/prompt.py`
- Test: `tests/test_slot_prompt.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_slot_prompt.py`:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_slot_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.slot_agent.prompt'`

- [ ] **Step 3: 최소 구현 작성**

`src/slot_agent/prompt.py`:

```python
"""슬롯 에이전트 시스템 프롬프트 빌더."""

from __future__ import annotations

from src.slot_agent.registry import ScenarioRegistry

_SYSTEM_PROMPT_TEMPLATE = """\
당신은 사전 정의된 조회 시나리오의 슬롯을 채우는 에이전트입니다.
사용자 메시지에서 어떤 시나리오에 해당하는지 고르고, 메시지에 이미 드러난
슬롯 값만 추출해 JSON으로 반환하세요.

## 규칙
- 슬롯 값을 임의로 추측하지 마세요. 메시지에 없으면 생략하세요.
- 디폴트("전체", "all" 등)를 임의로 적용하지 마세요.
- 어떤 시나리오와도 맞지 않으면 scenario_id를 null로 두세요.
- 슬롯의 후보값은 시스템이 DB에서 직접 조회합니다. 값을 지어내지 마세요.

## 출력 형식
정확히 아래 JSON 한 객체만 반환하세요. 다른 텍스트나 ```json 펜스도
넣지 마세요.

{{
  "scenario_id": "<id 또는 null>",
  "slots": {{"<슬롯명>": <값>, ...}}
}}

## 처리 가능한 시나리오
{catalog}
"""


def build_system_prompt(registry: ScenarioRegistry) -> str:
    """레지스트리의 시나리오 카탈로그를 반영해 시스템 프롬프트를 합성한다."""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        catalog=registry.build_catalog_for_llm()
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_slot_prompt.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/slot_agent/prompt.py tests/test_slot_prompt.py
git commit -m "feat(slot-agent): add extraction system prompt builder"
```

---

## Task 7: 에이전트 노드 wrapper

LLM 호출 → JSON 파싱 → resolve → (후보 안내 | 지표 결과) 포매팅. 기존 `templated_sql_agent.agent`와 동일한 단일 패스 구조.

**Files:**
- Create: `src/slot_agent/agent.py`
- Test: `tests/test_slot_agent.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_slot_agent.py`:

```python
"""슬롯 에이전트 wrapper 분기 로직 테스트. LLM은 mock으로 주입."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.slot_agent.agent import slot_wrapper
from src.slot_agent.repository import Repository, set_repository


@pytest.fixture(autouse=True)
def _virtual_db():
    """각 테스트마다 결정적 in-memory 가상 DB를 주입하고 끝나면 초기화."""
    set_repository(Repository(tables={
        "countries": [{"id": 1, "name": "한국"}, {"id": 2, "name": "일본"}],
        "branches": [
            {"id": 11, "country_id": 1, "name": "강남점"},
            {"id": 12, "country_id": 1, "name": "부산점"},
        ],
        "sales": [
            {"branch_id": 11, "month": "2026-01", "amount": 1200},
            {"branch_id": 11, "month": "2026-02", "amount": 1500},
        ],
        "categories": [{"id": 1, "name": "전자"}],
        "products": [{"id": 101, "category_id": 1, "name": "노트북"}],
        "inventory": [{"product_id": 101, "stock": 34}],
        "channels": [{"id": 1, "name": "검색광고"}],
        "signups": [{"channel_id": 1, "month": "2026-01", "count": 120}],
    }))
    yield
    set_repository(None)


def _state(text: str) -> dict:
    return {"messages": [HumanMessage(content=text)], "next_agent": "",
            "chat_history": []}


def _llm_returning(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.invoke.return_value = MagicMock(
        content=json.dumps(payload, ensure_ascii=False)
    )
    return mock


class TestAskFlow:
    @patch("src.slot_agent.agent.get_chat_model")
    def test_empty_slots_asks_first_with_candidates(self, mock_model) -> None:
        mock_model.return_value = _llm_returning(
            {"scenario_id": "regional_sales", "slots": {}}
        )
        result = slot_wrapper(_state("지역 매출 알려줘"))
        content = result["messages"][-1].content
        assert "나라" in content
        assert "한국" in content and "일본" in content  # DB 후보 grounding

    @patch("src.slot_agent.agent.get_chat_model")
    def test_parent_filled_asks_child_filtered(self, mock_model) -> None:
        mock_model.return_value = _llm_returning(
            {"scenario_id": "regional_sales", "slots": {"country": "한국"}}
        )
        content = slot_wrapper(_state("한국"))["messages"][-1].content
        assert "강남점" in content and "부산점" in content
        assert "도쿄점" not in content  # 일본 지점은 후보에서 제외


class TestFetchFlow:
    @patch("src.slot_agent.agent.get_chat_model")
    def test_all_slots_filled_runs_metric(self, mock_model) -> None:
        mock_model.return_value = _llm_returning({
            "scenario_id": "regional_sales",
            "slots": {"country": "한국", "branch": "강남점"},
        })
        content = slot_wrapper(_state("한국 강남점 매출"))["messages"][-1].content
        assert "월별 매출액" in content
        assert "2026-01" in content and "1200" in content


class TestNoMatch:
    @patch("src.slot_agent.agent.get_chat_model")
    def test_null_scenario_returns_no_match(self, mock_model) -> None:
        mock_model.return_value = _llm_returning(
            {"scenario_id": None, "slots": {}}
        )
        content = slot_wrapper(_state("안녕"))["messages"][-1].content
        assert "지역별 매출" in content  # 카탈로그 안내

    @patch("src.slot_agent.agent.get_chat_model")
    def test_unparseable_json_falls_back_to_no_match(self, mock_model) -> None:
        mock = MagicMock()
        mock.invoke.return_value = MagicMock(content="JSON 아님")
        mock_model.return_value = mock
        content = slot_wrapper(_state("ㅁㄴㅇ"))["messages"][-1].content
        assert "지역별 매출" in content

    @patch("src.slot_agent.agent.get_chat_model")
    def test_unknown_scenario_id_falls_back(self, mock_model) -> None:
        mock_model.return_value = _llm_returning(
            {"scenario_id": "does_not_exist", "slots": {}}
        )
        content = slot_wrapper(_state("..."))["messages"][-1].content
        assert "지역별 매출" in content


class TestFreeSlot:
    @patch("src.slot_agent.agent.get_chat_model")
    def test_missing_free_month_asks_for_value(self, mock_model) -> None:
        mock_model.return_value = _llm_returning(
            {"scenario_id": "new_signups", "slots": {"channel": "검색광고"}}
        )
        content = slot_wrapper(_state("검색광고 가입자"))["messages"][-1].content
        assert "월" in content
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_slot_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.slot_agent.agent'`

- [ ] **Step 3: 최소 구현 작성**

`src/slot_agent/agent.py`:

```python
"""slot 에이전트: declarative 시나리오 기반 슬롯 채우기 조회.

단일 LLM 호출로 (시나리오 매칭 + 메시지에 드러난 슬롯)만 추출하고, 후보값
grounding·슬롯 해소·지표 조회는 결정적 Python(resolve/metric)이 수행한다.
멀티턴 HITL은 query_rewriter가 처리하므로 이 에이전트는 chat_history를
보지 않는다.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage

from src.registry import registry
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.sql_agent.backend.formatter import to_markdown_table
from src.state import State
from src.slot_agent import scenarios  # noqa: F401 - 등록 트리거
from src.slot_agent.prompt import build_system_prompt
from src.slot_agent.registry import Scenario, scenario_registry
from src.slot_agent.repository import get_repository
from src.slot_agent.resolve import AskSlot, Ready, resolve

logger = get_logger("agent.slot")


def _emit(content: str) -> dict:
    """그래프 반환 dict 표준 형식 (다른 서브에이전트들과 동일한 태깅)."""
    return {"messages": [AIMessage(content=f"[조회 결과]\n{content}")]}


def _parse_action_json(text: str) -> dict[str, Any] | None:
    """LLM 응답에서 JSON 객체를 추출한다. 실패 시 None."""
    stripped = text.strip()
    if "```" in stripped:
        try:
            start = stripped.index("```")
            after = stripped[start + 3:]
            if after.startswith("json"):
                after = after[4:]
            end = after.index("```")
            stripped = after[:end].strip()
        except ValueError:
            pass
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None


def _no_match_message() -> str:
    """no_match 상황에서 사용자에게 보여줄 안내 메시지."""
    if not scenario_registry.scenarios:
        return "처리 가능한 조회가 등록되어 있지 않습니다."
    lines = ["이 에이전트가 처리할 수 있는 조회 종류는 다음과 같습니다:"]
    for s in scenario_registry.scenarios:
        lines.append(f"- {s.label}")
    lines.append("위 조회 중 하나로 다시 질문해 주세요.")
    return "\n".join(lines)


def _format_ask(ask: AskSlot) -> str:
    """다음 빈 슬롯을 묻는 메시지. 후보값이 있으면 표로 제시(grounding)."""
    slot = ask.slot
    if not ask.candidates:
        return f"{slot.description} 값을 알려주세요."
    columns = [slot.value_key, slot.label_key]
    rows = [
        (c.get(slot.value_key), c.get(slot.label_key)) for c in ask.candidates
    ]
    table = to_markdown_table(columns, rows)
    return (
        f"어떤 {slot.description}를 조회할까요? 아래에서 골라 알려주세요.\n\n"
        f"{table}"
    )


def _format_result(scenario: Scenario, result: dict[str, Any]) -> str:
    """확정된 슬롯으로 조회한 최종 지표를 표로 포매팅."""
    table = to_markdown_table(result["columns"], result["rows"])
    return f"[{scenario.label}] {result['label']}\n{table}"


@registry.agent(
    "slot",
    description=scenario_registry.build_router_description(),
)
@log_node("slot")
def slot_wrapper(state: State) -> dict:
    """declarative 시나리오 기반 슬롯 채우기 조회를 처리한다."""
    llm = get_chat_model()
    system_prompt = build_system_prompt(scenario_registry)
    messages = [SystemMessage(content=system_prompt)] + state["messages"]

    logger.info("LLM 호출 시작 (scenarios=%d)", len(scenario_registry.scenarios))
    try:
        response = llm.invoke(messages)
    except Exception:
        logger.error("LLM 호출 실패", exc_info=True)
        raise

    parsed = _parse_action_json(response.content)
    if parsed is None:
        logger.warning("JSON 파싱 실패 → no_match. 원본: %s", response.content)
        return _emit(_no_match_message())

    scenario_id = parsed.get("scenario_id")
    if not scenario_id:
        return _emit(_no_match_message())

    scenario = scenario_registry.get(scenario_id)
    if scenario is None:
        logger.warning("미등록 scenario_id: %s → no_match", scenario_id)
        return _emit(_no_match_message())

    extracted = parsed.get("slots") or {}
    repo = get_repository()
    outcome = resolve(repo, scenario, extracted)

    if isinstance(outcome, AskSlot):
        return _emit(_format_ask(outcome))

    assert isinstance(outcome, Ready)
    result = scenario.metric(repo, outcome.slots)
    return _emit(_format_result(scenario, result))
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_slot_agent.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/slot_agent/agent.py tests/test_slot_agent.py
git commit -m "feat(slot-agent): add single-pass slot-filling node wrapper"
```

---

## Task 8: 그래프 통합 + 데모 시나리오

`slot` 에이전트를 전역 레지스트리에 등록되도록 import하고, `main.py`에 멀티턴 데모를 추가한다.

**Files:**
- Modify: `src/slot_agent/__init__.py`
- Modify: `src/__init__.py:1-6`
- Modify: `src/main.py:158-196` (main 함수에 데모 G 추가)

- [ ] **Step 1: slot_agent 패키지가 wrapper를 노출하도록 수정**

`src/slot_agent/__init__.py` (Task 1에서 만든 빈 파일을 교체):

```python
# agent 모듈 import로 @registry.agent("slot") 등록을 트리거한다.
from src.slot_agent.agent import slot_wrapper  # noqa: F401
```

- [ ] **Step 2: 전역 등록 트리거 import 추가**

`src/__init__.py` 의 import 블록에 한 줄 추가 (알파벳 순서 유지, `sql_agent` 다음):

```python
# 각 에이전트 모듈을 import하여 @registry.agent 데코레이터를 통한 자동 등록을 트리거한다.
from src.math_agent import math_wrapper  # noqa: F401
from src.registry import registry  # noqa: F401
from src.slot_agent import slot_wrapper  # noqa: F401
from src.sql_agent import sql_wrapper  # noqa: F401
from src.templated_sql_agent import templated_sql_wrapper  # noqa: F401
from src.translate_agent import translate_wrapper  # noqa: F401
```

- [ ] **Step 3: 통합 검증 테스트 작성 (실패 확인)**

`tests/test_slot_agent.py` 끝에 추가:

```python
class TestRegistration:
    def test_slot_agent_registered_in_global_registry(self) -> None:
        import src  # noqa: F401 - src/__init__.py가 모든 에이전트를 등록
        from src.registry import registry

        entry = registry.get("slot")
        assert entry is not None
        assert entry.node_name == "slot_agent"
        assert "슬롯" in entry.description or "조회" in entry.description
```

Run: `uv run pytest tests/test_slot_agent.py::TestRegistration -v`
Expected: Step 1-2를 마쳤으면 PASS. (등록 import가 빠졌으면 FAIL — `entry is None`.)

- [ ] **Step 4: 전체 그래프 빌드 확인**

Run: `uv run python -c "from src.main import build_graph; g = build_graph(); print('slot_agent' in g.get_graph().nodes)"`
Expected: `True` 출력 (그래프에 slot_agent 노드가 포함됨).

- [ ] **Step 5: main.py에 멀티턴 데모 시나리오 G 추가**

`src/main.py` 의 `main()` 함수 끝(`run_three_turn_scenario(... "F" ...)` 호출 다음, `if __name__` 앞)에 추가:

```python
    run_three_turn_scenario(
        app, "G",
        "slot 에이전트 멀티턴 — 나라 → 지점 → 월별 매출 (슬롯 채우기)",
        "지역별 매출 알려줘",
        "한국",
        "강남점",
    )
```

- [ ] **Step 6: 전체 테스트 스위트 통과 확인**

Run: `uv run pytest -q`
Expected: 기존 테스트 전부 + 신규 슬롯 테스트 전부 PASS. 실패 0.

- [ ] **Step 7: 커밋**

```bash
git add src/slot_agent/__init__.py src/__init__.py src/main.py tests/test_slot_agent.py
git commit -m "feat(slot-agent): register slot agent in graph and add demo scenario G"
```

---

## 자가 검토 (작성자 체크리스트)

**1. 스펙 커버리지**

| 스펙 항목 | 구현 위치 |
|---|---|
| 1. 가상 DB 레이어 (repository) | Task 1 `repository.py` |
| 2. 데이터 구조/3 시나리오 (star schema) | Task 2 데이터 + Task 5 시나리오 |
| 3. declarative registry (slot lookup/parent, metric) | Task 3 `registry.py` |
| 4-(1) intent 분류 + 슬롯 pre-fill | Task 7 LLM 추출 + Task 6 프롬프트 |
| 4-(2) resolve: 상위 슬롯 필터 후보 조회 | Task 4 `resolve.py` |
| 4-(3) 유효값 자동 매칭 / 없으면 후보 제시 | Task 4 grounding + Task 7 `_format_ask` |
| 4-(4) 모든 슬롯 확정 시 지표 조회·포맷 | Task 7 `_format_result` + Task 5 metric |
| 5. grounding / config 분리 베스트 프랙티스 | repository + registry 분리, resolve grounding |
| 5'. (interrupt+checkpointer) | **스펙 대비 결정**: query_rewriter + 멀티턴 재호출로 대체 (설계 결정 절 참조) |
| 6. 구현 순서 (DB→시나리오1→일반화→확장) | Task 1→2→4(단일)→3·5(일반화) 순서로 반영 |

**2. 플레이스홀더 스캔**: 모든 코드 스텝에 실제 코드가 들어 있고 "TBD/적절히 처리" 류 없음 — 확인.

**3. 타입 일관성**:
- `Repository.all/where`, `get_repository/set_repository` — Task 1·5·7에서 동일 시그니처.
- `Slot(name, description, lookup, parent, value_key, label_key, validator)` — Task 3·4·5에서 동일.
- `resolve(repo, scenario, extracted) -> AskSlot | Ready`, `AskSlot.slot/candidates`, `Ready.slots` — Task 4·7 동일.
- metric 반환 `{"label", "columns", "rows"}` — Task 5·7 동일.
- `scenario_registry`(슬롯) vs `registry`(에이전트) — 이름 충돌 없이 분리 사용.
