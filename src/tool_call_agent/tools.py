"""tool_call 에이전트의 v1 도구 함수와 내부 헬퍼.

도구 함수는 사용자의 정보 조회 요청을 만족시키기 위해 LLM이 호출한다.
각 함수는 자체 sqlite 커넥션을 read-only 모드로 직접 관리하며,
모듈 레벨 싱글톤을 두지 않는다.
"""

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
