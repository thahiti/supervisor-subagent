import math
import re

from evals.types import (
    Checks,
    DimensionResult,
    MathCheck,
    OverallCheck,
    TestCase,
    TranslationCheck,
)


def evaluate_routing(
    expected: list[str],
    actual: list[str],
) -> DimensionResult:
    """라우팅 정확도를 평가한다. 순서 포함 exact match.

    Args:
        expected: 예상 에이전트 호출 순서
        actual: 실제 에이전트 호출 순서

    Returns:
        라우팅 평가 결과
    """
    passed = expected == actual
    detail = f"expected={expected} actual={actual}"
    if not passed:
        detail += " (MISMATCH)"
    return DimensionResult(
        dimension="routing",
        passed=passed,
        detail=detail,
    )


def evaluate_math(
    check: MathCheck,
    final_answer: str,
) -> DimensionResult:
    """수학 계산 정확도를 평가한다.

    Args:
        check: 수학 평가 기준 (expected_number)
        final_answer: 최종 답변 텍스트

    Returns:
        수학 평가 결과
    """
    expected = check.get("expected_number")
    if expected is None:
        return DimensionResult(
            dimension="math",
            passed=True,
            detail="no expected_number specified",
        )

    # 답변에서 숫자 추출 (정수, 소수, 콤마 포함)
    numbers = re.findall(r"-?[\d,]+\.?\d*", final_answer)
    parsed: list[float] = []
    for n in numbers:
        try:
            parsed.append(float(n.replace(",", "")))
        except ValueError:
            continue

    found = any(math.isclose(n, expected, rel_tol=1e-6) for n in parsed)
    detail = f"expected={expected}, extracted={parsed}"
    if found:
        detail += ", found in answer"
    else:
        detail += ", NOT found"

    return DimensionResult(
        dimension="math",
        passed=found,
        detail=detail,
    )


def evaluate_translation(
    check: TranslationCheck,
    final_answer: str,
) -> DimensionResult:
    """번역 품질을 평가한다. 키워드 포함 여부로 검사.

    Args:
        check: 번역 평가 기준
        final_answer: 최종 답변 텍스트

    Returns:
        번역 평가 결과
    """
    keywords = check.get("must_contain_meaning", [])
    if not keywords:
        return DimensionResult(
            dimension="translation",
            passed=True,
            detail="no keywords to check",
        )

    answer_lower = final_answer.lower()
    missing = [kw for kw in keywords if kw.lower() not in answer_lower]

    if missing:
        return DimensionResult(
            dimension="translation",
            passed=False,
            detail=f"missing keywords: {missing}",
        )

    return DimensionResult(
        dimension="translation",
        passed=True,
        detail=f"must_contain_meaning={keywords} all found",
    )


def evaluate_overall(
    check: OverallCheck,
    final_answer: str,
) -> DimensionResult:
    """최종 답변을 문자열 검사로 평가한다.

    Args:
        check: 최종 답변 평가 기준
        final_answer: 최종 답변 텍스트

    Returns:
        전체 평가 결과
    """
    answer_lower = final_answer.lower()

    # contains: 모든 키워드가 포함되어야 함
    contains = check.get("contains", [])
    if contains:
        missing = [s for s in contains if s.lower() not in answer_lower]
        if missing:
            return DimensionResult(
                dimension="overall",
                passed=False,
                detail=f"contains={contains}, missing: {missing}",
            )

    # contains_any: 하나라도 포함되면 통과
    contains_any = check.get("contains_any", [])
    if contains_any:
        found_any = any(s.lower() in answer_lower for s in contains_any)
        if not found_any:
            return DimensionResult(
                dimension="overall",
                passed=False,
                detail=f"contains_any={contains_any}, none found",
            )

    # not_contains: 하나라도 포함되면 실패
    not_contains = check.get("not_contains", [])
    if not_contains:
        found_bad = [s for s in not_contains if s.lower() in answer_lower]
        if found_bad:
            return DimensionResult(
                dimension="overall",
                passed=False,
                detail=f"not_contains={not_contains}, found: {found_bad}",
            )

    parts: list[str] = []
    if contains:
        parts.append(f"contains={contains} satisfied")
    if contains_any:
        parts.append(f"contains_any={contains_any} satisfied")
    if not_contains:
        parts.append(f"not_contains={not_contains} satisfied")

    return DimensionResult(
        dimension="overall",
        passed=True,
        detail=", ".join(parts) if parts else "no checks specified",
    )


def evaluate_test_case(
    test_case: TestCase,
    actual_routing: list[str],
    final_answer: str,
) -> list[DimensionResult]:
    """테스트 케이스의 모든 평가 차원을 실행한다.

    Args:
        test_case: 테스트 케이스 정의
        actual_routing: 실제 에이전트 호출 순서
        final_answer: 최종 답변 텍스트

    Returns:
        모든 차원의 평가 결과 리스트
    """
    results: list[DimensionResult] = []

    # routing은 항상 평가
    results.append(evaluate_routing(test_case["expected_routing"], actual_routing))

    checks: Checks = test_case.get("checks", {})

    if "math" in checks:
        results.append(evaluate_math(checks["math"], final_answer))

    if "translation" in checks:
        results.append(evaluate_translation(checks["translation"], final_answer))

    if "overall" in checks:
        results.append(evaluate_overall(checks["overall"], final_answer))

    return results
