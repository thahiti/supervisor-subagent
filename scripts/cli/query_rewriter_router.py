"""query_rewriter + router 실행 CLI.

첫 위치인자로 사용자 질의를 받아 리라이팅 후 라우팅하고,
리라이팅 결과와 라우팅 목적지를 stdout에 출력한다.

실행:
    uv run python -m scripts.cli.query_rewriter_router 3 곱하기 7
    uv run python -m scripts.cli.query_rewriter_router 공장2 \\
        --history '[{"role":"human","content":"재고 조사"},{"role":"ai","content":"어떤 브랜치?"}]'
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv


def main() -> None:
    """리라이터 → 라우터를 연쇄 실행하고 결과를 출력한다."""
    load_dotenv()
    import src  # noqa: F401  registry 등록

    from evals.route_eval import route_trace
    from scripts.cli._common import add_common_args, parse_history, patched_now

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
