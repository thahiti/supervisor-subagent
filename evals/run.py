"""LLM-as-Judge 평가 엔트리포인트.

Usage:
    uv run python -m evals.run
    uv run python -m evals.run --filter math
    uv run python -m evals.run --agent translate
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.logging import setup_logging

# registry에 에이전트를 등록하기 위해 import
import src.agents  # noqa: F401

from evals.runner import load_from_dir, print_results, run_all_tests


def main() -> None:
    """평가를 실행한다."""
    parser = argparse.ArgumentParser(description="Run LLM-as-Judge evaluation")
    parser.add_argument(
        "--filter",
        type=str,
        default="",
        help="Filter test cases by id (substring match)",
    )
    parser.add_argument(
        "--agent",
        type=str,
        default="",
        help="Filter test cases by target_agent name",
    )
    args = parser.parse_args()

    setup_logging()

    res_dir = Path(__file__).parent / "res"
    config, test_cases = load_from_dir(res_dir)

    if args.filter:
        test_cases = [tc for tc in test_cases if args.filter in tc["id"]]
    if args.agent:
        test_cases = [tc for tc in test_cases if tc["target_agent"] == args.agent]

    if not test_cases:
        print("No test cases matched the filter criteria.")
        sys.exit(1)

    results = run_all_tests(config, test_cases)
    print_results(config, results, test_cases)

    all_passed = all(r["passed"] for r in results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
