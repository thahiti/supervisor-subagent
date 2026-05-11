"""SQL 템플릿 변수 검증 + 타입 coercion + sqlite3 named-param 바인딩 생성."""

from __future__ import annotations

import re
from typing import Any

from src.templated_sql_agent.registry import SqlTemplate, TemplateVariable

_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


class TemplateRenderError(ValueError):
    """렌더링 단계에서 변수 누락·타입 불일치 등의 사유로 실패했을 때."""


def render(
    template: SqlTemplate,
    args: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """args를 검증·정제해 (sql, params) 튜플을 반환한다.

    Args:
        template: 렌더링 대상 SqlTemplate.
        args: 변수 이름 → 값 매핑. 일반적으로 LLM이 추출한 값.

    Returns:
        (sql_with_named_placeholders, params_dict). sqlite3.execute(sql, params)
        호출에 그대로 사용 가능.

    Raises:
        TemplateRenderError: 변수 누락 또는 타입 불일치.
    """
    params: dict[str, Any] = {}
    for var in template.variables:
        if var.name not in args:
            raise TemplateRenderError(f"누락된 변수: {var.name}")
        params[var.name] = _coerce(args[var.name], var)
    return template.sql, params


def _coerce(value: Any, var: TemplateVariable) -> Any:
    """variable.sql_type에 따른 coercion + 형식 검증."""
    if var.sql_type == "int":
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise TemplateRenderError(
                f"변수 '{var.name}'은(는) int여야 합니다. 입력값: {value!r}"
            ) from exc

    if var.sql_type == "text":
        text = str(value).strip()
        if not text:
            raise TemplateRenderError(
                f"변수 '{var.name}'(text)은(는) 비어 있을 수 없습니다."
            )
        return text

    if var.sql_type == "date":
        text = str(value).strip()
        if not _DATE_RE.match(text):
            raise TemplateRenderError(
                f"변수 '{var.name}'은(는) YYYY-MM 또는 YYYY-MM-DD 형식의 date "
                f"여야 합니다. 입력값: {value!r}"
            )
        return text

    raise TemplateRenderError(f"알 수 없는 sql_type: {var.sql_type}")
