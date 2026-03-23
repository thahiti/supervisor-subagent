from typing import NotRequired, TypedDict


class MathCheck(TypedDict, total=False):
    """수학 계산 평가 기준."""

    expected_number: float


class TranslationCheck(TypedDict, total=False):
    """번역 평가 기준."""

    source_text: str
    direction: str  # "en_to_kr" | "kr_to_en"
    must_contain_meaning: list[str]


class OverallCheck(TypedDict, total=False):
    """최종 답변 평가 기준."""

    contains: list[str]
    contains_any: list[str]
    not_contains: list[str]


class Checks(TypedDict, total=False):
    """평가 차원별 기준."""

    math: MathCheck
    translation: TranslationCheck
    overall: OverallCheck


class TestCase(TypedDict):
    """테스트 케이스 정의."""

    id: str
    description: str
    input: str
    expected_routing: list[str]
    checks: NotRequired[Checks]


class DimensionResult(TypedDict):
    """개별 평가 차원의 결과."""

    dimension: str  # "routing" | "math" | "translation" | "overall"
    passed: bool
    detail: str


class TestCaseResult(TypedDict):
    """테스트 케이스 전체 결과."""

    test_id: str
    passed: bool
    dimensions: list[DimensionResult]
    actual_routing: list[str]
    final_answer: str
    elapsed_seconds: float
