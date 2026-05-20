"""query_rewriter + router 실행 CLI.

이 모듈은 라우팅 워크플로우(`route_trace`)를 직접 소유한다.
리라이팅 단계는 `scripts.cli.query_rewriter`에 의존하지 않고 이 모듈
안에서 독립적으로 수행한다 (cross-CLI import 없음).

스모크 등 다른 호출자는 `from scripts.cli.query_rewriter_router import
route_trace`로 in-process 호출해 (리라이팅된 질의, 라우팅 목적지)를
직접 검증할 수 있다.

실행:
    uv run python -m scripts.cli.query_rewriter_router 3 곱하기 7
    uv run python -m scripts.cli.query_rewriter_router 공장2 \\
        --history '[{"role":"human","content":"재고 조사"},{"role":"ai","content":"어떤 브랜치?"}]'
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages

import src  # noqa: F401  registry 등록 (router_conditional이 의존)
from scripts.cli._common import (
    add_common_args,
    last_human_text,
    parse_history,
    patched_now,
)
from src.query_rewriter.rewriter import query_rewriter_node
from src.router import router_conditional, router_node
from src.state import State


def route_trace(
    query: str, chat_history: list[BaseMessage]
) -> tuple[str, str]:
    """query_rewriter → router를 연쇄 실행하고
    (리라이팅된 질의, 라우팅된 목적지 노드명)을 반환한다.

    리라이팅 단계는 query_rewriter CLI와 독립적으로 이 모듈 안에서
    수행한다 (strict isolation; cross-CLI import 없음).

    Args:
        query: 현재 사용자 입력.
        chat_history: 큐레이션된 과거 대화 메시지.

    Returns:
        `(rewritten_query, destination_node_name)` 튜플.
        destination은 에이전트의 node_name(예: `math_agent`) 또는
        `response_generator`이다.
    """
    state: State = {
        "messages": [HumanMessage(content=query)],
        "next_agent": "",
        "chat_history": chat_history,
    }

    rw = query_rewriter_node(state)
    state["messages"] = add_messages(state["messages"], rw["messages"])
    rewritten = last_human_text(state["messages"], query)

    rt = router_node(state)
    state["messages"] = add_messages(state["messages"], rt["messages"])
    state["next_agent"] = rt["next_agent"]

    return rewritten, router_conditional(state)


def main() -> None:
    """리라이터 → 라우터를 연쇄 실행하고 결과를 출력한다."""
    load_dotenv()

    parser = argparse.ArgumentParser(description="query_rewriter + router 실행")
    add_common_args(parser)
    args = parser.parse_args()

    query = " ".join(args.query)
    history = parse_history(args.history)

    with patched_now(args.now):
        rewritten, destination = route_trace(query, history)

    print(f"query      : {query}")
    print(f"rewritten  : {rewritten}")
    print(f"destination: {destination}")
    sys.exit(0)


if __name__ == "__main__":
    main()
