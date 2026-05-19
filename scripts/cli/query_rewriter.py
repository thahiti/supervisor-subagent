"""query_rewriter 단독 실행 CLI.

첫 위치인자로 사용자 질의를 받아 리라이팅 결과를 stdout에 출력한다.

실행:
    uv run python -m scripts.cli.query_rewriter 지난주 매출 알려줘 --now 2026-04-29T14:30
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv


def main() -> None:
    """리라이터를 1회 실행하고 결과를 출력한다."""
    load_dotenv()
    import src  # noqa: F401  registry 등록

    from evals.route_eval import rewrite
    from scripts.cli._common import add_common_args, parse_history, patched_now

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
