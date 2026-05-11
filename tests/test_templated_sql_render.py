"""render 단위 테스트."""

from __future__ import annotations

import pytest

from src.templated_sql_agent.registry import SqlTemplate, TemplateVariable
from src.templated_sql_agent.render import TemplateRenderError, render


def _t(*vars_: TemplateVariable, sql: str | None = None) -> SqlTemplate:
    placeholder_part = " AND ".join(f"{v.name} = :{v.name}" for v in vars_)
    return SqlTemplate(
        id="t",
        intent="i",
        sql=sql or f"SELECT * FROM x WHERE {placeholder_part}",
        variables=vars_,
    )


class TestRenderHappy:
    def test_int_coercion(self) -> None:
        t = _t(TemplateVariable(name="id", description="d", sql_type="int"))
        sql, params = render(t, {"id": "42"})
        assert ":id" in sql
        assert params == {"id": 42}

    def test_int_already_int(self) -> None:
        t = _t(TemplateVariable(name="id", description="d", sql_type="int"))
        sql, params = render(t, {"id": 5})
        assert params == {"id": 5}

    def test_text_strip(self) -> None:
        t = _t(TemplateVariable(name="c", description="d", sql_type="text"))
        _, params = render(t, {"c": "  hello  "})
        assert params == {"c": "hello"}

    def test_date_full(self) -> None:
        t = _t(TemplateVariable(name="d", description="d", sql_type="date"))
        _, params = render(t, {"d": "2026-05-11"})
        assert params == {"d": "2026-05-11"}

    def test_date_month_only(self) -> None:
        t = _t(TemplateVariable(name="d", description="d", sql_type="date"))
        _, params = render(t, {"d": "2026-05"})
        assert params == {"d": "2026-05"}

    def test_multiple_variables(self) -> None:
        t = _t(
            TemplateVariable(name="a", description="d", sql_type="int"),
            TemplateVariable(name="b", description="d", sql_type="text"),
        )
        sql, params = render(t, {"a": 1, "b": "x"})
        assert params == {"a": 1, "b": "x"}


class TestRenderErrors:
    def test_missing_arg(self) -> None:
        t = _t(TemplateVariable(name="id", description="d", sql_type="int"))
        with pytest.raises(TemplateRenderError, match="누락"):
            render(t, {})

    def test_int_cast_failure(self) -> None:
        t = _t(TemplateVariable(name="id", description="d", sql_type="int"))
        with pytest.raises(TemplateRenderError, match="int"):
            render(t, {"id": "abc"})

    def test_text_empty_after_strip(self) -> None:
        t = _t(TemplateVariable(name="c", description="d", sql_type="text"))
        with pytest.raises(TemplateRenderError, match="text"):
            render(t, {"c": "   "})

    def test_date_wrong_separator(self) -> None:
        t = _t(TemplateVariable(name="d", description="d", sql_type="date"))
        with pytest.raises(TemplateRenderError, match="date"):
            render(t, {"d": "2026/05/11"})

    def test_date_natural_language(self) -> None:
        t = _t(TemplateVariable(name="d", description="d", sql_type="date"))
        with pytest.raises(TemplateRenderError, match="date"):
            render(t, {"d": "오늘"})
