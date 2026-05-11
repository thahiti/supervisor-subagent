"""SQL 템플릿 레지스트리.

도메인 무지: 어떤 SQL 템플릿이든 등록할 수 있고, 등록 검증과 조회 인터페이스만
제공한다. 실제 도메인 템플릿은 templates.py에서 정의한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from src.sql_agent.backend.safety import UnsafeSqlError, validate_select_only


@dataclass(frozen=True)
class TemplateVariable:
    """SQL 템플릿의 단일 변수 정의.

    Attributes:
        name: SQL named placeholder 키 (예: "store_id").
        description: 사용자/LLM 양쪽에 노출되는 의미.
        sql_type: coercion + 안전 검증용 타입.
            - "int": 정수 ID 또는 수량
            - "text": 카테고리/도시명/주문 상태 같은 문자열 값
            - "date": YYYY-MM-DD 또는 YYYY-MM 형식 문자열
        lookup_sql: 후보값 조회용 SELECT (정적 등록).
            None이면 후보값 조회 불가.
    """

    name: str
    description: str
    sql_type: Literal["int", "text", "date"]
    lookup_sql: str | None = None


@dataclass(frozen=True)
class SqlTemplate:
    """단일 SQL 템플릿 정의.

    Attributes:
        id: 라우팅·로깅 키 (예: "product_stock").
        intent: 라우터 description/카탈로그 표시용 한 줄.
        sql: :name 형식 named placeholder만 사용.
        variables: 템플릿에 등장하는 모든 변수 (튜플로 hashable 보장).
    """

    id: str
    intent: str
    sql: str
    variables: tuple[TemplateVariable, ...]


class TemplateRegistry:
    """SQL 템플릿 등록·조회 레지스트리."""

    def __init__(self) -> None:
        self._templates: list[SqlTemplate] = []
        self._by_id: dict[str, SqlTemplate] = {}

    def register(self, template: SqlTemplate) -> None:
        """템플릿을 레지스트리에 등록한다.

        검증 실패 시 ValueError를 즉시 발생시킨다. 검증 항목:
            1. id 중복 금지
            2. sql의 :name placeholder 집합과 variables의 name 집합이 정확히 일치
            3. 각 lookup_sql은 SELECT-only (백엔드 safety 재활용)
        """
        if template.id in self._by_id:
            raise ValueError(f"중복 템플릿 id: {template.id}")

        placeholders = set(re.findall(r":(\w+)", template.sql))
        var_names = {v.name for v in template.variables}
        if placeholders != var_names:
            raise ValueError(
                f"템플릿 '{template.id}': sql placeholder {sorted(placeholders)} "
                f"≠ variables {sorted(var_names)}"
            )

        for v in template.variables:
            if v.lookup_sql is not None:
                try:
                    validate_select_only(v.lookup_sql)
                except UnsafeSqlError as exc:
                    raise ValueError(
                        f"템플릿 '{template.id}' 변수 '{v.name}'의 lookup_sql은 "
                        f"SELECT-only여야 합니다: {exc}"
                    ) from exc

        self._templates.append(template)
        self._by_id[template.id] = template

    @property
    def templates(self) -> list[SqlTemplate]:
        """등록된 모든 템플릿을 등록 순서대로 반환 (방어 복사)."""
        return list(self._templates)

    def get(self, template_id: str) -> SqlTemplate | None:
        """id로 템플릿을 조회. 없으면 None."""
        return self._by_id.get(template_id)


template_registry = TemplateRegistry()
