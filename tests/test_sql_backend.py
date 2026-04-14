"""SQL agent backend 단위 테스트.

도메인 무지를 유지하기 위해 fixture DB는 실제 ecommerce 스키마가 아닌
작은 toy 스키마를 사용한다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.agents.sql_agent.backend import SqlExecutor
from src.agents.sql_agent.backend.safety import (
    UnsafeSqlError,
    inject_limit_if_missing,
    validate_select_only,
)


@pytest.fixture
def toy_db(tmp_path: Path) -> Path:
    """작은 toy DB를 생성한다."""
    db = tmp_path / "toy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, qty INTEGER);
        INSERT INTO items VALUES (1, 'apple', 10);
        INSERT INTO items VALUES (2, 'banana', 5);
        INSERT INTO items VALUES (3, 'cherry', NULL);
        """
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def executor(toy_db: Path) -> SqlExecutor:
    return SqlExecutor(toy_db, auto_seed=False)


class TestSafety:
    def test_select_allowed(self) -> None:
        validate_select_only("SELECT * FROM t")

    def test_with_cte_allowed(self) -> None:
        validate_select_only("WITH x AS (SELECT 1) SELECT * FROM x")

    def test_lowercase_allowed(self) -> None:
        validate_select_only("select * from t")

    def test_leading_whitespace_allowed(self) -> None:
        validate_select_only("   \n  SELECT 1")

    def test_trailing_semicolon_allowed(self) -> None:
        validate_select_only("SELECT 1;")

    def test_empty_rejected(self) -> None:
        with pytest.raises(UnsafeSqlError):
            validate_select_only("")

    def test_insert_rejected(self) -> None:
        with pytest.raises(UnsafeSqlError):
            validate_select_only("INSERT INTO t VALUES (1)")

    def test_update_rejected(self) -> None:
        with pytest.raises(UnsafeSqlError):
            validate_select_only("UPDATE t SET x = 1")

    def test_delete_rejected(self) -> None:
        with pytest.raises(UnsafeSqlError):
            validate_select_only("DELETE FROM t")

    def test_drop_rejected(self) -> None:
        with pytest.raises(UnsafeSqlError):
            validate_select_only("DROP TABLE t")

    def test_multi_statement_rejected(self) -> None:
        with pytest.raises(UnsafeSqlError):
            validate_select_only("SELECT 1; SELECT 2")

    def test_keyword_in_string_literal_allowed(self) -> None:
        validate_select_only("SELECT * FROM t WHERE name = 'UPDATE me'")

    def test_pragma_rejected(self) -> None:
        with pytest.raises(UnsafeSqlError):
            validate_select_only("PRAGMA table_info(t)")

    def test_attach_rejected(self) -> None:
        with pytest.raises(UnsafeSqlError):
            validate_select_only("ATTACH DATABASE 'x' AS y")


class TestLimitInjection:
    def test_adds_limit_when_missing(self) -> None:
        assert inject_limit_if_missing("SELECT * FROM t", 100) == "SELECT * FROM t LIMIT 100"

    def test_preserves_existing_limit(self) -> None:
        assert inject_limit_if_missing("SELECT * FROM t LIMIT 5", 100) == "SELECT * FROM t LIMIT 5"

    def test_ignores_limit_in_string_literal(self) -> None:
        result = inject_limit_if_missing("SELECT 'LIMIT' FROM t", 100)
        assert result.endswith("LIMIT 100")


class TestExecute:
    def test_select_returns_rows(self, executor: SqlExecutor) -> None:
        r = executor.execute("SELECT name FROM items ORDER BY id")
        assert r["ok"]
        assert r["columns"] == ["name"]
        assert [row[0] for row in r["rows"]] == ["apple", "banana", "cherry"]

    def test_null_formatted(self, executor: SqlExecutor) -> None:
        r = executor.execute("SELECT qty FROM items WHERE id = 3")
        assert r["ok"]
        assert "NULL" in r["markdown"]

    def test_update_blocked_by_safety(self, executor: SqlExecutor) -> None:
        r = executor.execute("UPDATE items SET qty = 0")
        assert not r["ok"]
        assert "읽기 전용" in r["error"]

    def test_update_blocked_by_readonly_connection(
        self, executor: SqlExecutor, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """safety를 우회해도 read-only URI가 막는다 (defense-in-depth)."""
        monkeypatch.setattr(
            "src.agents.sql_agent.backend.executor.validate_select_only",
            lambda q: None,
        )
        r = executor.execute("UPDATE items SET qty = 0")
        assert not r["ok"]
        assert "SQLite 오류" in r["error"]

    def test_syntax_error_returns_structured_result(
        self, executor: SqlExecutor,
    ) -> None:
        r = executor.execute("SELECT FROM nowhere")
        assert not r["ok"]
        assert "SQLite 오류" in r["error"]

    def test_limit_auto_injected(self, executor: SqlExecutor) -> None:
        r = executor.execute("SELECT * FROM items")
        assert r["ok"]
        assert len(r["rows"]) == 3

    def test_empty_result_markdown(self, executor: SqlExecutor) -> None:
        r = executor.execute("SELECT name FROM items WHERE id = 999")
        assert r["ok"]
        assert "0개 행" in r["markdown"]


class TestInspection:
    def test_list_tables(self, executor: SqlExecutor) -> None:
        r = executor.list_tables()
        assert r["ok"]
        names = [row[0] for row in r["rows"]]
        assert names == ["items"]

    def test_get_schema(self, executor: SqlExecutor) -> None:
        r = executor.get_schema("items")
        assert r["ok"]
        assert "CREATE TABLE items" in r["rows"][0][0]

    def test_get_schema_unknown_table(self, executor: SqlExecutor) -> None:
        r = executor.get_schema("nonexistent")
        assert not r["ok"]
        assert "찾을 수 없음" in r["error"]

    def test_get_schema_rejects_unsafe_identifier(
        self, executor: SqlExecutor,
    ) -> None:
        r = executor.get_schema("items; DROP TABLE items")
        assert not r["ok"]
        assert "잘못된 테이블명" in r["error"]


class TestDbPath:
    def test_missing_db_without_auto_seed_raises(self, tmp_path: Path) -> None:
        executor = SqlExecutor(tmp_path / "nope.db", auto_seed=False)
        r = executor.execute("SELECT 1")
        assert not r["ok"]
