"""슬롯 에이전트 wrapper 분기 로직 테스트. LLM은 mock으로 주입."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.slot_agent.agent import slot_wrapper
from src.slot_agent.repository import Repository, set_repository


@pytest.fixture(autouse=True)
def _virtual_db():
    """각 테스트마다 결정적 in-memory 가상 DB를 주입하고 끝나면 초기화."""
    set_repository(Repository(tables={
        "countries": [{"id": 1, "name": "한국"}, {"id": 2, "name": "일본"}],
        "branches": [
            {"id": 11, "country_id": 1, "name": "강남점"},
            {"id": 12, "country_id": 1, "name": "부산점"},
        ],
        "sales": [
            {"branch_id": 11, "month": "2026-01", "amount": 1200},
            {"branch_id": 11, "month": "2026-02", "amount": 1500},
        ],
        "categories": [{"id": 1, "name": "전자"}],
        "products": [{"id": 101, "category_id": 1, "name": "노트북"}],
        "inventory": [{"product_id": 101, "stock": 34}],
        "channels": [{"id": 1, "name": "검색광고"}],
        "signups": [{"channel_id": 1, "month": "2026-01", "count": 120}],
    }))
    yield
    set_repository(None)


def _state(text: str) -> dict:
    return {"messages": [HumanMessage(content=text)], "next_agent": "",
            "chat_history": []}


def _llm_returning(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.invoke.return_value = MagicMock(
        content=json.dumps(payload, ensure_ascii=False)
    )
    return mock


class TestAskFlow:
    @patch("src.slot_agent.agent.get_chat_model")
    def test_empty_slots_asks_first_with_candidates(self, mock_model) -> None:
        mock_model.return_value = _llm_returning(
            {"scenario_id": "regional_sales", "slots": {}}
        )
        result = slot_wrapper(_state("지역 매출 알려줘"))
        content = result["messages"][-1].content
        assert "나라" in content
        assert "한국" in content and "일본" in content  # DB 후보 grounding

    @patch("src.slot_agent.agent.get_chat_model")
    def test_parent_filled_asks_child_filtered(self, mock_model) -> None:
        mock_model.return_value = _llm_returning(
            {"scenario_id": "regional_sales", "slots": {"country": "한국"}}
        )
        content = slot_wrapper(_state("한국"))["messages"][-1].content
        assert "강남점" in content and "부산점" in content
        assert "도쿄점" not in content  # 일본 지점은 후보에서 제외


class TestFetchFlow:
    @patch("src.slot_agent.agent.get_chat_model")
    def test_all_slots_filled_runs_metric(self, mock_model) -> None:
        mock_model.return_value = _llm_returning({
            "scenario_id": "regional_sales",
            "slots": {"country": "한국", "branch": "강남점"},
        })
        content = slot_wrapper(_state("한국 강남점 매출"))["messages"][-1].content
        assert "월별 매출액" in content
        assert "2026-01" in content and "1200" in content


class TestNoMatch:
    @patch("src.slot_agent.agent.get_chat_model")
    def test_null_scenario_returns_no_match(self, mock_model) -> None:
        mock_model.return_value = _llm_returning(
            {"scenario_id": None, "slots": {}}
        )
        content = slot_wrapper(_state("안녕"))["messages"][-1].content
        assert "지역별 매출" in content  # 카탈로그 안내

    @patch("src.slot_agent.agent.get_chat_model")
    def test_unparseable_json_falls_back_to_no_match(self, mock_model) -> None:
        mock = MagicMock()
        mock.invoke.return_value = MagicMock(content="JSON 아님")
        mock_model.return_value = mock
        content = slot_wrapper(_state("ㅁㄴㅇ"))["messages"][-1].content
        assert "지역별 매출" in content

    @patch("src.slot_agent.agent.get_chat_model")
    def test_unknown_scenario_id_falls_back(self, mock_model) -> None:
        mock_model.return_value = _llm_returning(
            {"scenario_id": "does_not_exist", "slots": {}}
        )
        content = slot_wrapper(_state("..."))["messages"][-1].content
        assert "지역별 매출" in content


class TestFreeSlot:
    @patch("src.slot_agent.agent.get_chat_model")
    def test_missing_free_month_asks_for_value(self, mock_model) -> None:
        mock_model.return_value = _llm_returning(
            {"scenario_id": "new_signups", "slots": {"channel": "검색광고"}}
        )
        content = slot_wrapper(_state("검색광고 가입자"))["messages"][-1].content
        assert "조회 월(YYYY-MM)" in content
        assert "값을 알려주세요" in content


def test_object_particle_picks_correct_josa() -> None:
    from src.slot_agent.agent import _object_particle

    assert _object_particle("지점") == "을"   # 받침 있음
    assert _object_particle("나라") == "를"   # 받침 없음
    assert _object_particle("제품") == "을"
    assert _object_particle("채널") == "을"
    assert _object_particle("AB") == "를"     # 비한글 → 기본값
    assert _object_particle("") == "를"
