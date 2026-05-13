# tool_call Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사전 정의된 함수형 도구 4개를 ReAct로 호출하는 신규 에이전트 `tool_call`을 추가한다. 메타DB에서 브랜치별 DB 경로를 얻어 브랜치 DB의 머신 정보를 조회하는 멀티 DB 시나리오를 v1 도메인으로 구현한다.

**Architecture:** sql_agent와 동일한 ReAct 서브그래프 패턴(agent ↔ tools 루프, WorkerState 격리). 단, SQL/도메인 추상화 재사용 없이 `src/tool_call_agent/`에서 모듈 레벨 `TOOLS` 리스트만 노출. 도구 함수는 자체 sqlite 커넥션을 read-only 모드로 직접 관리하며, SELECT 검증과 LIMIT 주입만 `src/sql_agent/backend/safety.py`에서 재사용한다.

**Tech Stack:** Python 3.11+, LangGraph, LangChain `@tool`, sqlite3, pytest

**Spec:** `docs/superpowers/specs/2026-05-13-tool-call-agent-design.md`

---

## File Structure

| 파일 | 책임 |
|---|---|
| `res/sample_db/factory/seed.py` | `meta.db`, `branch_{A,B,C}.db` 생성·시드 (idempotent) |
| `src/tool_call_agent/__init__.py` | wrapper import로 `@registry.agent` 등록 트리거 |
| `src/tool_call_agent/prompt.py` | 범용 ReAct 시스템 프롬프트 (도메인 어휘 없음) |
| `src/tool_call_agent/tools.py` | 4개 `@tool` 함수 + 내부 헬퍼 (path 화이트리스트, sqlite 헬퍼, markdown) |
| `src/tool_call_agent/agent.py` | ReAct 서브그래프 빌드 + `@registry.agent("tool_call")` wrapper |
| `src/__init__.py` | 신규 agent import 추가 (등록 트리거) |
| `src/main.py` | 데모 시나리오 G 추가 |
| `res/suggestions.yaml` | `tool_call` 카테고리 추천 질문 |
| `README.md` | Architecture/Structure/Subagents 표/데모 목록 갱신 |
| `tests/test_factory_seed.py` | 시드 스크립트 단위 테스트 |
| `tests/test_tool_call_tools.py` | 도구 함수 + 헬퍼 단위 테스트 |
| `tests/test_tool_call_agent.py` | 서브그래프 + wrapper 단위 테스트 |

---

## Task 1: 시드 스크립트 (`res/sample_db/factory/seed.py`)

**Files:**
- Create: `res/sample_db/factory/seed.py`
- Test: `tests/test_factory_seed.py`

- [ ] **Step 1: 테스트 파일 작성**

Create `tests/test_factory_seed.py`:

```python
"""factory 샘플 DB 시드 스크립트 단위 테스트."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from res.sample_db.factory import seed


@pytest.fixture
def tmp_factory_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """seed의 출력 디렉토리를 tmp_path로 리다이렉트."""
    monkeypatch.setattr(seed, "FACTORY_DIR", tmp_path)
    monkeypatch.setattr(seed, "META_DB_PATH", tmp_path / "meta.db")
    return tmp_path


def test_run_creates_meta_and_three_branch_dbs(tmp_factory_dir: Path) -> None:
    seed.run()

    assert (tmp_factory_dir / "meta.db").exists()
    assert (tmp_factory_dir / "branch_A.db").exists()
    assert (tmp_factory_dir / "branch_B.db").exists()
    assert (tmp_factory_dir / "branch_C.db").exists()


def test_meta_db_has_three_branches(tmp_factory_dir: Path) -> None:
    seed.run()

    with sqlite3.connect(tmp_factory_dir / "meta.db") as conn:
        rows = conn.execute(
            "SELECT branch_code, branch_name, region, db_path FROM branches ORDER BY branch_code"
        ).fetchall()

    assert len(rows) == 3
    codes = [r[0] for r in rows]
    assert codes == ["F-A", "F-B", "F-C"]
    db_paths = [r[3] for r in rows]
    assert db_paths == ["branch_A.db", "branch_B.db", "branch_C.db"]


def test_each_branch_has_machines_and_status(tmp_factory_dir: Path) -> None:
    seed.run()

    for branch in ("branch_A.db", "branch_B.db", "branch_C.db"):
        with sqlite3.connect(tmp_factory_dir / branch) as conn:
            machines = conn.execute("SELECT machine_id FROM machines").fetchall()
            statuses = conn.execute("SELECT machine_id FROM machine_status").fetchall()
        assert len(machines) >= 3, f"{branch}: machines >= 3"
        assert len(statuses) == len(machines), f"{branch}: status per machine"


def test_run_is_idempotent(tmp_factory_dir: Path) -> None:
    seed.run()
    seed.run()  # 두 번째 실행도 예외 없이 같은 행 수 유지

    with sqlite3.connect(tmp_factory_dir / "meta.db") as conn:
        count = conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
    assert count == 3
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_factory_seed.py -v`
Expected: ImportError or ModuleNotFoundError — `res.sample_db.factory.seed`가 없음.

- [ ] **Step 3: 시드 구현**

Create `res/sample_db/factory/seed.py`:

