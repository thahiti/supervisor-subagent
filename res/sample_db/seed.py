"""결정적 ecommerce 샘플 DB 시드 스크립트.

약 50,000행 규모의 SQLite 데이터베이스를 생성한다.
`random.seed(42)`로 고정되어 재현 가능하다.

사용법:
    python -m res.sample_db.seed                # 기본 경로
    python -m res.sample_db.seed --force        # 기존 파일 덮어쓰기
    python -m res.sample_db.seed --path x.db    # 경로 지정
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent / "ecommerce.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

N_DEPARTMENTS = 10
N_EMPLOYEES = 500
N_CUSTOMERS = 5_000
N_PRODUCTS = 200
N_ORDERS = 15_000
ITEMS_PER_ORDER_MIN = 1
ITEMS_PER_ORDER_MAX = 4

DEPARTMENTS: list[tuple[str, str]] = [
    ("엔지니어링", "서울"),
    ("영업", "서울"),
    ("마케팅", "부산"),
    ("인사", "서울"),
    ("재무", "서울"),
    ("고객지원", "부산"),
    ("운영", "인천"),
    ("데이터분석", "서울"),
    ("디자인", "서울"),
    ("법무", "서울"),
]

KR_FIRST_NAMES = [
    "민준", "서연", "지훈", "하은", "도윤", "수아", "예준", "지우", "주원", "지민",
    "현우", "소율", "건우", "서윤", "시우", "하윤", "민재", "채원", "준호", "다은",
    "우진", "유나", "성호", "예린", "재현", "아린", "태민", "수빈", "지후", "나연",
]

KR_LAST_NAMES = [
    "김", "이", "박", "최", "정", "강", "조", "윤", "장", "임",
    "한", "오", "서", "신", "권", "황", "안", "송", "류", "홍",
]

EN_FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Barbara", "William", "Susan", "Richard", "Jessica", "Thomas", "Sarah",
    "Charles", "Karen", "Daniel", "Nancy",
]

EN_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin",
]

CITIES: list[tuple[str, str]] = [
    ("서울", "대한민국"),
    ("부산", "대한민국"),
    ("인천", "대한민국"),
    ("대구", "대한민국"),
    ("대전", "대한민국"),
    ("광주", "대한민국"),
    ("도쿄", "일본"),
    ("오사카", "일본"),
    ("베이징", "중국"),
    ("상하이", "중국"),
    ("뉴욕", "미국"),
    ("로스앤젤레스", "미국"),
    ("샌프란시스코", "미국"),
    ("런던", "영국"),
    ("파리", "프랑스"),
    ("베를린", "독일"),
    ("시드니", "호주"),
    ("토론토", "캐나다"),
    ("싱가포르", "싱가포르"),
    ("방콕", "태국"),
]

PRODUCT_CATEGORIES: list[tuple[str, list[str]]] = [
    ("전자기기", ["노트북", "스마트폰", "태블릿", "이어폰", "스마트워치", "모니터", "키보드", "마우스"]),
    ("의류", ["티셔츠", "청바지", "원피스", "재킷", "코트", "스웨터", "운동복"]),
    ("도서", ["소설", "에세이", "자기계발서", "전문서적", "만화", "아동도서"]),
    ("가구", ["책상", "의자", "소파", "침대", "옷장", "책장"]),
    ("식품", ["커피", "차", "과자", "초콜릿", "견과류", "건강식품"]),
    ("뷰티", ["스킨케어", "메이크업", "향수", "바디케어", "헤어케어"]),
    ("스포츠", ["러닝화", "요가매트", "덤벨", "자전거", "등산용품"]),
    ("주방용품", ["냄비", "프라이팬", "식기세트", "칼", "도마"]),
    ("완구", ["레고", "퍼즐", "보드게임", "인형", "RC카"]),
    ("반려동물", ["사료", "간식", "장난감", "목줄", "집"]),
]

ORDER_STATUSES = ["pending", "paid", "shipped", "delivered", "cancelled"]
ORDER_STATUS_WEIGHTS = [5, 10, 15, 65, 5]

DATE_START = date(2023, 1, 1)
DATE_END = date(2025, 4, 30)


def _generate_departments() -> list[tuple[int, str, str]]:
    return [(i + 1, name, loc) for i, (name, loc) in enumerate(DEPARTMENTS[:N_DEPARTMENTS])]


def _random_korean_name(rng: random.Random) -> str:
    return rng.choice(KR_LAST_NAMES) + rng.choice(KR_FIRST_NAMES)


def _random_english_name(rng: random.Random) -> str:
    return f"{rng.choice(EN_FIRST_NAMES)} {rng.choice(EN_LAST_NAMES)}"


def _random_name(rng: random.Random) -> str:
    return _random_korean_name(rng) if rng.random() < 0.7 else _random_english_name(rng)


def _random_date(rng: random.Random, start: date, end: date) -> date:
    delta_days = (end - start).days
    return start + timedelta(days=rng.randint(0, delta_days))


def _generate_employees(rng: random.Random) -> list[tuple]:
    rows: list[tuple] = []
    for i in range(1, N_EMPLOYEES + 1):
        name = _random_name(rng)
        email = f"emp{i:04d}@company.example"
        salary = int(rng.lognormvariate(mu=17.7, sigma=0.35))
        salary = max(30_000_000, min(salary, 200_000_000))
        dept_id = rng.randint(1, N_DEPARTMENTS)
        if i <= N_DEPARTMENTS:
            manager_id = None
        else:
            manager_id = rng.randint(1, min(i - 1, N_EMPLOYEES // 5))
            if rng.random() < 0.05:
                manager_id = None
        hire_date = _random_date(rng, date(2018, 1, 1), date(2025, 3, 31)).isoformat()
        rows.append((i, name, email, salary, dept_id, manager_id, hire_date))
    return rows


def _generate_customers(rng: random.Random) -> list[tuple]:
    rows: list[tuple] = []
    for i in range(1, N_CUSTOMERS + 1):
        name = _random_name(rng)
        email = f"cust{i:05d}@mail.example"
        city, country = rng.choice(CITIES)
        signup = _random_date(rng, DATE_START, DATE_END).isoformat()
        rows.append((i, name, email, city, country, signup))
    return rows


def _generate_products(rng: random.Random) -> list[tuple]:
    rows: list[tuple] = []
    pid = 1
    products_per_category = N_PRODUCTS // len(PRODUCT_CATEGORIES)
    for category, names in PRODUCT_CATEGORIES:
        for _ in range(products_per_category):
            base_name = rng.choice(names)
            suffix = rng.randint(1, 999)
            name = f"{base_name} {suffix:03d}"
            price = int(rng.lognormvariate(mu=10.5, sigma=0.8))
            price = max(5_000, min(price, 3_000_000))
            stock_pool = rng.random()
            if stock_pool < 0.15:
                stock = rng.randint(0, 99)
            elif stock_pool < 0.6:
                stock = rng.randint(100, 500)
            else:
                stock = rng.randint(500, 2_000)
            rows.append((pid, name, category, price, stock))
            pid += 1
    while pid <= N_PRODUCTS:
        category, names = rng.choice(PRODUCT_CATEGORIES)
        base_name = rng.choice(names)
        name = f"{base_name} {rng.randint(1, 999):03d}"
        price = int(rng.lognormvariate(mu=10.5, sigma=0.8))
        price = max(5_000, min(price, 3_000_000))
        stock = rng.randint(0, 2_000)
        rows.append((pid, name, category, price, stock))
        pid += 1
    return rows


def _generate_orders_and_items(
    rng: random.Random,
    products: list[tuple],
) -> tuple[list[tuple], list[tuple]]:
    orders: list[tuple] = []
    items: list[tuple] = []
    item_id = 1
    price_by_pid = {p[0]: p[3] for p in products}

    for oid in range(1, N_ORDERS + 1):
        customer_id = rng.randint(1, N_CUSTOMERS)
        order_date = _random_date(rng, DATE_START, DATE_END).isoformat()
        status = rng.choices(ORDER_STATUSES, weights=ORDER_STATUS_WEIGHTS, k=1)[0]

        n_items = rng.randint(ITEMS_PER_ORDER_MIN, ITEMS_PER_ORDER_MAX)
        chosen_pids = rng.sample(range(1, N_PRODUCTS + 1), k=n_items)
        total = 0
        for pid in chosen_pids:
            qty = rng.randint(1, 5)
            unit_price = price_by_pid[pid]
            items.append((item_id, oid, pid, qty, unit_price))
            total += qty * unit_price
            item_id += 1

        orders.append((oid, customer_id, order_date, status, total))
    return orders, items


def build_database(db_path: Path | str) -> None:
    """DB 파일을 생성하고 시드 데이터를 삽입한다."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    rng = random.Random(42)

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.executescript(schema_sql)

        departments = _generate_departments()
        employees = _generate_employees(rng)
        customers = _generate_customers(rng)
        products = _generate_products(rng)
        orders, items = _generate_orders_and_items(rng, products)

        with conn:
            conn.executemany(
                "INSERT INTO departments VALUES (?, ?, ?)", departments,
            )
            conn.executemany(
                "INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?, ?)", employees,
            )
            conn.executemany(
                "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)", customers,
            )
            conn.executemany(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?)", products,
            )
            conn.executemany(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?)", orders,
            )
            conn.executemany(
                "INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", items,
            )

        total_rows = (
            len(departments) + len(employees) + len(customers)
            + len(products) + len(orders) + len(items)
        )
        print(f"✓ DB 생성 완료: {db_path} ({total_rows:,} rows)")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="ecommerce 샘플 DB 시드")
    parser.add_argument("--path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--force", action="store_true", help="기존 파일 덮어쓰기")
    args = parser.parse_args()

    if args.path.exists() and not args.force:
        print(f"이미 존재함: {args.path} (덮어쓰려면 --force)")
        return

    build_database(args.path)


if __name__ == "__main__":
    main()
