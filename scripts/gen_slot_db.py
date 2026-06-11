"""슬롯 에이전트 가상 DB(res/slot_db/*.json)를 결정적으로 생성한다.

난수·현재시각을 쓰지 않고 데이터를 리터럴로 고정한다. 재실행해도 동일한
파일이 생성되어 grounding 테스트가 안정적이다.

실행:
    uv run python scripts/gen_slot_db.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "res" / "slot_db"

TABLES: dict[str, list[dict]] = {
    # --- regional_sales: country -> branch -> 월별 매출 ---
    "countries": [
        {"id": 1, "name": "한국"},
        {"id": 2, "name": "일본"},
    ],
    "branches": [
        {"id": 11, "country_id": 1, "name": "강남점"},
        {"id": 12, "country_id": 1, "name": "부산점"},
        {"id": 21, "country_id": 2, "name": "도쿄점"},
    ],
    "sales": [
        {"branch_id": 11, "month": "2026-01", "amount": 1200},
        {"branch_id": 11, "month": "2026-02", "amount": 1500},
        {"branch_id": 11, "month": "2026-03", "amount": 1800},
        {"branch_id": 12, "month": "2026-01", "amount": 800},
        {"branch_id": 12, "month": "2026-02", "amount": 950},
        {"branch_id": 21, "month": "2026-01", "amount": 2200},
    ],
    # --- product_stock: category -> product -> 재고 ---
    "categories": [
        {"id": 1, "name": "전자"},
        {"id": 2, "name": "식품"},
    ],
    "products": [
        {"id": 101, "category_id": 1, "name": "노트북"},
        {"id": 102, "category_id": 1, "name": "모니터"},
        {"id": 201, "category_id": 2, "name": "원두커피"},
    ],
    "inventory": [
        {"product_id": 101, "stock": 34},
        {"product_id": 102, "stock": 12},
        {"product_id": 201, "stock": 240},
    ],
    # --- new_signups: channel + month(자유 입력) -> 신규 가입자 수 ---
    "channels": [
        {"id": 1, "name": "검색광고"},
        {"id": 2, "name": "추천"},
    ],
    "signups": [
        {"channel_id": 1, "month": "2026-01", "count": 120},
        {"channel_id": 1, "month": "2026-02", "count": 150},
        {"channel_id": 2, "month": "2026-01", "count": 80},
    ],
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in TABLES.items():
        path = OUT_DIR / f"{name}.json"
        path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
