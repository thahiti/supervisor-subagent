"""query_rewriter 계열 CLI 공용 인자/파서·메시지 유틸.

첫 위치인자(query)는 nargs="+"로 받아 공백으로 이어 붙인다 →
따옴표 없이 여러 단어를 그대로 입력할 수 있다.

`Role`, `to_messages`, `last_human_text`는 두 CLI(`query_rewriter`,
`query_rewriter_router`)와 스모크가 공유하는 CLI-tier 메시지 유틸이며,
워크플로우 함수(`rewrite`, `route_trace`)는 각 CLI 모듈이 직접 소유한다.
"""

from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Literal, NotRequired, cast
from unittest.mock import patch

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.state import State


class CliState(State):
    """CLI 워크플로우(rewrite, route_trace)의 state-IO 타입.

    프로덕션 ``src.state.State``를 확장한다. 입력 단계에는 ``rewritten``과
    ``next_node``가 없을 수 있고, 워크플로우가 출력 state를 만들 때
    채워진다.
    """

    rewritten: NotRequired[str]
    next_node: NotRequired[str]


Role = Literal["human", "ai"]


def to_messages(pairs: list[tuple[Role, str]]) -> list[BaseMessage]:
    """(role, content) 쌍 리스트를 BaseMessage 리스트로 변환한다."""
    out: list[BaseMessage] = []
    for role, content in pairs:
        if role == "human":
            out.append(HumanMessage(content=content))
        else:
            out.append(AIMessage(content=content))
    return out


def last_human_text(messages: list[BaseMessage], default: str) -> str:
    """messages에서 마지막 HumanMessage 본문을 반환한다 (없으면 default)."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return cast(str, msg.content)
    return default


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """query 위치인자 + --history/--now 옵션을 parser에 추가한다."""
    parser.add_argument(
        "query",
        nargs="+",
        help="사용자 질의 (여러 단어는 공백으로 이어 붙임; 따옴표 불필요)",
    )
    parser.add_argument(
        "--history",
        default="",
        help=(
            'chat_history JSON. 예: '
            '\'[{"role":"human","content":"..."},'
            '{"role":"ai","content":"..."}]\''
        ),
    )
    parser.add_argument(
        "--now",
        default="",
        help="리라이터 기준 시각 ISO (예: 2026-04-29T14:30). "
        "지정 시 상대 날짜 변환이 결정적이 된다.",
    )


def parse_history(raw: str) -> list[BaseMessage]:
    """--history JSON 문자열을 BaseMessage 리스트로 변환한다."""
    if not raw.strip():
        return []
    data = json.loads(raw)
    pairs = [(cast(Role, d["role"]), str(d["content"])) for d in data]
    return to_messages(pairs)


@contextmanager
def patched_now(now_iso: str) -> Iterator[None]:
    """now_iso가 주어지면 rewriter의 datetime.now()를 고정한다."""
    if not now_iso:
        yield
        return
    fixed = datetime.fromisoformat(now_iso)
    with patch("src.query_rewriter.rewriter.datetime") as mock_dt:
        mock_dt.now.return_value = fixed
        yield