```python
"""제조업 멀티-DB 샘플 시드 스크립트.

본사 메타DB(meta.db)와 3개 브랜치 DB(branch_A/B/C.db)를 생성한다.
모듈 import 시 부수효과는 없으며, run() 호출 시점에만 파일을 만든다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

FACTORY_DIR = Path(__file__).resolve().parent
META_DB_PATH = FACTORY_DIR / "meta.db"

_BRANCHES: list[tuple[str, str, str, str]] = [
    ("F-A", "아산 1공장", "충남", "branch_A.db"),
    ("F-B", "구미 2공장", "경북", "branch_B.db"),
    ("F-C", "광주 3공장", "광주", "branch_C.db"),
]

_BRANCH_MACHINES: dict[str, list[tuple[str, str, str, str]]] = {
    "branch_A.db": [
        ("M-001", "압출기 1호", "라인-1", "EX-2000"),
        ("M-002", "절단기 1호", "라인-1", "CT-500"),
        ("M-003", "포장기 1호", "라인-2", "PK-100"),
        ("M-004", "검사기 1호", "라인-2", "IN-300"),
    ],
    "branch_B.db": [
        ("M-101", "프레스 A", "라인-α", "PR-1200"),
        ("M-102", "용접로봇 A", "라인-α", "WR-9"),
        ("M-103", "도장부스 A", "라인-β", "PT-50"),
    ],
    "branch_C.db": [
        ("M-201", "조립로봇 1", "어셈블리", "AR-7"),
        ("M-202", "조립로봇 2", "어셈블리", "AR-7"),
        ("M-203", "테스트벤치 1", "QA", "TB-300"),
        ("M-204", "포장기 X", "출하", "PK-200"),
        ("M-205", "라벨러", "출하", "LB-50"),
    ],
}

_BRANCH_STATUS: dict[str, list[tuple[str, str, float, str]]] = {
    "branch_A.db": [
        ("M-001", "running", 0.92, "2026-05-13T08:00:00"),
        ("M-002", "running", 0.88, "2026-05-13T08:00:00"),
        ("M-003", "idle", 0.10, "2026-05-13T08:00:00"),
        ("M-004", "maintenance", 0.00, "2026-05-13T07:30:00"),
    ],
    "branch_B.db": [
        ("M-101", "running", 0.95, "2026-05-13T08:00:00"),
        ("M-102", "fault", 0.00, "2026-05-13T06:15:00"),
        ("M-103", "running", 0.80, "2026-05-13T08:00:00"),
    ],
    "branch_C.db": [
        ("M-201", "running", 0.97, "2026-05-13T08:00:00"),
        ("M-202", "running", 0.93, "2026-05-13T08:00:00"),
        ("M-203", "idle", 0.20, "2026-05-13T08:00:00"),
        ("M-204", "running", 0.85, "2026-05-13T08:00:00"),
        ("M-205", "maintenance", 0.00, "2026-05-13T07:00:00"),
    ],
}


def _build_meta_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS branches ("
            "branch_code TEXT PRIMARY KEY,"
            "branch_name TEXT NOT NULL,"
            "region      TEXT NOT NULL,"
            "db_path     TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT OR REPLACE INTO branches "
            "(branch_code, branch_name, region, db_path) VALUES (?, ?, ?, ?)",
            _BRANCHES,
        )


def _build_branch_db(path: Path, machines: list[tuple[str, str, str, str]],
                     statuses: list[tuple[str, str, float, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS machines ("
            "machine_id TEXT PRIMARY KEY,"
            "name       TEXT NOT NULL,"
            "line       TEXT NOT NULL,"
            "model      TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS machine_status ("
            "machine_id   TEXT PRIMARY KEY REFERENCES machines(machine_id),"
            "state        TEXT NOT NULL,"
            "uptime_ratio REAL NOT NULL,"
            "last_updated TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT OR REPLACE INTO machines "
            "(machine_id, name, line, model) VALUES (?, ?, ?, ?)",
            machines,
        )
        conn.executemany(
            "INSERT OR REPLACE INTO machine_status "
            "(machine_id, state, uptime_ratio, last_updated) VALUES (?, ?, ?, ?)",
            statuses,
        )


def run() -> None:
    """meta.db와 brand DB 3개를 생성/갱신한다. Idempotent."""
    _build_meta_db(META_DB_PATH)
    for filename in ("branch_A.db", "branch_B.db", "branch_C.db"):
        _build_branch_db(
            FACTORY_DIR / filename,
            _BRANCH_MACHINES[filename],
            _BRANCH_STATUS[filename],
        )


if __name__ == "__main__":
    run()
    print(f"✓ factory 시드 완료: {FACTORY_DIR}")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_factory_seed.py -v`
Expected: 4 passed.

- [ ] **Step 5: 커밋**

```bash
git add res/sample_db/factory/seed.py tests/test_factory_seed.py
git commit -m "feat(tool-call-agent): add factory multi-db seed script"
```

---

## Task 2: 경로 화이트리스트 헬퍼 (`tools.py` 일부)

**Files:**
- Create: `src/tool_call_agent/__init__.py` (빈 파일)
- Create: `src/tool_call_agent/tools.py` (헬퍼만 포함)
- Test: `tests/test_tool_call_tools.py`

- [ ] **Step 1: 테스트 파일 작성 (헬퍼 부분만)**

Create `tests/test_tool_call_tools.py`:

```python
"""tool_call_agent 도구 함수 + 내부 헬퍼 단위 테스트."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from res.sample_db.factory import seed
from src.tool_call_agent import tools


@pytest.fixture
def factory_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """factory 디렉토리와 메타 경로를 tmp_path로 리다이렉트하고 시드한다."""
    monkeypatch.setattr(seed, "FACTORY_DIR", tmp_path)
    monkeypatch.setattr(seed, "META_DB_PATH", tmp_path / "meta.db")
    monkeypatch.setattr(tools, "_FACTORY_DB_ROOT", tmp_path)
    monkeypatch.setattr(tools, "_META_DB", tmp_path / "meta.db")
    seed.run()
    return tmp_path


class TestResolveBranchDb:
    def test_relative_path_resolved_to_factory_root(self, factory_tmp: Path) -> None:
        result = tools._resolve_branch_db("branch_A.db")
        assert result == (factory_tmp / "branch_A.db").resolve()

    def test_absolute_path_in_root_allowed(self, factory_tmp: Path) -> None:
        absolute = str((factory_tmp / "branch_B.db").resolve())
        result = tools._resolve_branch_db(absolute)
        assert result == (factory_tmp / "branch_B.db").resolve()

    def test_directory_traversal_rejected(self, factory_tmp: Path) -> None:
        with pytest.raises(ValueError, match="허용되지 않은"):
            tools._resolve_branch_db("../../etc/passwd")

    def test_meta_db_rejected(self, factory_tmp: Path) -> None:
        with pytest.raises(ValueError, match="허용되지 않은"):
            tools._resolve_branch_db("meta.db")

    def test_non_db_extension_rejected(self, factory_tmp: Path) -> None:
        (factory_tmp / "branch_X.txt").write_text("")
        with pytest.raises(ValueError, match="허용되지 않은"):
            tools._resolve_branch_db("branch_X.txt")

    def test_missing_file_rejected(self, factory_tmp: Path) -> None:
        with pytest.raises(ValueError, match="존재하지 않는"):
            tools._resolve_branch_db("branch_Z.db")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_tool_call_tools.py -v`
Expected: ImportError — `src.tool_call_agent.tools`가 없음.

- [ ] **Step 3: 헬퍼 구현 (도구 함수는 다음 태스크)**

Create `src/tool_call_agent/__init__.py` (빈 파일).

Create `src/tool_call_agent/tools.py`:

