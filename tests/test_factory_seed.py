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
