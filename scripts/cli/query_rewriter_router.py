"""query_rewriter + router 실행 CLI.

이 모듈은 라우팅 워크플로우(`route_trace`)를 직접 소유한다.
리라이팅 단계는 `scripts.cli.query_rewriter`에 의존하지 않고 이 모듈
안에서 독립적으로 수행한다 (cross-CLI import 없음).

스모크 등 다른 호출자는 `from scripts.cli.query_rewriter_router import
route_trace`로 in-process 호출해 결과 state를 직접 검증할 수 있다.

실행:
    uv run python -m scripts.cli.query_rewriter_router 3 곱하기 7
    uv run python -m scripts.cli.query_rewriter_router 공장2 \\
        --history '[{"role":"human","content":"재고 조사"},{"role":"ai","content":"어떤 브랜치?"}]'
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph.message import add_messages

import src  # noqa: F401  registry 등록 (router_conditional이 의존)
from scripts.cli._common import (
    CliState,
    add_common_args,
    last_human_text,
    parse_history,
    patched_now,
    print_examples,
    resolve_example,
)
from scripts.cli._examples import ROUTER_EXAMPLES
from src.query_rewriter.rewriter import query_rewriter_node
from src.router import router_conditional, router_node


def route_trace(state: CliState) -> CliState:
    """query_rewriter → router를 연쇄 실행하고 모든 결과 필드를 채운 새
    ``CliState``를 반환한다.

    리라이팅 단계는 query_rewriter 모듈에 의존하지 않고 이 함수 안에서
    독립적으로 수행한다 (strict isolation; cross-CLI import 없음).
    결과 state에는 ``rewritten``, ``next_agent``, ``next_node``가 모두
    채워진다.

    Args:
        state: 입력 ``CliState``.

    Returns:
        ``messages``가 누적되고 ``rewritten``/``next_agent``/``next_node``가
        모두 채워진 새 ``CliState``.
    """
    rw = query_rewriter_node(state)
    msgs_after_rewrite = add_messages(state["messages"], rw["messages"])
    rewritten_text = last_human_text(msgs_after_rewrite, "")

    state_for_router: CliState = {**state, "messages": msgs_after_rewrite}
    rt = router_node(state_for_router)
    msgs_after_router = add_messages(msgs_after_rewrite, rt["messages"])

    after_router: CliState = {
        **state,
        "messages": msgs_after_router,
        "next_agent": rt["next_agent"],
        "rewritten": rewritten_text,
    }
    return {**after_router, "next_node": router_conditional(after_router)}


def main() -> None:
    """리라이터 → 라우터를 연쇄 실행하고 결과를 출력한다."""
    load_dotenv()

    parser = argparse.ArgumentParser(description="query_rewriter + router 실행")
    add_common_args(parser)
    args = parser.parse_args()

    if args.list_examples:
        print_examples(ROUTER_EXAMPLES)
        sys.exit(0)

    if args.example:
        ex = resolve_example(ROUTER_EXAMPLES, args.example)
        baseline: CliState = {"messages": [], "next_agent": "", "chat_history": []}
        initial: CliState = {**baseline, **ex["input"]}
        query = last_human_text(initial["messages"], "")
    else:
        if not args.query:
            parser.error("query 또는 --example/--list-examples 중 하나가 필요합니다")
        query = " ".join(args.query)
        history = parse_history(args.history)
        initial = {
            "messages": [HumanMessage(content=query)],
            "next_agent": "",
            "chat_history": history,
        }

    with patched_now(args.now):
        result = route_trace(initial)

    print(f"query      : {query}")
    print(f"rewritten  : {result.get('rewritten', '')}")
    print(f"destination: {result.get('next_node', '')}")
    sys.exit(0)


if __name__ == "__main__":
    main()
