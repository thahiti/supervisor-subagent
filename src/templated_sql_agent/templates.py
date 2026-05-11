"""ecommerce.db 도메인 SQL 템플릿 카탈로그.

모듈 import 시 부수효과로 template_registry에 모든 템플릿이 등록된다.
다른 도메인을 추가하려면 이 파일과 동일한 형식의 새 모듈을 작성하고,
패키지 __init__.py에서 import하면 된다.
"""

from __future__ import annotations

from src.templated_sql_agent.registry import (
    SqlTemplate,
    TemplateVariable,
    template_registry,
)

# 부서별 평균 급여
template_registry.register(SqlTemplate(
    id="dept_avg_salary",
    intent="특정 부서의 평균 급여 조회",
    sql=(
        "SELECT d.name AS department, AVG(e.salary) AS avg_salary, "
        "COUNT(e.id) AS headcount "
        "FROM employees e "
        "JOIN departments d ON e.dept_id = d.id "
        "WHERE d.id = :dept_id "
        "GROUP BY d.name"
    ),
    variables=(
        TemplateVariable(
            name="dept_id",
            description="조회 대상 부서의 id",
            sql_type="int",
            lookup_sql="SELECT id, name, location FROM departments ORDER BY name",
        ),
    ),
))

# 특정 제품 재고
template_registry.register(SqlTemplate(
    id="product_stock",
    intent="특정 제품의 현재 재고 조회",
    sql=(
        "SELECT id, name, category, price, stock "
        "FROM products WHERE id = :product_id"
    ),
    variables=(
        TemplateVariable(
            name="product_id",
            description="조회 대상 제품의 id",
            sql_type="int",
            lookup_sql=(
                "SELECT id, name, category FROM products "
                "ORDER BY category, name"
            ),
        ),
    ),
))

# 카테고리별 매출 상위 N개
template_registry.register(SqlTemplate(
    id="category_top_n_revenue",
    intent="특정 카테고리의 매출 상위 N개 제품 조회",
    sql=(
        "SELECT p.name, SUM(oi.quantity * oi.unit_price) AS revenue "
        "FROM order_items oi "
        "JOIN products p ON oi.product_id = p.id "
        "WHERE p.category = :category "
        "GROUP BY p.name "
        "ORDER BY revenue DESC "
        "LIMIT :n"
    ),
    variables=(
        TemplateVariable(
            name="category",
            description="조회 대상 제품 카테고리명",
            sql_type="text",
            lookup_sql="SELECT DISTINCT category FROM products ORDER BY category",
        ),
        TemplateVariable(
            name="n",
            description="조회할 상위 제품 개수",
            sql_type="int",
        ),
    ),
))

# 특정 고객의 주문 내역
template_registry.register(SqlTemplate(
    id="customer_orders",
    intent="특정 고객의 주문 내역 조회",
    sql=(
        "SELECT id, order_date, status, total_amount "
        "FROM orders WHERE customer_id = :customer_id "
        "ORDER BY order_date DESC"
    ),
    variables=(
        TemplateVariable(
            name="customer_id",
            description="조회 대상 고객의 id",
            sql_type="int",
            lookup_sql="SELECT id, name, city FROM customers ORDER BY name",
        ),
    ),
))

# 특정 월의 특정 상태 주문 수
template_registry.register(SqlTemplate(
    id="monthly_order_count",
    intent="특정 월의 특정 상태 주문 건수 집계",
    sql=(
        "SELECT COUNT(*) AS order_count "
        "FROM orders "
        "WHERE strftime('%Y-%m', order_date) = :year_month "
        "AND status = :status"
    ),
    variables=(
        TemplateVariable(
            name="year_month",
            description="조회 대상 월(YYYY-MM 형식)",
            sql_type="date",
        ),
        TemplateVariable(
            name="status",
            description="조회 대상 주문 상태",
            sql_type="text",
            lookup_sql="SELECT DISTINCT status FROM orders ORDER BY status",
        ),
    ),
))
