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
