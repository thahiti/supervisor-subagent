"""SQL agent frontend 통합 테스트.

LLM을 호출하지 않고 tool 어댑터와 registry 등록을 검증한다.
실제 LLM 기반 end-to-end 검증은 evals/에 위임한다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.registry import registry
from src.sql_agent.backend import SqlExecutor
from src.sql_agent import tools as sql_tools


@pytest.fixture
def toy_executor(tmp_path: Path) -> SqlExecutor:
    db = tmp_path / "toy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO departments VALUES (1, '엔지니어링'), (2, '영업');
        """
    )
    conn.commit()
    conn.close()
    return SqlExecutor(db, auto_seed=False)


@pytest.fixture
def injected_tools(toy_executor: SqlExecutor):
    original = sql_tools._executor
    sql_tools.set_executor(toy_executor)
    yield
    sql_tools.set_executor(original)


class TestToolAdapters:
    def test_execute_sql_returns_markdown(self, injected_tools) -> None:
        result = sql_tools.execute_sql.invoke({"query": "SELECT name FROM departments"})
        assert "엔지니어링" in result
        assert "영업" in result

    def test_execute_sql_blocks_write(self, injected_tools) -> None:
        result = sql_tools.execute_sql.invoke(
            {"query": "UPDATE departments SET name = 'x'"},
        )
        assert result.startswith("ERROR:")

    def test_list_tables_returns_toy_tables(self, injected_tools) -> None:
        result = sql_tools.list_tables.invoke({})
        assert "departments" in result

    def test_get_schema_returns_ddl(self, injected_tools) -> None:
        result = sql_tools.get_schema.invoke({"table": "departments"})
        assert "CREATE TABLE departments" in result

    def test_get_schema_rejects_unknown_table(self, injected_tools) -> None:
        result = sql_tools.get_schema.invoke({"table": "ghost"})
        assert result.startswith("ERROR:")


class TestRegistration:
    def test_sql_agent_in_registry(self) -> None:
        import src  # noqa: F401

        entry = registry.get("sql")
        assert entry is not None
        assert entry.node_name == "sql_agent"
        assert "ecommerce" in entry.description.lower() or "데이터베이스" in entry.description

    def test_workers_prompt_includes_sql(self) -> None:
        import src  # noqa: F401

        prompt = registry.build_workers_prompt()
        assert "**sql**" in prompt
