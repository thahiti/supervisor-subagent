"""슬롯 에이전트 도메인 시나리오 카탈로그.

모듈 import 시 부수효과로 scenario_registry에 모든 시나리오가 등록된다.
도메인 지식(lookup/metric, 테이블/컬럼명)은 이 파일에만 모인다. 새 시나리오
추가는 이 파일에 lookup/metric 함수와 Scenario 선언을 더하는 것으로 끝난다.
"""

from __future__ import annotations

import re
from typing import Any

from src.slot_agent.registry import Scenario, Slot, scenario_registry
from src.slot_agent.repository import Repository

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def _validate_month(raw: Any) -> str:
    text = str(raw).strip()
    if not _MONTH_RE.match(text):
        raise ValueError(f"YYYY-MM 형식이 아닙니다: {raw!r}")
    return text


# --- regional_sales: country → branch → 월별 매출 ---
def _list_countries(repo: Repository, slots: dict) -> list[dict]:
    return repo.all("countries")


def _list_branches(repo: Repository, slots: dict) -> list[dict]:
    return repo.where("branches", country_id=slots["country"])


def _get_sales(repo: Repository, slots: dict) -> dict:
    rows = repo.where("sales", branch_id=slots["branch"])
    rows.sort(key=lambda r: r["month"])
    return {
        "label": "월별 매출액",
        "columns": ["month", "amount"],
        "rows": [(r["month"], r["amount"]) for r in rows],
    }


scenario_registry.register(Scenario(
    id="regional_sales",
    label="지역별 매출 조회",
    slots=(
        Slot(name="country", description="나라", lookup=_list_countries),
        Slot(name="branch", description="지점", lookup=_list_branches,
             parent="country"),
    ),
    metric=_get_sales,
))


# --- product_stock: category → product → 재고 수량 ---
def _list_categories(repo: Repository, slots: dict) -> list[dict]:
    return repo.all("categories")


def _list_products(repo: Repository, slots: dict) -> list[dict]:
    return repo.where("products", category_id=slots["category"])


def _get_stock(repo: Repository, slots: dict) -> dict:
    products = repo.where("products", id=slots["product"])
    inventory = repo.where("inventory", product_id=slots["product"])
    name = products[0]["name"] if products else str(slots["product"])
    stock = inventory[0]["stock"] if inventory else 0
    return {
        "label": "제품 재고 수량",
        "columns": ["product", "stock"],
        "rows": [(name, stock)],
    }


scenario_registry.register(Scenario(
    id="product_stock",
    label="제품 재고 조회",
    slots=(
        Slot(name="category", description="제품 카테고리", lookup=_list_categories),
        Slot(name="product", description="제품", lookup=_list_products,
             parent="category"),
    ),
    metric=_get_stock,
))


# --- new_signups: channel + month(자유 입력, 독립 필터) → 신규 가입자 수 ---
def _list_channels(repo: Repository, slots: dict) -> list[dict]:
    return repo.all("channels")


def _get_signups(repo: Repository, slots: dict) -> dict:
    channels = repo.where("channels", id=slots["channel"])
    name = channels[0]["name"] if channels else str(slots["channel"])
    rows = repo.where("signups", channel_id=slots["channel"], month=slots["month"])
    # 해당 채널·월에 데이터가 없으면 가입자 0명으로 간주한다(명시적 합의).
    count = rows[0]["count"] if rows else 0
    return {
        "label": "신규 가입자 수",
        "columns": ["channel", "month", "signups"],
        "rows": [(name, slots["month"], count)],
    }


scenario_registry.register(Scenario(
    id="new_signups",
    label="신규 가입자 분석",
    slots=(
        Slot(name="channel", description="유입 채널", lookup=_list_channels),
        Slot(name="month", description="조회 월(YYYY-MM)", lookup=None,
             validator=_validate_month),
    ),
    metric=_get_signups,
))
