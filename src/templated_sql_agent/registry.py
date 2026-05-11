"""SQL 템플릿 레지스트리.

도메인 무지: 어떤 SQL 템플릿이든 등록할 수 있고, 등록 검증과 조회 인터페이스만
제공한다. 실제 도메인 템플릿은 templates.py에서 정의한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


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
        """템플릿을 레지스트리에 등록한다."""
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
