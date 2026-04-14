"""Frontend ↔ Backend 어댑터 레이어.

LangChain @tool로 Backend SqlExecutor의 메서드를 감싸 LLM에
노출한다. LLM은 Backend 구조를 전혀 알 필요가 없다.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from src.agents.sql_agent.backend import SqlExecutor

DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "res" / "sample_db" / "ecommerce.db"

_executor: SqlExecutor = SqlExecutor(DEFAULT_DB_PATH)


def set_executor(executor: SqlExecutor) -> None:
    """테스트/DI 용: 모듈 레벨 executor를 교체한다."""
    global _executor
    _executor = executor


@tool
def execute_sql(query: str) -> str:
    """SELECT 쿼리를 실행하고 결과를 Markdown 표로 반환한다.

    LIMIT이 없으면 자동으로 100이 적용된다. INSERT/UPDATE 등
    쓰기 쿼리는 시스템이 거부한다. 에러 발생 시 'ERROR: ...'로
    시작하는 문자열을 반환하므로, 메시지를 읽고 쿼리를 수정해
    재시도할 수 있다.
    """
    return _executor.execute(query)["markdown"]


@tool
def list_tables() -> str:
    """데이터베이스 내 테이블 목록을 반환한다."""
    return _executor.list_tables()["markdown"]


@tool
def get_schema(table: str) -> str:
    """지정 테이블의 CREATE TABLE DDL을 반환한다."""
    return _executor.get_schema(table)["markdown"]


SQL_TOOLS = [execute_sql, list_tables, get_schema]
SQL_TOOLS_BY_NAME = {t.name: t for t in SQL_TOOLS}
