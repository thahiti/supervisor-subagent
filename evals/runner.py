import time
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph

from evals.evaluators import evaluate_test_case
from evals.types import TestCase, TestCaseResult


def load_test_cases(path: str | Path) -> list[TestCase]:
    """YAML 파일에서 테스트 케이스를 로드한다.

    Args:
        path: 테스트 케이스 YAML 파일 경로

    Returns:
        테스트 케이스 리스트
    """
    with open(path) as f:
        data = yaml.safe_load(f)
    return data["test_cases"]


def run_single_test(
    app: CompiledStateGraph,
    test_case: TestCase,
) -> TestCaseResult:
    """단일 테스트 케이스를 실행하고 평가한다.

    Args:
        app: 컴파일된 LangGraph 그래프
        test_case: 테스트 케이스 정의

    Returns:
        테스트 결과
    """
    start = time.monotonic()

    result: dict[str, Any] = app.invoke({
        "messages": [HumanMessage(content=test_case["input"])],
        "next_agent": "",
        "plan": "",
        "completed_agents": [],
    })

    elapsed = time.monotonic() - start

    actual_routing: list[str] = result.get("completed_agents", [])
    final_answer: str = result["messages"][-1].content

    dimensions = evaluate_test_case(test_case, actual_routing, final_answer)
    all_passed = all(d["passed"] for d in dimensions)

    return TestCaseResult(
        test_id=test_case["id"],
        passed=all_passed,
        dimensions=dimensions,
        actual_routing=actual_routing,
        final_answer=final_answer,
        elapsed_seconds=round(elapsed, 3),
    )


def run_all_tests(
    app: CompiledStateGraph,
    test_cases: list[TestCase],
) -> list[TestCaseResult]:
    """모든 테스트 케이스를 순차 실행한다.

    Args:
        app: 컴파일된 LangGraph 그래프
        test_cases: 테스트 케이스 리스트

    Returns:
        모든 테스트 결과 리스트
    """
    results: list[TestCaseResult] = []
    for tc in test_cases:
        result = run_single_test(app, tc)
        results.append(result)
    return results


def print_results(
    results: list[TestCaseResult],
    test_cases: list[TestCase],
) -> None:
    """평가 결과를 콘솔에 출력한다.

    Args:
        results: 테스트 결과 리스트
        test_cases: 테스트 케이스 리스트 (description 참조용)
    """
    tc_map = {tc["id"]: tc for tc in test_cases}
    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    failed_ids: list[str] = [r["test_id"] for r in results if not r["passed"]]
    total_time = sum(r["elapsed_seconds"] for r in results)

    print(f"\n{'=' * 60}")
    print("  EVALUATION RESULTS")
    print(f"{'=' * 60}\n")

    for i, r in enumerate(results, 1):
        tc = tc_map[r["test_id"]]
        status = "PASS" if r["passed"] else "FAIL"
        desc = tc["description"]
        header = f"[{i}/{total}] {r['test_id']} - {desc}"
        padding = max(1, 55 - len(header))
        print(f"{header} {'.' * padding} {status} ({r['elapsed_seconds']}s)")

        for d in r["dimensions"]:
            mark = "\u2713" if d["passed"] else "\u2717"
            dim_name = d["dimension"].ljust(12)
            print(f"  {mark} {dim_name}: {d['detail']}")

        print()

    print(f"{'-' * 60}")
    print(f"  SUMMARY: {passed_count}/{total} passed, {total - passed_count} failed")
    if failed_ids:
        print(f"  Failed: {', '.join(failed_ids)}")
    print(f"  Total time: {total_time:.1f}s")
    print(f"{'-' * 60}")
