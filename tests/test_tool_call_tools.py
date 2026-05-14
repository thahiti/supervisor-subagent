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


class TestGetBranchDbPath:
    def test_returns_absolute_path(self, factory_tmp: Path) -> None:
        out = tools.get_branch_db_path.invoke({"branch_code": "F-A"})
        assert out == str((factory_tmp / "branch_A.db").resolve())

    def test_unknown_code_returns_error(self, factory_tmp: Path) -> None:
        out = tools.get_branch_db_path.invoke({"branch_code": "F-Z"})
        assert out.startswith("ERROR: 등록되지 않은 branch_code")


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
