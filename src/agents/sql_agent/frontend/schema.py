"""ecommerce 도메인 스키마 DDL 상수.

Frontend 에이전트가 LLM 시스템 프롬프트에 주입하는 도메인 지식.
Backend는 이 내용을 전혀 모른다 — 다른 도메인을 추가하려면 이 파일과
few_shots.py, prompt.py만 새로 작성하면 된다.
"""

SCHEMA_DDL = """\
CREATE TABLE departments (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,         -- 부서명 (예: '엔지니어링', '영업')
    location TEXT NOT NULL      -- 위치 (예: '서울', '부산')
);

CREATE TABLE employees (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,         -- 직원명
    email TEXT NOT NULL UNIQUE,
    salary INTEGER NOT NULL,    -- 연봉 (원 단위)
    dept_id INTEGER NOT NULL,   -- departments.id
    manager_id INTEGER,         -- employees.id (상위 매니저, NULL 가능)
    hire_date TEXT NOT NULL,    -- 'YYYY-MM-DD'
    FOREIGN KEY (dept_id) REFERENCES departments(id),
    FOREIGN KEY (manager_id) REFERENCES employees(id)
);

CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    city TEXT NOT NULL,         -- 도시명 (예: '서울', '도쿄', '뉴욕')
    country TEXT NOT NULL,      -- 국가명
    signup_date TEXT NOT NULL   -- 'YYYY-MM-DD'
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,     -- 카테고리 (예: '전자기기', '의류', '도서')
    price INTEGER NOT NULL,     -- 가격 (원 단위)
    stock INTEGER NOT NULL      -- 재고 수량
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date TEXT NOT NULL,   -- 'YYYY-MM-DD'
    status TEXT NOT NULL,       -- 'pending'|'paid'|'shipped'|'delivered'|'cancelled'
    total_amount INTEGER NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price INTEGER NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);
"""
