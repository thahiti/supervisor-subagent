"""SQL 안전성 검증 모듈.

도메인 무지: 어떤 스키마든 적용 가능한 일반적인 안전 규칙만 다룬다.
"""

from __future__ import annotations

import re

_ALLOWED_PREFIX_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

_FORBIDDEN_KEYWORDS: tuple[str, ...] = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "REPLACE", "TRUNCATE", "ATTACH", "DETACH", "PRAGMA", "VACUUM",
)

_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)


class UnsafeSqlError(ValueError):
    """안전하지 않은 SQL이 감지되었을 때 발생."""


def validate_select_only(query: str) -> None:
    """SELECT/WITH로 시작하는 단일 쿼리만 허용한다.

    Args:
        query: 검증할 SQL 문자열.

    Raises:
        UnsafeSqlError: 허용되지 않은 쿼리인 경우.
    """
    stripped = query.strip().rstrip(";").strip()
    if not stripped:
        raise UnsafeSqlError("빈 쿼리는 허용되지 않습니다.")

    if not _ALLOWED_PREFIX_RE.match(stripped):
        raise UnsafeSqlError(
            "SELECT 또는 WITH로 시작하는 읽기 전용 쿼리만 허용됩니다.",
        )

    if ";" in stripped:
        raise UnsafeSqlError("다중 문장(;)은 허용되지 않습니다.")

    upper_no_strings = _strip_string_literals(stripped).upper()
    for keyword in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper_no_strings):
            raise UnsafeSqlError(
                f"금지된 키워드가 포함되어 있습니다: {keyword}",
            )


def inject_limit_if_missing(query: str, row_limit: int) -> str:
    """LIMIT이 없으면 자동으로 추가한다.

    Args:
        query: SQL 쿼리.
        row_limit: 적용할 LIMIT 값.

    Returns:
        LIMIT이 보장된 쿼리.
    """
    stripped = query.strip().rstrip(";").strip()
    if _LIMIT_RE.search(_strip_string_literals(stripped)):
        return stripped
    return f"{stripped} LIMIT {row_limit}"


def _strip_string_literals(query: str) -> str:
    """문자열 리터럴 안의 키워드가 검증을 오염시키지 않도록 제거한다."""
    return re.sub(r"'[^']*'", "''", query)