```python
"""tool_call 에이전트의 v1 도구 함수와 내부 헬퍼.

도구 함수는 사용자의 정보 조회 요청을 만족시키기 위해 LLM이 호출한다.
각 함수는 자체 sqlite 커넥션을 read-only 모드로 직접 관리하며,
모듈 레벨 싱글톤을 두지 않는다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from src.sql_agent.backend.safety import (
    UnsafeSqlError,
    inject_limit_if_missing,
    validate_select_only,
)

_FACTORY_DB_ROOT = (
    Path(__file__).resolve().parents[2] / "res" / "sample_db" / "factory"
)
_META_DB = _FACTORY_DB_ROOT / "meta.db"
_ROW_LIMIT = 100
_BUSY_TIMEOUT_MS = 1000


def _resolve_branch_db(db_path: str) -> Path:
    """LLM이 넘긴 db_path를 안전한 절대 경로로 환원한다.

    화이트리스트: 결과 경로의 parent가 정확히 _FACTORY_DB_ROOT이고,
    확장자가 .db이며, meta.db는 제외, 실제 파일이 존재해야 한다.

    Raises:
        ValueError: 화이트리스트 위반 또는 파일 부재 시.
    """
    candidate = Path(db_path)
    if not candidate.is_absolute():
        candidate = _FACTORY_DB_ROOT / candidate
    resolved = candidate.resolve()

    if resolved.parent != _FACTORY_DB_ROOT.resolve():
        raise ValueError(f"허용되지 않은 DB 경로: {db_path}")
    if resolved.suffix != ".db" or resolved.name == "meta.db":
        raise ValueError(f"허용되지 않은 DB 경로: {db_path}")
    if not resolved.exists():
        raise ValueError(f"존재하지 않는 DB 파일: {resolved.name}")
    return resolved
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_tool_call_tools.py::TestResolveBranchDb -v`
Expected: 6 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/tool_call_agent/__init__.py src/tool_call_agent/tools.py tests/test_tool_call_tools.py
git commit -m "feat(tool-call-agent): add path whitelist helper"
```

---

## Task 3: SQL 실행 + markdown 헬퍼

**Files:**
- Modify: `src/tool_call_agent/tools.py` (헬퍼 추가)
- Test: `tests/test_tool_call_tools.py` (테스트 추가)

- [ ] **Step 1: 헬퍼 테스트 추가**

Append to `tests/test_tool_call_tools.py`:

```python
class TestReadQuery:
    def test_returns_columns_and_rows(self, factory_tmp: Path) -> None:
        cols, rows = tools._read_query(
            factory_tmp / "meta.db",
            "SELECT branch_code, branch_name FROM branches ORDER BY branch_code",
        )
        assert cols == ["branch_code", "branch_name"]
        assert rows[0][0] == "F-A"

    def test_named_params_binding(self, factory_tmp: Path) -> None:
        cols, rows = tools._read_query(
            factory_tmp / "meta.db",
            "SELECT db_path FROM branches WHERE branch_code = :code",
            {"code": "F-B"},
        )
        assert rows == [("branch_B.db",)]

    def test_select_only_violation_raises(self, factory_tmp: Path) -> None:
        from src.sql_agent.backend.safety import UnsafeSqlError
        with pytest.raises(UnsafeSqlError):
            tools._read_query(factory_tmp / "meta.db", "DELETE FROM branches")

    def test_readonly_connection(self, factory_tmp: Path) -> None:
        # read-only 검증: 쓰기 시도 시 sqlite3.OperationalError
        # _read_query는 SELECT만 허용하므로, 여기서는 mtime 불변을 확인
        import os
        before = os.path.getmtime(factory_tmp / "branch_A.db")
        tools._read_query(
            factory_tmp / "branch_A.db",
            "SELECT machine_id FROM machines",
        )
        after = os.path.getmtime(factory_tmp / "branch_A.db")
        assert before == after

    def test_auto_limit_injected(self, factory_tmp: Path) -> None:
        # _ROW_LIMIT=100 cap을 우회할 수 없음. branch_C.db는 머신 5개.
        cols, rows = tools._read_query(
            factory_tmp / "branch_C.db",
            "SELECT machine_id FROM machines",
        )
        assert 0 < len(rows) <= 100


class TestToMarkdown:
    def test_basic_table(self) -> None:
        out = tools._to_markdown(["a", "b"], [(1, "x"), (2, "y")])
        assert "| a | b |" in out
        assert "| 1 | x |" in out
        assert "| 2 | y |" in out

    def test_empty_rows(self) -> None:
        assert tools._to_markdown(["a"], []) == "(결과 없음)"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_tool_call_tools.py::TestReadQuery tests/test_tool_call_tools.py::TestToMarkdown -v`
Expected: AttributeError — `_read_query`, `_to_markdown`이 없음.

- [ ] **Step 3: 헬퍼 구현**

Append to `src/tool_call_agent/tools.py`:

```python
def _read_query(
    db_file: Path,
    sql: str,
    params: dict[str, Any] | None = None,
) -> tuple[list[str], list[tuple]]:
    """단발성 read-only sqlite 조회.

    안전망: validate_select_only + mode=ro URI + busy_timeout + LIMIT 100 주입.

    Returns:
        (columns, rows) 튜플.

    Raises:
        UnsafeSqlError: SELECT-only 검증 실패.
        sqlite3.Error: 커넥션/실행 실패.
    """
    validate_select_only(sql)
    safe_sql = inject_limit_if_missing(sql, _ROW_LIMIT)
    uri = f"file:{db_file}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=_BUSY_TIMEOUT_MS / 1000) as conn:
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        cur = conn.execute(safe_sql, params or {})
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return cols, rows


def _to_markdown(cols: list[str], rows: list[tuple]) -> str:
    """결과 표를 markdown 표 문자열로 직렬화한다."""
    if not rows:
        return "(결과 없음)"
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join(
        "| " + " | ".join(str(v) for v in r) + " |" for r in rows
    )
    return "\n".join([head, sep, body])
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_tool_call_tools.py -v`
Expected: 모든 헬퍼 테스트 통과 (총 13개 정도).

- [ ] **Step 5: 커밋**

```bash
git add src/tool_call_agent/tools.py tests/test_tool_call_tools.py
git commit -m "feat(tool-call-agent): add read-only sqlite + markdown helpers"
```

---

## Task 4: `list_branches` 도구

**Files:**
- Modify: `src/tool_call_agent/tools.py`
- Test: `tests/test_tool_call_tools.py`

- [ ] **Step 1: 테스트 추가**

Append to `tests/test_tool_call_tools.py`:

```python
class TestListBranches:
    def test_returns_markdown_with_all_branches(self, factory_tmp: Path) -> None:
        out = tools.list_branches.invoke({})
        assert "F-A" in out and "아산 1공장" in out
        assert "F-B" in out and "구미 2공장" in out
        assert "F-C" in out and "광주 3공장" in out
        assert "| branch_code |" in out

    def test_no_args_required(self, factory_tmp: Path) -> None:
        # 인자 없이 invoke 가능
        out = tools.list_branches.invoke({})
        assert isinstance(out, str)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_tool_call_tools.py::TestListBranches -v`
Expected: AttributeError — `list_branches`가 없음.

- [ ] **Step 3: 도구 구현**

Append to `src/tool_call_agent/tools.py`:

```python
from langchain_core.tools import tool


@tool
def list_branches() -> str:
    """등록된 브랜치(공장) 목록을 markdown 표로 반환한다.

    반환 컬럼: branch_code, branch_name, region.
    branch_code는 다른 도구의 인자로 사용된다.
    """
    try:
        cols, rows = _read_query(
            _META_DB,
            "SELECT branch_code, branch_name, region "
            "FROM branches ORDER BY branch_code",
        )
    except (sqlite3.Error, UnsafeSqlError) as exc:
        return f"ERROR: 브랜치 목록 조회 실패: {exc}"
    return _to_markdown(cols, rows)
