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
