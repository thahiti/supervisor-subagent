"""Text-to-SQL few-shot 예시.

난이도를 점진적으로 올린 10개 예시. 모두 SQLite 방언으로 작성되어 있다.
예시 10번은 PostgreSQL의 DATE_TRUNC/INTERVAL 대신 SQLite의 date()
modifier 체이닝을 사용한다.
"""

FEW_SHOTS: list[tuple[str, str]] = [
    (
        "모든 직원의 이름과 이메일을 보여줘",
        "SELECT name, email FROM employees;",
    ),
    (
        "연봉이 5천만원 이상인 직원은?",
        "SELECT name, salary FROM employees WHERE salary >= 50000000;",
    ),
    (
        "부서별 평균 급여를 알려줘",
        "SELECT d.name, AVG(e.salary) AS avg_salary "
        "FROM employees e "
        "JOIN departments d ON e.dept_id = d.id "
        "GROUP BY d.name;",
    ),
    (
        "매출 상위 5개 제품은?",
        "SELECT p.name, SUM(oi.quantity * oi.unit_price) AS revenue "
        "FROM order_items oi "
        "JOIN products p ON oi.product_id = p.id "
        "GROUP BY p.name "
        "ORDER BY revenue DESC "
        "LIMIT 5;",
    ),
    (
        "2025년 3월에 들어온 주문 건수는?",
        "SELECT COUNT(*) AS order_count "
        "FROM orders "
        "WHERE order_date BETWEEN '2025-03-01' AND '2025-03-31';",
    ),
    (
        "서울에 사는 고객이 주문한 총 금액은?",
        "SELECT SUM(o.total_amount) AS total "
        "FROM orders o "
        "JOIN customers c ON o.customer_id = c.id "
        "WHERE c.city = '서울';",
    ),
    (
        "회사 평균보다 급여가 높은 직원 목록",
        "SELECT name, salary FROM employees "
        "WHERE salary > (SELECT AVG(salary) FROM employees);",
    ),
    (
        "주문을 10건 이상 한 고객은?",
        "SELECT c.name, COUNT(o.id) AS order_count "
        "FROM customers c "
        "JOIN orders o ON c.id = o.customer_id "
        "GROUP BY c.name "
        "HAVING COUNT(o.id) >= 10;",
    ),
    (
        "담당 매니저가 배정되지 않은 직원은?",
        "SELECT name FROM employees WHERE manager_id IS NULL;",
    ),
    (
        "재고가 100개 미만이면서 지난달 판매량이 50개 이상인 제품을 판매량 순으로 보여줘",
        "SELECT p.name, p.stock, SUM(oi.quantity) AS sold "
        "FROM products p "
        "JOIN order_items oi ON p.id = oi.product_id "
        "JOIN orders o ON oi.order_id = o.id "
        "WHERE p.stock < 100 "
        "  AND o.order_date >= date('now', 'start of month', '-1 month') "
        "  AND o.order_date <  date('now', 'start of month') "
        "GROUP BY p.name, p.stock "
        "HAVING SUM(oi.quantity) >= 50 "
        "ORDER BY sold DESC;",
    ),
]


def format_few_shots() -> str:
    """Few-shot 예시들을 프롬프트 포맷 문자열로 직렬화한다."""
    blocks: list[str] = []
    for i, (nl, sql) in enumerate(FEW_SHOTS, start=1):
        blocks.append(f"예시 {i}:\n질문: {nl}\nSQL:\n```sql\n{sql}\n```")
    return "\n\n".join(blocks)
