import logging
import time
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import HumanMessage

from evals.judge import judge
from evals.types import EvalConfig, TestCase, TestCaseResult

logger = logging.getLogger("supervisor_subagent.eval.runner")


def _load_single_yaml(path: Path) -> tuple[EvalConfig | None, list[TestCase]]:
    """단일 YAML 파일을 로드한다.

    Args:
        path: YAML 파일 경로

    Returns:
        (eval_config 또는 None, test_cases) 튜플
    """
    with open(path) as f:
        data = yaml.safe_load(f)
    if data is None:
        return None, []
    config = data.get("eval_config")
    cases = data.get("test_cases", [])
    return config, cases


def load_from_dir(res_dir: str | Path) -> tuple[EvalConfig, list[TestCase]]:
    """res 디렉토리 하위의 모든 YAML 파일을 수집하여 로드한다.

    eval_config는 첫 번째로 발견된 것을 사용한다.
    test_cases는 모든 파일에서 병합한다.

    Args:
        res_dir: YAML 파일이 위치한 디렉토리

    Returns:
        (eval_config, 병합된 test_cases) 튜플
    """
    res_path = Path(res_dir)
    yaml_files = sorted(res_path.glob("**/*.yaml")) + sorted(res_path.glob("**/*.yml"))

    if not yaml_files:
        raise FileNotFoundError(f"No YAML files found in {res_path}")

    config: EvalConfig | None = None
    all_cases: list[TestCase] = []

    for f in yaml_files:
        logger.info("YAML 로드: %s", f)
        file_config, cases = _load_single_yaml(f)
        if file_config is not None and config is None:
            config = file_config
        all_cases.extend(cases)

    if config is None:
        raise ValueError("eval_config가 정의된 YAML 파일이 없습니다.")

    logger.info("총 %d개 테스트 케이스 로드 (%d개 파일)", len(all_cases), len(yaml_files))
    return config, all_cases


def _resolve_criteria(
    config: EvalConfig,
    test_case: TestCase,
) -> list[str]:
    """테스트 케이스의 평가 기준을 결정한다.

    케이스 레벨 override가 있으면 우선, 없으면 agent_criteria에서 조회.

    Args:
        config: 평가 설정
        test_case: 테스트 케이스

    Returns:
        평가 기준 목록
    """
    if "eval_criteria" in test_case:
        return test_case["eval_criteria"]
    return config["agent_criteria"].get(test_case["target_agent"], ["correctness"])


def _invoke_agent(
    target_agent: str,
    input_text: str,
    state_overrides: dict[str, Any] | None,
) -> str:
    """registry에서 에이전트를 조회하여 wrapper를 호출한다.

    Args:
        target_agent: 에이전트 이름
        input_text: 사용자 입력
        state_overrides: State에 병합할 추가 필드

    Returns:
        에이전트의 최종 출력 텍스트
    """
    from src.agents.registry import registry

    entry = registry.get(target_agent)
    if entry is None:
        raise ValueError(f"에이전트 '{target_agent}'가 registry에 등록되어 있지 않습니다.")

    state: dict[str, Any] = {
        "messages": [HumanMessage(content=input_text)],
        "next_agent": "",
        "plan": "",
        "completed_agents": [],
    }

    if state_overrides:
        state.update(state_overrides)

    result = entry.wrapper(state)
    return result["messages"][-1].content


def run_single_test(
    config: EvalConfig,
    test_case: TestCase,
) -> TestCaseResult:
    """단일 테스트 케이스를 실행하고 Judge로 평가한다.

    Args:
        config: 평가 설정
        test_case: 테스트 케이스

    Returns:
        테스트 결과
    """
    criteria = _resolve_criteria(config, test_case)
    state_overrides = test_case.get("state_overrides")

    start = time.monotonic()

    logger.info("에이전트 실행: %s (id=%s)", test_case["target_agent"], test_case["id"])
    try:
        actual_output = _invoke_agent(
            test_case["target_agent"],
            test_case["input"],
            state_overrides,
        )
    except Exception:
        logger.error("에이전트 실행 실패: %s", test_case["id"], exc_info=True)
        raise

    logger.info("Judge 평가 시작: %s", test_case["id"])
    judge_result = judge(
        config=config,
        input_text=test_case["input"],
        reference_answer=test_case["reference_answer"],
        actual_output=actual_output,
        criteria=criteria,
    )

    elapsed = time.monotonic() - start
    passed = judge_result["overall_score"] >= config["pass_threshold"]

    return TestCaseResult(
        test_id=test_case["id"],
        target_agent=test_case["target_agent"],
        passed=passed,
        judge_result=judge_result,
        actual_output=actual_output,
        elapsed_seconds=round(elapsed, 1),
    )


def run_all_tests(
    config: EvalConfig,
    test_cases: list[TestCase],
) -> list[TestCaseResult]:
    """모든 테스트 케이스를 순차 실행한다.

    Args:
        config: 평가 설정
        test_cases: 테스트 케이스 리스트

    Returns:
        모든 테스트 결과
    """
    results: list[TestCaseResult] = []
    for tc in test_cases:
        result = run_single_test(config, tc)
        results.append(result)
    return results


def print_results(
    config: EvalConfig,
    results: list[TestCaseResult],
    test_cases: list[TestCase],
) -> None:
    """평가 결과를 콘솔에 출력한다.

    Args:
        config: 평가 설정
        results: 테스트 결과 리스트
        test_cases: 테스트 케이스 리스트
    """
    tc_map = {tc["id"]: tc for tc in test_cases}
    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    failed_ids = [r["test_id"] for r in results if not r["passed"]]
    total_time = sum(r["elapsed_seconds"] for r in results)

    print(f"\n{'=' * 60}")
    print(f"  EVALUATION RESULTS (judge: {config['judge_model']})")
    print(f"{'=' * 60}\n")

    for i, r in enumerate(results, 1):
        tc = tc_map[r["test_id"]]
        status = "PASS" if r["passed"] else "FAIL"
        score = r["judge_result"]["overall_score"]
        desc = tc["description"]
        header = f"[{i}/{total}] {r['test_id']} - {desc}"
        padding = max(1, 50 - len(header))
        print(f"{header} {'.' * padding} {status} ({score}, {r['elapsed_seconds']}s)")

        for criterion, detail in r["judge_result"]["scores"].items():
            mark = "\u2713" if detail["score"] >= config["pass_threshold"] else "\u2717"
            crit_name = criterion.ljust(16)
            print(f"  {mark} {crit_name}: {detail['score']}/10 - {detail['reason']}")

        print()

    print(f"{'-' * 60}")
    print(f"  SUMMARY: {passed_count}/{total} passed (threshold: {config['pass_threshold']})")
    if failed_ids:
        print(f"  Failed: {', '.join(failed_ids)}")
    print(f"  Total time: {total_time:.1f}s")
    print(f"{'-' * 60}")