```

(import는 파일 상단에 두는 것이 관례지만, 점진 추가 단계이므로 명확성을 위해 도구 정의 직전에 두었다. 모든 도구를 추가한 뒤 Task 7에서 import를 파일 상단으로 정리한다.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_tool_call_tools.py::TestListBranches -v`
Expected: 2 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/tool_call_agent/tools.py tests/test_tool_call_tools.py
git commit -m "feat(tool-call-agent): add list_branches tool"
```

---

## Task 5: `get_branch_db_path` 도구

**Files:**
- Modify: `src/tool_call_agent/tools.py`
- Test: `tests/test_tool_call_tools.py`

- [ ] **Step 1: 테스트 추가**

Append to `tests/test_tool_call_tools.py`:

```python
class TestGetBranchDbPath:
    def test_returns_absolute_path(self, factory_tmp: Path) -> None:
        out = tools.get_branch_db_path.invoke({"branch_code": "F-A"})
        assert out == str((factory_tmp / "branch_A.db").resolve())

    def test_unknown_code_returns_error(self, factory_tmp: Path) -> None:
        out = tools.get_branch_db_path.invoke({"branch_code": "F-Z"})
        assert out.startswith("ERROR: 등록되지 않은 branch_code")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_tool_call_tools.py::TestGetBranchDbPath -v`
Expected: AttributeError — `get_branch_db_path`가 없음.

- [ ] **Step 3: 도구 구현**

Append to `src/tool_call_agent/tools.py`:

```python
@tool
def get_branch_db_path(branch_code: str) -> str:
    """특정 브랜치의 머신 DB 경로를 반환한다.

    list_machines / get_machine_status를 호출하기 전에 이 도구로 db_path를
    확보해야 한다. branch_code는 list_branches 결과의 branch_code 컬럼 값과
    정확히 일치해야 한다.

    Args:
        branch_code: 브랜치 코드 (예: "F-A").
    """
    try:
        cols, rows = _read_query(
            _META_DB,
            "SELECT db_path FROM branches WHERE branch_code = :code",
            {"code": branch_code},
        )
    except (sqlite3.Error, UnsafeSqlError) as exc:
        return f"ERROR: 브랜치 DB 경로 조회 실패: {exc}"
    if not rows:
        return f"ERROR: 등록되지 않은 branch_code: {branch_code}"
    return str((_FACTORY_DB_ROOT / rows[0][0]).resolve())
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_tool_call_tools.py::TestGetBranchDbPath -v`
Expected: 2 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/tool_call_agent/tools.py tests/test_tool_call_tools.py
git commit -m "feat(tool-call-agent): add get_branch_db_path tool"
```

---

## Task 6: `list_machines` 도구

**Files:**
- Modify: `src/tool_call_agent/tools.py`
- Test: `tests/test_tool_call_tools.py`

- [ ] **Step 1: 테스트 추가**

Append to `tests/test_tool_call_tools.py`:

```python
class TestListMachines:
    def test_returns_machines_for_branch(self, factory_tmp: Path) -> None:
        db_path = str((factory_tmp / "branch_A.db").resolve())
        out = tools.list_machines.invoke({"db_path": db_path})
        assert "M-001" in out and "압출기 1호" in out
        assert "| machine_id |" in out

    def test_traversal_path_returns_error(self, factory_tmp: Path) -> None:
        out = tools.list_machines.invoke({"db_path": "../../etc/passwd"})
        assert out.startswith("ERROR: 머신 목록 조회 실패")
        assert "허용되지 않은" in out

    def test_meta_db_rejected(self, factory_tmp: Path) -> None:
        out = tools.list_machines.invoke({"db_path": "meta.db"})
        assert out.startswith("ERROR: 머신 목록 조회 실패")

    def test_missing_file_returns_error(self, factory_tmp: Path) -> None:
        out = tools.list_machines.invoke({"db_path": "branch_Z.db"})
        assert out.startswith("ERROR: 머신 목록 조회 실패")
        assert "존재하지 않는" in out
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_tool_call_tools.py::TestListMachines -v`
Expected: AttributeError — `list_machines`가 없음.

- [ ] **Step 3: 도구 구현**

Append to `src/tool_call_agent/tools.py`:

```python
@tool
def list_machines(db_path: str) -> str:
    """특정 브랜치 DB의 머신(설비) 목록을 markdown 표로 반환한다.

    db_path는 get_branch_db_path의 반환값을 그대로 사용한다.

    Args:
        db_path: 브랜치 DB 파일 경로.
    """
    try:
        db_file = _resolve_branch_db(db_path)
        cols, rows = _read_query(
            db_file,
            "SELECT machine_id, name, line, model FROM machines ORDER BY machine_id",
        )
    except (ValueError, sqlite3.Error, UnsafeSqlError) as exc:
        return f"ERROR: 머신 목록 조회 실패: {exc}"
    return _to_markdown(cols, rows)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_tool_call_tools.py::TestListMachines -v`
Expected: 4 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/tool_call_agent/tools.py tests/test_tool_call_tools.py
git commit -m "feat(tool-call-agent): add list_machines tool"
```

---

## Task 7: `get_machine_status` 도구 + TOOLS 리스트

**Files:**
- Modify: `src/tool_call_agent/tools.py`
- Test: `tests/test_tool_call_tools.py`

- [ ] **Step 1: 테스트 추가**

Append to `tests/test_tool_call_tools.py`:

```python
class TestGetMachineStatus:
    def test_returns_status_row(self, factory_tmp: Path) -> None:
        db_path = str((factory_tmp / "branch_A.db").resolve())
        out = tools.get_machine_status.invoke(
            {"db_path": db_path, "machine_id": "M-001"}
        )
        assert "M-001" in out
        assert "running" in out
        assert "0.92" in out

    def test_unknown_machine_returns_error(self, factory_tmp: Path) -> None:
        db_path = str((factory_tmp / "branch_A.db").resolve())
        out = tools.get_machine_status.invoke(
            {"db_path": db_path, "machine_id": "M-999"}
        )
        assert out.startswith("ERROR: 머신을 찾을 수 없습니다")


class TestToolsManifest:
    def test_tools_list_contains_four_tools(self) -> None:
        assert len(tools.TOOLS) == 4
        names = {t.name for t in tools.TOOLS}
        assert names == {
            "list_branches",
            "get_branch_db_path",
            "list_machines",
            "get_machine_status",
        }

    def test_tools_by_name_lookup(self) -> None:
        assert tools.TOOLS_BY_NAME["list_branches"] is tools.list_branches
        assert tools.TOOLS_BY_NAME["get_branch_db_path"] is tools.get_branch_db_path
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_tool_call_tools.py::TestGetMachineStatus tests/test_tool_call_tools.py::TestToolsManifest -v`
Expected: AttributeError — `get_machine_status`와 `TOOLS`가 없음.

- [ ] **Step 3: 도구 구현 + manifest**

Append to `src/tool_call_agent/tools.py`:

```python
@tool
def get_machine_status(db_path: str, machine_id: str) -> str:
    """특정 머신의 현재 상태/가동률을 markdown 표로 반환한다.

    Args:
        db_path: 브랜치 DB 파일 경로 (get_branch_db_path 결과).
        machine_id: 머신 id (list_machines 결과의 machine_id 컬럼).
    """
    try:
        db_file = _resolve_branch_db(db_path)
        cols, rows = _read_query(
            db_file,
            "SELECT m.machine_id, m.name, s.state, s.uptime_ratio, s.last_updated "
            "FROM machines m JOIN machine_status s ON m.machine_id = s.machine_id "
            "WHERE m.machine_id = :mid",
            {"mid": machine_id},
        )
    except (ValueError, sqlite3.Error, UnsafeSqlError) as exc:
        return f"ERROR: 머신 상태 조회 실패: {exc}"
    if not rows:
        return f"ERROR: 머신을 찾을 수 없습니다: {machine_id}"
    return _to_markdown(cols, rows)


TOOLS = [list_branches, get_branch_db_path, list_machines, get_machine_status]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
```

또한 파일 상단 import 정리: Task 4에서 `from langchain_core.tools import tool`을 모듈 중간에 두었다면, 상단의 다른 import 옆으로 옮긴다. 최종 `tools.py` 상단 import 블록:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from src.sql_agent.backend.safety import (
    UnsafeSqlError,
    inject_limit_if_missing,
    validate_select_only,
)
```

