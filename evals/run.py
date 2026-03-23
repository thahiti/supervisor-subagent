"""Evaluation entry point.

Usage:
    uv run python -m evals.run
    uv run python -m evals.run --filter math
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.logging import setup_logging
from src.main import build_graph

from evals.runner import load_test_cases, print_results, run_all_tests


def main() -> None:
    """평가를 실행한다."""
    parser = argparse.ArgumentParser(description="Run evaluation test cases")
    parser.add_argument(
        "--filter",
        type=str,
        default="",
        help="Filter test cases by id (substring match)",
    )
    args = parser.parse_args()

    setup_logging()

    test_cases_path = Path(__file__).parent / "test_cases.yaml"
    test_cases = load_test_cases(test_cases_path)

    if args.filter:
        test_cases = [tc for tc in test_cases if args.filter in tc["id"]]
        if not test_cases:
            print(f"No test cases matching filter: '{args.filter}'")
            sys.exit(1)

    app = build_graph()
    results = run_all_tests(app, test_cases)
    print_results(results, test_cases)

    all_passed = all(r["passed"] for r in results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
