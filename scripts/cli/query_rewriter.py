"""query_rewriter 단독 실행 CLI.

이 모듈은 리라이팅 워크플로우(`rewrite`)를 직접 소유한다. 스모크 등
다른 호출자는 `from scripts.cli.query_rewriter import rewrite`로
in-process로 호출해 결과 state를 검증할 수 있다.

실행:
    uv run python -m scripts.cli.query_rewriter 지난주 매출 알려줘 --now 2026-04-29T14:30
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph.message import add_messages

from scripts.cli._common import (
    CliState,
    add_common_args,
    last_human_text,
    parse_history,
    patched_now,
)
from src.query_rewriter.rewriter import query_rewriter_node


def rewrite(state: CliState) -> CliState:
    """query_rewriter_node를 실행하고 리라이팅 텍스트를 채운 새 state를 반환한다.

    ``state["messages"]``의 마지막 HumanMessage를 현재 query로 보고,
    리라이팅 결과 메시지를 messages에 누적한 뒤 ``rewritten`` 필드에
    리라이팅 텍스트를 채워 반환한다. 리라이팅이 일어나지 않으면
    원본 query 텍스트가 그대로 담긴다.

    Args:
        state: 입력 ``CliState``. ``messages``에 적어도 하나의 HumanMessage가
            있어야 한다 (없으면 ``rewritten`` = "").

    Returns:
        ``messages``가 누적되고 ``rewritten``이 채워진 새 ``CliState``.
    """
    rw = query_rewriter_node(state)
    merged = add_messages(state["messages"], rw["messages"])
    rewritten_text = last_human_text(merged, "")
    return {**state, "messages": merged, "rewritten": rewritten_text}


def main() -> None:
    """리라이터를 1회 실행하고 결과를 출력한다."""
    load_dotenv()

    parser = argparse.ArgumentParser(description="query_rewriter 단독 실행")
    add_common_args(parser)
    args = parser.parse_args()

    query = " ".join(args.query)
    history = parse_history(args.history)

    initial: CliState = {
        "messages": [HumanMessage(content=query)],
        "next_agent": "",
        "chat_history": history,
    }

    with patched_now(args.now):
        result = rewrite(initial)

    print(f"query    : {query}")
    print(f"rewritten: {result.get('rewritten', '')}")
    sys.exit(0)


if __name__ == "__main__":
    main()