- [ ] **Step 4: 전체 도구 테스트 통과 확인**

Run: `uv run pytest tests/test_tool_call_tools.py -v`
Expected: 모든 테스트 통과 (총 ~21개).

- [ ] **Step 5: 커밋**

```bash
git add src/tool_call_agent/tools.py tests/test_tool_call_tools.py
git commit -m "feat(tool-call-agent): add get_machine_status tool and TOOLS manifest"
```

---

## Task 8: 시스템 프롬프트

**Files:**
- Create: `src/tool_call_agent/prompt.py`

(이 태스크는 정적 문자열 정의이므로 단위 테스트는 다음 태스크의 통합 테스트로 흡수한다.)

- [ ] **Step 1: 프롬프트 파일 작성**

Create `src/tool_call_agent/prompt.py`:

```python
"""tool_call 에이전트 시스템 프롬프트.

도메인 어휘를 포함하지 않는다. 도구의 의미는 LangChain bind_tools가
각 @tool 함수의 docstring과 시그니처에서 자동 추출한다.
"""

SYSTEM_PROMPT = """\
당신은 사전 정의된 도구들을 사용해 사용자의 정보 조회 요청을 처리하는 에이전트입니다.
사용 가능한 도구의 이름·설명·파라미터 스키마는 시스템이 별도로 제공합니다 (tool 바인딩).

## 처리 규칙

1. 사용자의 의도를 충족하려면 어떤 도구를, 어떤 순서로 호출해야 하는지 먼저 판단하세요.
2. 한 도구의 결과가 다른 도구의 파라미터로 필요하면 순차적으로 호출하세요 (한 턴 안에서 여러 번 호출 가능).
3. 도구 호출에 필요한 파라미터를 사용자 메시지나 이전 도구 결과에서 확보할 수 없으면, 도구를 호출하지 말고 사용자에게 자연어로 부족한 정보를 묻고 응답을 종료하세요.
4. 파라미터 값을 추측·날조하지 마세요. 사용자가 명시하지 않았고 도구로도 얻을 수 없는 값은 missing입니다.
5. 사용자에게 되물을 때, 후보값을 조회할 수 있는 도구가 있다면 "전체 목록을 보여드릴까요?" 형태로 제안하세요. 사용자가 동의하면 다음 턴에 해당 도구를 호출합니다.
6. 도구가 "ERROR: ..."로 시작하는 결과를 반환하면, 메시지를 읽고 (a) 파라미터를 수정해 재시도하거나 (b) 사용자에게 사유를 안내하세요.
7. 최종 응답은 도구 결과를 정리해 사용자가 바로 이해할 수 있는 형태로 작성하세요. 도구의 markdown 표는 보존하세요.
8. 시스템 내부 식별자(예: DB 파일 경로)는 사용자에게 노출하지 마세요. 사용자 친화적인 이름(브랜치 이름 등)으로 환원해서 보여주세요.

## 출력 형식

- 도구를 호출할 때는 tool_calls만 반환하세요 (텍스트는 비워도 됩니다).
- 사용자에게 응답할 때는 일반 자연어로 반환하세요 (tool_calls 없음).
"""
```

- [ ] **Step 2: 커밋**

```bash
git add src/tool_call_agent/prompt.py
git commit -m "feat(tool-call-agent): add system prompt"
```

---

## Task 9: ReAct 서브그래프 + wrapper

**Files:**
- Create: `src/tool_call_agent/agent.py`
- Modify: `src/tool_call_agent/__init__.py`
- Test: `tests/test_tool_call_agent.py`

- [ ] **Step 1: 테스트 파일 작성**

Create `tests/test_tool_call_agent.py`:

```python
"""tool_call 에이전트 wrapper + 서브그래프 단위 테스트.

LLM은 mock으로 tool_calls / 최종 응답을 시드한다.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from res.sample_db.factory import seed
from src.tool_call_agent import tools


@pytest.fixture
def factory_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """factory DB를 tmp에 시드하고, tools 모듈의 경로 상수를 리다이렉트."""
    monkeypatch.setattr(seed, "FACTORY_DIR", tmp_path)
    monkeypatch.setattr(seed, "META_DB_PATH", tmp_path / "meta.db")
    monkeypatch.setattr(tools, "_FACTORY_DB_ROOT", tmp_path)
    monkeypatch.setattr(tools, "_META_DB", tmp_path / "meta.db")
    seed.run()
    return tmp_path


def _state(user_text: str) -> dict:
    return {
        "messages": [HumanMessage(content=user_text)],
        "next_agent": "",
        "chat_history": [],
    }


def _ai_with_tool_calls(calls: list[dict]) -> AIMessage:
    msg = AIMessage(content="")
    msg.tool_calls = calls  # type: ignore[attr-defined]
    return msg


def _llm_sequence(responses: list) -> MagicMock:
    """LLM을 mock으로 만들어 invoke 호출마다 순서대로 응답을 반환."""
    llm = MagicMock()
    bound = MagicMock()
    bound.invoke = MagicMock(side_effect=responses)
    llm.bind_tools.return_value = bound
    return llm


class TestSubgraphFlow:
    @patch("src.tool_call_agent.agent.get_chat_model")
    def test_single_tool_call_then_finish(
        self, mock_chat: MagicMock, factory_tmp: Path
    ) -> None:
        from src.tool_call_agent.agent import tool_call_subgraph

        mock_chat.return_value = _llm_sequence([
            _ai_with_tool_calls([
                {"id": "c1", "name": "list_branches", "args": {}},
            ]),
            AIMessage(content="다음 브랜치가 있습니다: F-A, F-B, F-C"),
        ])

        result = tool_call_subgraph.invoke(
            {"messages": [HumanMessage("어떤 브랜치 있어?")]}
        )
        final = result["messages"][-1]
        assert isinstance(final, AIMessage)
        assert "F-A" in final.content

    @patch("src.tool_call_agent.agent.get_chat_model")
    def test_three_step_chain(
        self, mock_chat: MagicMock, factory_tmp: Path
    ) -> None:
        from src.tool_call_agent.agent import tool_call_subgraph

        db_path = str((factory_tmp / "branch_A.db").resolve())
        mock_chat.return_value = _llm_sequence([
            _ai_with_tool_calls([
                {"id": "c1", "name": "list_branches", "args": {}},
            ]),
            _ai_with_tool_calls([
                {"id": "c2", "name": "get_branch_db_path",
                 "args": {"branch_code": "F-A"}},
            ]),
            _ai_with_tool_calls([
                {"id": "c3", "name": "get_machine_status",
                 "args": {"db_path": db_path, "machine_id": "M-001"}},
            ]),
            AIMessage(content="F-A의 M-001 머신 상태입니다: running"),
        ])

        result = tool_call_subgraph.invoke(
            {"messages": [HumanMessage("아산 1공장 M-001 상태")]}
        )
        final = result["messages"][-1]
        assert isinstance(final, AIMessage)
        assert "running" in final.content

    @patch("src.tool_call_agent.agent.get_chat_model")
    def test_clarification_without_tool_call(
        self, mock_chat: MagicMock, factory_tmp: Path
    ) -> None:
        from src.tool_call_agent.agent import tool_call_subgraph

        mock_chat.return_value = _llm_sequence([
            AIMessage(content="어느 브랜치의 어느 머신을 조회할까요?"),
        ])

        result = tool_call_subgraph.invoke(
            {"messages": [HumanMessage("머신 상태")]}
        )
        final = result["messages"][-1]
        assert isinstance(final, AIMessage)
        assert "어느 브랜치" in final.content

    @patch("src.tool_call_agent.agent.get_chat_model")
    def test_unknown_tool_name_recovers(
        self, mock_chat: MagicMock, factory_tmp: Path
    ) -> None:
        from src.tool_call_agent.agent import tool_call_subgraph

        mock_chat.return_value = _llm_sequence([
            _ai_with_tool_calls([
                {"id": "c1", "name": "does_not_exist", "args": {}},
            ]),
            AIMessage(content="죄송합니다. 다시 시도하겠습니다."),
        ])

        result = tool_call_subgraph.invoke(
            {"messages": [HumanMessage("아무거나")]}
        )
        # 에러 ToolMessage가 LLM에게 전달되고, LLM이 자연어로 종료.
        tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert any("알 수 없는 tool" in m.content for m in tool_msgs)

    @patch("src.tool_call_agent.agent.get_chat_model")
    def test_tool_exception_surfaced_as_error(
        self, mock_chat: MagicMock, factory_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.tool_call_agent import agent as agent_mod

        def _raising_tool(*args, **kwargs):
            raise RuntimeError("boom")

        broken = MagicMock()
        broken.invoke = _raising_tool
        monkeypatch.setitem(agent_mod.TOOLS_BY_NAME, "list_branches", broken)

        mock_chat.return_value = _llm_sequence([
            _ai_with_tool_calls([
                {"id": "c1", "name": "list_branches", "args": {}},
            ]),
            AIMessage(content="실패했습니다."),
        ])

        result = agent_mod.tool_call_subgraph.invoke(
            {"messages": [HumanMessage("어떤 브랜치?")]}
        )
        tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert any("실행 중 예외" in m.content for m in tool_msgs)


class TestWrapper:
    @patch("src.tool_call_agent.agent.get_chat_model")
    def test_wrapper_tags_output(
        self, mock_chat: MagicMock, factory_tmp: Path
    ) -> None:
        from src.tool_call_agent.agent import tool_call_wrapper

        mock_chat.return_value = _llm_sequence([
            AIMessage(content="브랜치 F-A, F-B, F-C"),
        ])

        result = tool_call_wrapper(_state("어떤 브랜치"))
        assert result["messages"][0].content.startswith("[조회 결과]\n")

    def test_wrapper_registered(self) -> None:
        from src.registry import registry
        import src.tool_call_agent  # noqa: F401  - 등록 트리거

        names = registry.agent_names
        assert "tool_call" in names

    def test_wrapper_description_has_routing_hints(self) -> None:
        from src.registry import registry
        import src.tool_call_agent  # noqa: F401

        entry = registry.get("tool_call")
        assert entry is not None
        desc = entry.description
        assert "브랜치" in desc
        assert "머신" in desc
        assert "ecommerce" in desc  # 라우팅 배제 가이드
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_tool_call_agent.py -v`
Expected: ImportError — `src.tool_call_agent.agent`가 없음.

