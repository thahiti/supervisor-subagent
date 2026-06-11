"""슬롯 에이전트 가상 DB repository 단위 테스트."""

from __future__ import annotations

import json

import pytest

from src.slot_agent.repository import Repository


def _repo() -> Repository:
    return Repository(tables={
        "countries": [{"id": 1, "name": "한국"}, {"id": 2, "name": "일본"}],
        "branches": [
            {"id": 11, "country_id": 1, "name": "강남점"},
            {"id": 12, "country_id": 1, "name": "부산점"},
            {"id": 21, "country_id": 2, "name": "도쿄점"},
        ],
    })


class TestQuery:
    def test_all_returns_every_row(self) -> None:
        assert len(_repo().all("countries")) == 2

    def test_all_unknown_table_raises(self) -> None:
        with pytest.raises(KeyError):
            _repo().all("nope")

    def test_all_returns_defensive_copy(self) -> None:
        repo = _repo()
        repo.all("countries")[0]["name"] = "변조"
        assert repo.all("countries")[0]["name"] == "한국"

    def test_where_filters_by_equality(self) -> None:
        rows = _repo().where("branches", country_id=1)
        assert {r["name"] for r in rows} == {"강남점", "부산점"}

    def test_where_multiple_filters(self) -> None:
        rows = _repo().where("branches", country_id=1, name="강남점")
        assert len(rows) == 1 and rows[0]["id"] == 11

    def test_where_no_match_returns_empty(self) -> None:
        assert _repo().where("branches", country_id=999) == []


class TestFromDir:
    def test_from_dir_loads_files_by_stem(self, tmp_path) -> None:
        (tmp_path / "widgets.json").write_text(
            json.dumps([{"id": 1, "name": "a"}]), encoding="utf-8"
        )
        repo = Repository.from_dir(tmp_path)
        assert repo.all("widgets") == [{"id": 1, "name": "a"}]
