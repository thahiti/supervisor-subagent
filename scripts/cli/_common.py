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
import sys
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Iterator, Literal, NotRequired, cast
from unittest.mock import patch

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.state import State

if TYPE_CHECKING:
    from scripts.eval import EvalCase  # 순환 import 회피: 런타임 import 안 함


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
    """query 위치인자 + --history/--now/--example/--list-examples를 parser에 추가한다.

    ``query``는 ``--example``/``--list-examples`` 사용 시 생략 가능하므로
    ``nargs="*"``로 둔다. 호출자는 query 부재 시점에서 직접 검증한다.
    """
    parser.add_argument(
        "query",
        nargs="*",
        help="사용자 질의 (여러 단어는 공백으로 이어 붙임; 따옴표 불필요). "
        "--example/--list-examples 사용 시 생략",
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
    parser.add_argument(
        "--examples",
        default="",
        help="예제 YAML 파일 경로. --example/--list-examples 사용 시 필수. "
        "예: scripts/examples/rewriter.yml",
    )
    parser.add_argument(
        "--example",
        default="",
        help="미리 정의된 예제로 실행 (id 또는 정수 인덱스). "
        "지정 시 query·--history는 무시된다. --examples로 YAML 경로를 함께 줘야 한다.",
    )
    parser.add_argument(
        "--list-examples",
        action="store_true",
        help="--examples로 지정한 YAML의 예제 목록을 출력하고 종료한다.",
    )


def parse_history(raw: str) -> list[BaseMessage]:
    """--history JSON 문자열을 BaseMessage 리스트로 변환한다."""
    if not raw.strip():
        return []
    data = json.loads(raw)
    pairs = [(cast(Role, d["role"]), str(d["content"])) for d in data]
    return to_messages(pairs)


def resolve_example(examples: list[EvalCase], key: str) -> EvalCase:
    """``key``로 예제를 찾아 반환한다. id 매칭이 정수 인덱스보다 우선한다.

    Args:
        examples: 예제 리스트 (``EvalCase``).
        key: 예제 id 문자열 또는 음이 아닌 정수 인덱스 문자열.

    Returns:
        매칭된 예제.

    Raises:
        SystemExit: 매칭되는 예제가 없거나 인덱스 범위를 벗어날 때.
            stderr에 사용 가능한 id 목록을 출력한다.
    """
    for ex in examples:
        if ex["id"] == key:
            return ex
    try:
        idx = int(key)
    except ValueError:
        idx = None
    if idx is not None and 0 <= idx < len(examples):
        return examples[idx]
    available = ", ".join(ex["id"] for ex in examples)
    print(
        f"error: 알 수 없는 예제 '{key}'. 사용 가능: {available}",
        file=sys.stderr,
    )
    raise SystemExit(2)


def print_examples(examples: list[EvalCase]) -> None:
    """예제 목록을 사람이 읽을 수 있는 형태로 stdout에 출력한다.

    각 예제마다 ``[NN] id — description`` 헤더와 ``input["query"]``를
    한 줄씩 보여준다. ``input["chat_history"]``가 있으면 그 아래
    ``history:`` 블록에 ``[role] content`` 형식으로 함께 출력한다.
    """
    for idx, ex in enumerate(examples):
        print(f"[{idx:02d}] {ex['id']} — {ex['description']}")
        query = ex["input"].get("query", "")
        if query:
            print(f"     query  : {query}")
        history = ex["input"].get("chat_history", [])
        if history:
            print("     history:")
            for msg in history:
                role = "human" if isinstance(msg, HumanMessage) else "ai"
                print(f"              [{role}] {msg.content}")


def build_initial_state(input_data: dict) -> CliState:
    """예제 ``input`` 딕셔너리에서 ``CliState``를 만든다.

    ``input["query"]``를 ``HumanMessage``로 감싸 ``messages``에 넣고,
    ``input.get("chat_history", [])``를 그대로 유지한다.
    """
    query = input_data.get("query", "")
    chat_history = input_data.get("chat_history", [])
    messages: list = [HumanMessage(content=query)] if query else []
    return {
        "messages": messages,
        "next_agent": "",
        "chat_history": chat_history,
    }


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