- [ ] **Step 3: agent.py 구현**

Create `src/tool_call_agent/agent.py`:

```python
"""tool_call 에이전트: 함수형 도구 ReAct 서브그래프."""

from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.registry import registry
from src.state import State, WorkerState
from src.tool_call_agent.prompt import SYSTEM_PROMPT
from src.tool_call_agent.tools import TOOLS, TOOLS_BY_NAME

logger = get_logger("agent.tool_call")
router_logger = get_logger("router.tool_call")


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def build_tool_call_agent() -> CompiledStateGraph:
    """ReAct 서브그래프(agent ↔ tools 루프)를 빌드한다."""

    @log_node("tool_call_agent_internal")
    def agent_node(state: WorkerState) -> dict:
        llm = get_chat_model().bind_tools(TOOLS)
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]

        logger.info("LLM 호출 시작 (tools=%d)", len(TOOLS))
        try:
            response = llm.invoke(messages)
        except Exception:
            logger.error("LLM 호출 실패", exc_info=True)
            raise

        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls:
            logger.info(
                "LLM tool_calls: %s",
                [(tc["name"], _truncate(str(tc["args"]))) for tc in tool_calls],
            )
        else:
            logger.info("LLM 최종 응답: %s", _truncate(str(response.content), 200))

        return {"messages": [response]}

    @log_node("tool_call_tool_executor")
    def tool_executor_node(state: WorkerState) -> dict:
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", []) or []

        results: list[ToolMessage] = []
        for tc in tool_calls:
            fn = TOOLS_BY_NAME.get(tc["name"])
            if fn is None:
                logger.error("알 수 없는 tool: %s", tc["name"])
                results.append(ToolMessage(
                    content=f"ERROR: 알 수 없는 tool '{tc['name']}'",
                    tool_call_id=tc["id"],
                ))
                continue

            logger.info("tool 실행: %s(%s)", tc["name"], _truncate(str(tc["args"])))
            try:
                out = fn.invoke(tc["args"])
                results.append(ToolMessage(content=str(out), tool_call_id=tc["id"]))
            except Exception as exc:
                logger.error("tool 실행 실패: %s", tc["name"], exc_info=True)
                results.append(ToolMessage(
                    content=f"ERROR: {tc['name']} 실행 중 예외: {exc}",
                    tool_call_id=tc["id"],
                ))
        return {"messages": results}

    def should_continue(state: WorkerState) -> str:
        last = state["messages"][-1]
        has_tool_calls = bool(getattr(last, "tool_calls", None))
        decision = "tools" if has_tool_calls else END
        router_logger.info(
            "should_continue: tool_calls=%s → %s", has_tool_calls, decision,
        )
        return decision

    graph = StateGraph(WorkerState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_executor_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()


tool_call_subgraph = build_tool_call_agent()


@registry.agent("tool_call")
@log_node("tool_call")
def tool_call_wrapper(state: State) -> dict:
    """제조업 브랜치(공장)별 머신 정보 조회를 처리합니다.

    처리 가능한 질의 유형:
    - 등록된 브랜치(공장) 목록 조회 (예: "어떤 브랜치가 있어?", "공장 목록 보여줘")
    - 특정 브랜치의 머신(설비) 목록 조회 (예: "아산 1공장의 머신 목록", "F-A 브랜치의 설비")
    - 특정 머신의 현재 상태/가동률 조회 (예: "아산 1공장 M-001 머신 상태", "F-B의 압출기 가동률")
    - 브랜치를 모르고 질문한 경우 사용자에게 어느 브랜치인지 되묻고, 사용자가 동의하면 브랜치 목록을 제공

    데이터 구조:
    - 본사 메타DB에 브랜치 코드/이름/지역/DB 경로가 등록되어 있음
    - 각 브랜치마다 별도의 DB 파일이 존재하며, 머신 정보는 해당 브랜치 DB에서만 조회 가능
    - 따라서 브랜치 정보가 명시되지 않은 머신 질의는 먼저 브랜치를 확정해야 함

    실행 방식:
    - 사전 정의된 함수형 도구들(브랜치 목록 조회, 브랜치 DB 경로 조회, 머신 목록 조회, 머신 상태 조회)을 ReAct 루프로 순차/조합 호출
    - 도구 실행에 필요한 파라미터(브랜치 코드, 머신 id 등)가 부족하면 사용자에게 자연어로 되묻고 그 턴을 종료. 다음 턴에서 사용자가 정보를 보충하면 이어서 실행

    라우팅 가이드:
    - 브랜치/공장/머신/설비/가동률/라인 같은 제조 도메인 키워드가 등장하면 이 에이전트
    - 직원/부서/고객/제품/주문 등 ecommerce 도메인은 이 에이전트가 아님 (sql 또는 templated_sql)
    - 자유형 임의 SQL이 필요한 분석성 질의는 이 에이전트가 아님 (sql)
    """
    try:
        result = tool_call_subgraph.invoke({"messages": state["messages"]})
    except Exception:
        logger.error("서브그래프 실행 실패", exc_info=True)
        raise

    last = result["messages"][-1]
    return {"messages": [AIMessage(content=f"[조회 결과]\n{last.content}")]}
```

