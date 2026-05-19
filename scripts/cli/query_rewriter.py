"""query_rewriter 단독 실행 CLI.

이 모듈은 리라이팅 워크플로우(`rewrite`)를 직접 소유한다. 스모크 등
다른 호출자는 `from scripts.cli.query_rewriter import rewrite`로
in-process로 호출해 결과를 검증할 수 있다.

실행:
    uv run python -m scripts.cli.query_rewriter 지난주 매출 알려줘 --now 2026-04-29T14:30
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages

from scripts.cli._common import (
    add_common_args,
    last_human_text,
    parse_history,
    patched_now,
)
from src.query_rewriter.rewriter import query_rewriter_node
from src.state import State


def rewrite(query: str, chat_history: list[BaseMessage]) -> str:
    """query_rewriter_node를 실행하고 리라이팅된 질의 텍스트를 반환한다.

    리라이팅이 없으면 원본 query를 그대로 반환한다.

    Args:
        query: 현재 사용자 입력.
        chat_history: 큐레이션된 과거 대화 메시지.

    Returns:
        리라이팅된 질의 텍스트 (변화 없으면 원본).
    """
    state: State = {
        "messages": [HumanMessage(content=query)],
        "next_agent": "",
        "chat_history": chat_history,
    }
    rw = query_rewriter_node(state)
    merged = add_messages(state["messages"], rw["messages"])
    return last_human_text(merged, query)


def main() -> None:
    """리라이터를 1회 실행하고 결과를 출력한다."""
    load_dotenv()

    parser = argparse.ArgumentParser(description="query_rewriter 단독 실행")
    add_common_args(parser)
    args = parser.parse_args()

    query = " ".join(args.query)
    history = parse_history(args.history)

    with patched_now(args.now):
        rewritten = rewrite(query, history)

    print(f"query    : {query}")
    print(f"rewritten: {rewritten}")
    sys.exit(0)


if __name__ == "__main__":
    main()
