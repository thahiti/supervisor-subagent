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


class TestRegistrationValidation:
    def test_rejects_duplicate_id(self) -> None:
        reg = TemplateRegistry()
        reg.register(_make_template("dup"))
        with pytest.raises(ValueError, match="중복"):
            reg.register(_make_template("dup"))

    def test_rejects_placeholder_mismatch_missing_var(self) -> None:
        reg = TemplateRegistry()
        bad = SqlTemplate(
            id="bad",
            intent="i",
            sql="SELECT * FROM t WHERE x = :x AND y = :y",
            variables=(
                TemplateVariable(name="x", description="d", sql_type="int"),
            ),
        )
        with pytest.raises(ValueError, match="placeholder"):
            reg.register(bad)

    def test_rejects_placeholder_mismatch_extra_var(self) -> None:
        reg = TemplateRegistry()
        bad = SqlTemplate(
            id="bad",
            intent="i",
            sql="SELECT * FROM t WHERE x = :x",
            variables=(
                TemplateVariable(name="x", description="d", sql_type="int"),
                TemplateVariable(name="y", description="d", sql_type="int"),
            ),
        )
        with pytest.raises(ValueError, match="placeholder"):
            reg.register(bad)

    def test_rejects_non_select_lookup_sql(self) -> None:
        reg = TemplateRegistry()
        bad = SqlTemplate(
            id="bad",
            intent="i",
            sql="SELECT * FROM t WHERE x = :x",
            variables=(
                TemplateVariable(
                    name="x",
                    description="d",
                    sql_type="int",
                    lookup_sql="DELETE FROM t",
                ),
            ),
        )
        with pytest.raises(ValueError, match="SELECT"):
            reg.register(bad)

    def test_accepts_select_lookup_sql(self) -> None:
        reg = TemplateRegistry()
        ok = SqlTemplate(
            id="ok",
            intent="i",
            sql="SELECT * FROM t WHERE x = :x",
            variables=(
                TemplateVariable(
                    name="x",
                    description="d",
                    sql_type="int",
                    lookup_sql="SELECT id, name FROM t ORDER BY name",
                ),
            ),
        )
        reg.register(ok)
        assert reg.get("ok") is ok

    def test_validation_failure_does_not_register(self) -> None:
        reg = TemplateRegistry()
        bad = SqlTemplate(
            id="bad",
            intent="i",
            sql="SELECT * FROM t WHERE x = :x AND y = :y",
            variables=(
                TemplateVariable(name="x", description="d", sql_type="int"),
            ),
        )
        with pytest.raises(ValueError):
            reg.register(bad)
        assert reg.get("bad") is None
        assert reg.templates == []


class TestBuilders:
    def _populated(self) -> TemplateRegistry:
        reg = TemplateRegistry()
        reg.register(SqlTemplate(
            id="t1",
            intent="첫 번째 의도",
            sql="SELECT * FROM t WHERE x = :x",
            variables=(
                TemplateVariable(
                    name="x",
                    description="x 설명",
                    sql_type="int",
                    lookup_sql="SELECT id, name FROM t ORDER BY name",
                ),
            ),
        ))
        reg.register(SqlTemplate(
            id="t2",
            intent="두 번째 의도",
            sql="SELECT * FROM t WHERE y = :y",
            variables=(
                TemplateVariable(
                    name="y",
                    description="y 설명",
                    sql_type="text",
                ),
            ),
        ))
        return reg

    def test_router_description_contains_header_and_intents(self) -> None:
        desc = self._populated().build_router_description()
        assert "사전 정의된 SQL 템플릿" in desc
        assert "후보값" in desc
        assert "첫 번째 의도" in desc
        assert "두 번째 의도" in desc

    def test_router_description_empty_registry(self) -> None:
        desc = TemplateRegistry().build_router_description()
        # 빈 레지스트리여도 헤더는 있고 의도 항목만 비어 있다.
        assert "사전 정의된 SQL 템플릿" in desc

    def test_catalog_for_llm_includes_template_id_and_variables(self) -> None:
        cat = self._populated().build_catalog_for_llm()
        assert "template_id: t1" in cat
        assert "template_id: t2" in cat
        assert "x (int)" in cat
        assert "y (text)" in cat
        assert "x 설명" in cat
        assert "y 설명" in cat

    def test_catalog_indicates_lookup_availability(self) -> None:
        cat = self._populated().build_catalog_for_llm()
        # x는 lookup_sql이 있고, y는 없다.
        assert "후보값 조회 가능" in cat
        assert "후보값 조회 불가" in cat

    def test_catalog_does_not_leak_lookup_sql_body(self) -> None:
        """lookup_sql 본문은 LLM에 노출되지 않아야 한다."""
        cat = self._populated().build_catalog_for_llm()
        assert "ORDER BY name" not in cat
        assert "SELECT id, name FROM t" not in cat