Replace `src/tool_call_agent/__init__.py` content with:

```python
from src.tool_call_agent.agent import tool_call_wrapper  # noqa: F401 - 등록 트리거
from src.tool_call_agent.tools import TOOLS, TOOLS_BY_NAME  # noqa: F401

__all__ = ["tool_call_wrapper", "TOOLS", "TOOLS_BY_NAME"]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_tool_call_agent.py -v`
Expected: 모든 테스트 통과 (총 7개).

- [ ] **Step 5: 커밋**

```bash
git add src/tool_call_agent/agent.py src/tool_call_agent/__init__.py tests/test_tool_call_agent.py
git commit -m "feat(tool-call-agent): add ReAct subgraph and registered wrapper"
```

---

## Task 10: 메인 패키지에 에이전트 등록 + 데모 시나리오 G

**Files:**
- Modify: `src/__init__.py`
- Modify: `src/main.py`

- [ ] **Step 1: 등록 트리거 import 추가**

Edit `src/__init__.py` — 주석 바로 아래 import 블록에 한 줄 추가 (알파벳 순서로 sql_agent와 templated_sql_agent 사이 위치):

```python
# 각 에이전트 모듈을 import하여 @registry.agent 데코레이터를 통한 자동 등록을 트리거한다.
from src.math_agent import math_wrapper  # noqa: F401
from src.registry import registry  # noqa: F401
from src.sql_agent import sql_wrapper  # noqa: F401
from src.templated_sql_agent import templated_sql_wrapper  # noqa: F401
from src.tool_call_agent import tool_call_wrapper  # noqa: F401
from src.translate_agent import translate_wrapper  # noqa: F401

__all__ = [
    "math_wrapper",
    "registry",
    "sql_wrapper",
    "templated_sql_wrapper",
    "tool_call_wrapper",
    "translate_wrapper",
]
```

- [ ] **Step 2: 데모 시나리오 G 추가**

Edit `src/main.py` — `run_three_turn_scenario(app, "F", ...)` 호출 바로 뒤에 시나리오 G 추가:

```python
    run_three_turn_scenario(
        app, "G",
        "tool_call 멀티턴 — 파라미터 부족 → 브랜치 목록 → 머신 상태 조회",
        "머신 상태 알려줘",
        "응 브랜치 목록 보여줘",
        "아산 1공장의 M-001 상태",
    )
```

- [ ] **Step 3: 라우터/그래프 통합 회귀 확인**

Run: `uv run pytest -v` (전체 테스트)
Expected: 모든 기존 테스트가 그대로 통과해야 함. 신규 테스트 포함 전체 통과.

- [ ] **Step 4: 시나리오 G 수동 실행 (외부 LLM 호출 필요)**

`.env`에 `OPENAI_API_KEY`가 설정된 경우에만:

Run: `uv run python -m src.main 2>&1 | tail -60`
Expected: 시나리오 G가 3턴 모두 정상 실행되고, 최종 메시지에 머신 상태 markdown이 포함됨.

(API 키가 없으면 이 단계는 건너뛰고 다음 태스크에서 다시 시도)

- [ ] **Step 5: 커밋**

```bash
git add src/__init__.py src/main.py
git commit -m "feat(tool-call-agent): register agent and add demo scenario G"
```

---

## Task 11: CLI 추천 질문 추가

**Files:**
- Modify: `res/suggestions.yaml`

- [ ] **Step 1: 카테고리 추가**

Edit `res/suggestions.yaml` — 파일 끝(또는 알파벳 순서가 맞는 위치)에 `tool_call` 카테고리 추가:

```yaml
tool_call:
  - "어떤 브랜치가 등록되어 있어?"
  - "아산 1공장의 머신 목록 보여줘"
  - "F-A 브랜치의 M-001 머신 상태 알려줘"
  - "구미 2공장에 어떤 머신이 있어?"
  - "머신 상태 조회해줘"
```

- [ ] **Step 2: YAML 파싱 확인**

Run: `uv run python -c "import yaml; print(list(yaml.safe_load(open('res/suggestions.yaml')).keys()))"`
Expected: `tool_call`이 포함된 키 리스트 출력.

- [ ] **Step 3: 기존 추천 테스트 회귀 확인**

Run: `uv run pytest tests/test_cli_suggestions.py -v`
Expected: 모든 기존 테스트 통과.

- [ ] **Step 4: 커밋**

```bash
git add res/suggestions.yaml
git commit -m "feat(tool-call-agent): add CLI suggestions for tool_call category"
```

---

## Task 12: README 업데이트

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Architecture 다이어그램 업데이트**

Edit `README.md` lines 7-13 — 다이어그램 분기에 tool_call_agent 추가:

```
[START] → [query_rewriter] → [router] ─┬→ [math_agent]          ─┐
                                       ├→ [translate_agent]      │
                                       ├→ [sql_agent]            ├→ [response_generator] → [END]
                                       ├→ [templated_sql_agent]  │
                                       ├→ [tool_call_agent]      │
                                       └→ [response_generator] (FINISH)
```

- [ ] **Step 2: subagents 한 줄 설명에 tool_call 추가**

Edit `README.md` line 17 — 기존 문장:

```
- **subagents** — `math`, `translate`, `sql`, `templated_sql` 중 선택된 하나만 실행된다.
```

를 다음으로 교체:

```
- **subagents** — `math`, `translate`, `sql`, `templated_sql`, `tool_call` 중 선택된 하나만 실행된다.
```

- [ ] **Step 3: 데모 시나리오 목록에 G 추가**

Edit `README.md` lines 30-36 — 시나리오 목록 끝에 G 추가:

```
- **G** `tool_call` 멀티턴 — 제조업 브랜치별 머신 DB 조회 (정보 부족 → 브랜치 목록 → 머신 상태)의 3턴 시퀀스 시연
```

- [ ] **Step 4: Project Structure 트리에 tool_call_agent 추가**

Edit `README.md` Project Structure 섹션의 `src/` 트리 — `templated_sql_agent` 항목 바로 아래에 추가:

```
│   ├── tool_call_agent/      # 함수형 도구 ReAct 기반 멀티 DB 조회 (제조업 브랜치/머신)
│   │   ├── agent.py          #   ReAct 서브그래프 + wrapper
│   │   ├── tools.py          #   4개 @tool 함수 + path 화이트리스트 + sqlite 헬퍼
│   │   └── prompt.py         #   범용 시스템 프롬프트 (도메인 어휘 없음)
```

