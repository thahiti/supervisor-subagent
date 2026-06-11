"""슬롯 에이전트의 가상 DB 레이어.

실제 DB 대신 JSON 파일을 읽어 메모리 dict로 올려두고, 도메인 무지한 테이블
조회 인터페이스(all/where)만 노출한다. 나중에 이 클래스의 내부 저장소만
진짜 DB로 교체하면 시나리오/에이전트 코드는 그대로다 — 핵심 추상화 경계.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# repository.py 기준: parents[0]=slot_agent, [1]=src, [2]=repo root
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "res" / "slot_db"


class Repository:
    """JSON 테이블 저장소. 테이블명(파일 stem) → 행(dict) 리스트."""

    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self._tables = tables

    @classmethod
    def from_dir(cls, data_dir: str | Path) -> "Repository":
        """디렉터리 내 모든 *.json을 로드한다. 파일명(stem)이 테이블명."""
        dir_path = Path(data_dir)
        if not dir_path.exists():
            raise FileNotFoundError(f"데이터 디렉터리가 없습니다: {data_dir}")
        tables: dict[str, list[dict[str, Any]]] = {}
        for path in sorted(dir_path.glob("*.json")):
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError(f"{path.name}: JSON 최상위는 list여야 합니다")
            tables[path.stem] = data
        return cls(tables)

    def all(self, table: str) -> list[dict[str, Any]]:
        """테이블의 모든 행을 반환(행 단위 방어 복사). 미등록 테이블이면 KeyError."""
        if table not in self._tables:
            raise KeyError(f"등록되지 않은 테이블: {table}")
        return [dict(row) for row in self._tables[table]]

    def where(self, table: str, **filters: Any) -> list[dict[str, Any]]:
        """모든 filters를 동등 비교로 만족하는 행만 반환."""
        return [
            row for row in self.all(table)
            if all(row.get(k) == v for k, v in filters.items())
        ]


_repository: Repository | None = None


def get_repository() -> Repository:
    """전역 repository 인스턴스. 최초 호출 시 res/slot_db에서 lazy 로드."""
    global _repository
    if _repository is None:
        _repository = Repository.from_dir(_DEFAULT_DATA_DIR)
    return _repository


def set_repository(repo: Repository | None) -> None:
    """전역 repository를 교체(테스트용). None이면 다음 get에서 재로딩."""
    global _repository
    _repository = repo
