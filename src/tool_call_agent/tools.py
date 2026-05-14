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