또한 `res/sample_db/`의 설명 줄 다음에 한 줄 추가 (또는 트리 안에 표시):

```
│   └── sample_db/factory/    # 제조업 메타DB + 3개 브랜치 DB 시드 (tool_call용)
```

- [ ] **Step 5: Subagents 표에 tool_call 행 추가**

Edit `README.md` Subagents 표 (88-91행 부근) — `templated_sql` 행 다음에 추가:

```
| `tool_call` | ReAct | `list_branches`, `get_branch_db_path`, `list_machines`, `get_machine_status` (factory 메타DB + 브랜치별 sqlite, read-only) |
```

- [ ] **Step 6: README 변경 확인**

Run: `git diff README.md | head -80`
Expected: 다이어그램, 시나리오 목록, Project Structure, Subagents 표에 tool_call 관련 추가가 보임.

- [ ] **Step 7: 커밋**

```bash
git add README.md
git commit -m "docs(tool-call-agent): update README with new agent and scenario G"
```

---

## Task 13: 전체 회귀 + 최종 검증

**Files:**
- (테스트 실행만, 코드 변경 없음)

- [ ] **Step 1: 전체 테스트 통과**

Run: `uv run pytest -v`
Expected: 모든 테스트 통과. 새 테스트 ≥28개 + 기존 테스트 모두 PASS.

- [ ] **Step 2: 라우터 동작 빠른 확인 (선택)**

`OPENAI_API_KEY`가 있다면:

Run: `uv run python -c "
from dotenv import load_dotenv; load_dotenv()
import src  # noqa
from src.registry import registry
print('등록된 에이전트:', registry.agent_names)
"`
Expected: `['math', 'sql', 'templated_sql', 'tool_call', 'translate']` (순서는 import 순서)

- [ ] **Step 3: 시드 산출물이 .gitignore에 들어가는지 확인**

기존 `.gitignore`에 `*.db`나 `res/sample_db/*.db`가 있는지 확인:

Run: `grep -n "\.db" /Users/randy/claude_code/supervisor-subagent/.gitignore 2>/dev/null || echo "no .db rule"`

만약 ecommerce.db 패턴만 있고 factory DB가 커밋 대상에 들어간다면, 다음을 `.gitignore`에 추가:

```
res/sample_db/factory/*.db
```

이후:

```bash
git status
```

`res/sample_db/factory/` 아래에 시드된 .db들이 untracked 또는 ignored 상태인지 확인. 만약 tracked로 잘못 잡혔으면 `git rm --cached res/sample_db/factory/*.db`로 정리.

(seed.py 자체는 커밋되어야 하지만, 자동 생성된 .db 파일은 커밋 대상이 아니다. 기존 `ecommerce.db`가 어떻게 처리되는지 확인 후 동일 패턴 적용.)

- [ ] **Step 4: (필요 시) .gitignore 커밋**

위 Step 3에서 변경이 있었다면:

```bash
git add .gitignore
git commit -m "chore(tool-call-agent): ignore generated factory db files"
```

- [ ] **Step 5: 작업 요약**

`git log --oneline -15`로 본 plan에서 만든 커밋들이 한눈에 보이는지 확인. 모든 태스크의 커밋이 atomic하고 메시지가 명확한지 점검.

---

## Self-Review

### 1. Spec coverage
| Spec 섹션 | 구현 태스크 |
|---|---|
| 디렉토리 구조 | Task 1 (factory dir), Tasks 2/4/7/8/9 (agent dir) |
| 에이전트 그래프 (agent.py) | Task 9 |
| 시스템 프롬프트 (prompt.py) | Task 8 |
| 도구 시그니처 | Tasks 4 (list_branches), 5 (get_branch_db_path), 6 (list_machines), 7 (get_machine_status + manifest) |
| 샘플 DB (meta + 3 branch) | Task 1 |
| 안전 정책 3중망 + 화이트리스트 | Task 2 (path), Task 3 (validate + LIMIT + read-only) |
| 에러 처리 표준 | Task 5/6/7 (ERROR 문자열), Task 9 (ToolMessage ERROR) |
| 멀티턴 흐름 시나리오 G | Task 10 (데모 추가) |
| 그래프/라우터 통합 | Task 10 (src/__init__.py 등록) |
| CLI 추천 질문 | Task 11 |
| 테스트 (tools/agent/seed) | Tasks 1, 2~7, 9 |
| README 업데이트 | Task 12 |

모든 spec 섹션이 어떤 태스크에 매핑됨. 누락 없음.

### 2. Placeholder scan
- TBD/TODO/FIXME 없음
- 모든 step이 실제 코드 또는 명령어 포함

### 3. Type consistency
- `TOOLS: list`, `TOOLS_BY_NAME: dict[str, BaseTool]` — Task 7에서 정의, Task 9에서 사용 (일관)
- `_resolve_branch_db(db_path: str) -> Path` — Task 2에서 정의, Tasks 6/7에서 호출
- `_read_query(...) -> tuple[list[str], list[tuple]]` — Task 3에서 정의, Tasks 4/5/6/7에서 호출
- `seed.run()` — Task 1에서 정의, 테스트 fixture에서 호출 (Tasks 2/3/4/5/6/7/9), 직접 도구 코드에서는 호출하지 않음 (도구는 시드된 DB가 이미 있다고 가정 — 자동 시드는 별도 책임으로 분리할 수도 있으나 v1은 수동 시드 또는 테스트 fixture가 시드)

**주의:** spec의 `_ensure_seeded()`는 본 plan에서는 구현하지 않았다. 도구는 시드된 DB를 가정한다. 실서비스에서 첫 호출 시 자동 시드가 필요하면 후속 PR에서 추가. v1 데모와 테스트는 (a) 데모는 사전에 `python -m res.sample_db.factory.seed`를 한 번 돌려두거나 (b) 테스트는 fixture에서 `seed.run()`을 호출하므로 충분히 동작한다.

이를 README의 "Quick Start" 부근에 한 줄로 명시:

```
첫 실행 전 1회: uv run python -m res.sample_db.factory.seed   # tool_call 에이전트용 멀티 DB 시드
```

→ **Task 12에 이 한 줄을 추가**한다 (Step 7로 흡수). 아래 수정:

**Task 12 Step 4에 추가 항목:**

Edit `README.md` Quick Start 섹션 — 기존 `uv run python -m src.cli` 줄 다음에 한 줄 추가:

```bash
uv run python -m res.sample_db.factory.seed  # tool_call용 multi DB 시드 (최초 1회)
```

(이 항목은 위 Task 12의 Step들 사이에 적절히 삽입; 본 plan을 실행할 때는 README 편집을 한 커밋으로 묶어서 처리하면 됨.)

---

## 실행 핸드오프

Plan 완료. 저장 경로: `docs/superpowers/plans/2026-05-13-tool-call-agent.md`

두 가지 실행 방식:

1. **Subagent-Driven (추천)** — 태스크마다 fresh subagent 디스패치, 각 태스크 사이에 리뷰. 빠른 반복.
2. **Inline Execution** — 본 세션에서 직접 실행, 체크포인트마다 리뷰.

어느 방식으로 진행할까요?
