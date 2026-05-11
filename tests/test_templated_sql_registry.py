"""TemplateRegistry 단위 테스트."""

from __future__ import annotations

import pytest

from src.templated_sql_agent.registry import (
    SqlTemplate,
    TemplateRegistry,
    TemplateVariable,
)


def _make_template(template_id: str = "t1") -> SqlTemplate:
    return SqlTemplate(
        id=template_id,
        intent="테스트 의도",
        sql="SELECT * FROM t WHERE x = :x",
        variables=(
            TemplateVariable(
                name="x",
                description="테스트 변수",
                sql_type="int",
            ),
        ),
    )


class TestBasicRegistration:
    def test_register_and_get(self) -> None:
        reg = TemplateRegistry()
        t = _make_template()
        reg.register(t)
        assert reg.get("t1") is t

    def test_get_missing_returns_none(self) -> None:
        reg = TemplateRegistry()
        assert reg.get("nope") is None

    def test_templates_preserves_order(self) -> None:
        reg = TemplateRegistry()
        reg.register(_make_template("a"))
        reg.register(_make_template("b"))
        reg.register(_make_template("c"))
        assert [t.id for t in reg.templates] == ["a", "b", "c"]

    def test_templates_returns_defensive_copy(self) -> None:
        reg = TemplateRegistry()
        reg.register(_make_template("a"))
        got = reg.templates
        got.clear()
        assert [t.id for t in reg.templates] == ["a"]
