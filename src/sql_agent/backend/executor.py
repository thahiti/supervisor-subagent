"""도메인 무지의 SQLite 실행기.

Frontend 레이어가 어떤 도메인을 다루든 이 클래스는 영향을 받지 않는다.
오직 SQL 문자열을 받아 안전하게 실행하고 결과를 구조화해 반환한다.

Defense-in-depth:
    1. safety.validate_select_only — 키워드/문법 레벨 가드
    2. SQLite URI mode=ro — 커넥션 레벨 read-only 강제
    3. busy_timeout / query timeout — 무한 대기 방지
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, TypedDict

from src.sql_agent.backend.formatter import to_markdown_table
from src.sql_agent.backend.safety import (
    UnsafeSqlError,
    inject_limit_if_missing,
    validate_select_only,
)
from src.logging import get_logger

logger = get_logger("sql.backend")

DEFAULT_ROW_LIMIT = 100
DEFAULT_BUSY_TIMEOUT_MS = 3_000
DEFAULT_QUERY_TIMEOUT_S = 5.0


class ExecutionResult(TypedDict):
    """SQL 실행 결과를 표현하는 구조체."""

    ok: bool
    columns: list[str]
    rows: list[tuple[Any, ...]]
    markdown: str
    error: str | None


class SqlExecutor:
    """SQLite 쿼리 실행기 (read-only).

    Attributes:
        db_path: 대상 SQLite 파일 경로.
        row_limit: 자동 주입할 LIMIT 값.
        auto_seed: DB 파일이 없을 때 자동 시드 여부.
        query_timeout_s: 단일 쿼리 최대 실행 시간(초).
    """

    def __init__(
        self,
        db_path: Path,
        *,
        row_limit: int = DEFAULT_ROW_LIMIT,
        auto_seed: bool = True,
        query_timeout_s: float = DEFAULT_QUERY_TIMEOUT_S,
    ) -> None:
        self._db_path = Path(db_path)
        self._row_limit = row_limit
        self._auto_seed = auto_seed
        self._query_timeout_s = query_timeout_s

    @property
    def db_path(self) -> Path:
        return self._db_path

    def execute(self, query: str) -> ExecutionResult:
        """쿼리를 검증하고 실행하여 결과를 반환한다.

        Args:
            query: 실행할 SQL 쿼리 문자열.

        Returns:
            ExecutionResult. 실패 시 ok=False와 error 메시지를 포함한다.
        """
        try:
            validate_select_only(query)
        except UnsafeSqlError as exc:
            logger.warning("SQL 안전성 검증 실패: %s", exc)
            return _error_result(str(exc))

        safe_query = inject_limit_if_missing(query, self._row_limit)
        return self._run_query(safe_query)

    def list_tables(self) -> ExecutionResult:
        """DB 내 사용자 테이블 목록을 반환한다.

        Returns:
            ExecutionResult. 단일 컬럼 'name'에 테이블명이 담긴다.
        """
        return self._run_query(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name",
        )

    def get_schema(self, table: str) -> ExecutionResult:
        """지정 테이블의 CREATE 문(DDL)을 반환한다.

        Args:
            table: 스키마를 조회할 테이블명.

        Returns:
            ExecutionResult. 'sql' 컬럼에 DDL 문자열이 담긴다.
            테이블이 없으면 ok=False.
        """
        if not _is_safe_identifier(table):
            return _error_result(f"잘못된 테이블명: {table}")

        result = self._run_query(
            "SELECT sql FROM sqlite_master "
            f"WHERE type='table' AND name='{table}'",
        )
        if result["ok"] and not result["rows"]:
            return _error_result(f"테이블을 찾을 수 없음: {table}")
        return result

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Read-only 모드로 DB에 연결한다."""
        self._ensure_db_exists()
        uri = f"file:{self._db_path}?mode=ro"
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=self._query_timeout_s,
            isolation_level=None,
        )
        try:
            conn.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
            yield conn
        finally:
            conn.close()

    def _run_query(self, query: str) -> ExecutionResult:
        try:
            with self._connect() as conn:
                cursor = conn.execute(query)
                rows = cursor.fetchall()
                columns = [d[0] for d in cursor.description] if cursor.description else []
        except sqlite3.Error as exc:
            logger.warning("SQL 실행 오류: %s | query=%s", exc, query[:120])
            return _error_result(f"SQLite 오류: {exc}")
        except FileNotFoundError as exc:
            logger.warning("DB 파일 없음: %s", exc)
            return _error_result(str(exc))

        markdown = to_markdown_table(columns, rows)
        logger.info(
            "SQL 실행 성공: rows=%d, query=%s", len(rows), query[:120],
        )
        return ExecutionResult(
            ok=True,
            columns=columns,
            rows=rows,
            markdown=markdown,
            error=None,
        )

    def _ensure_db_exists(self) -> None:
        if self._db_path.exists():
            return
        if not self._auto_seed:
            raise FileNotFoundError(f"DB 파일 없음: {self._db_path}")
        logger.info("DB 파일 없음 → 자동 시드: %s", self._db_path)
        from res.sample_db.seed import build_database

        build_database(self._db_path)


def _is_safe_identifier(name: str) -> bool:
    """SQL 식별자 화이트리스트 검증 (영숫자/언더스코어만)."""
    return bool(name) and all(c.isalnum() or c == "_" for c in name)


def _error_result(message: str) -> ExecutionResult:
    return ExecutionResult(
        ok=False,
        columns=[],
        rows=[],
        markdown=f"ERROR: {message}",
        error=message,
    )
