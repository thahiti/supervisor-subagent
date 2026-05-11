"""templates.py 등록 검증.

import 시 등록 검증이 통과하고 5개 템플릿이 모두 들어가는지 확인한다.
"""

from __future__ import annotations

from src.templated_sql_agent.registry import template_registry
import src.templated_sql_agent.templates  # noqa: F401 - 등록 트리거


EXPECTED_IDS = {
    "dept_avg_salary",
    "product_stock",
    "category_top_n_revenue",
    "customer_orders",
    "monthly_order_count",
}


class TestTemplatesRegistered:
    def test_all_expected_ids_present(self) -> None:
        ids = {t.id for t in template_registry.templates}
        assert EXPECTED_IDS.issubset(ids)

    def test_each_has_nonempty_intent_and_sql(self) -> None:
        for t in template_registry.templates:
            if t.id not in EXPECTED_IDS:
                continue
            assert t.intent.strip()
            assert t.sql.strip().lower().startswith("select")
            assert len(t.variables) >= 1

    def test_lookup_variables_have_select_only_sql(self) -> None:
        # 등록 검증이 lookup_sql을 SELECT-only로 강제하지만,
        # 추가로 명시 검증한다.
        for t in template_registry.templates:
            for v in t.variables:
                if v.lookup_sql is None:
                    continue
                normalized = v.lookup_sql.strip().lower()
                assert normalized.startswith("select") or normalized.startswith("with")
