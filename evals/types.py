from typing import Any, NotRequired, TypedDict


class ScoreDetail(TypedDict):
    """개별 평가 기준의 점수와 근거."""

    score: int
    reason: str


class JudgeResult(TypedDict):
    """Judge LLM의 평가 결과."""

    scores: dict[str, ScoreDetail]
    overall_score: float
    summary: str


class TestCase(TypedDict):
    """테스트 케이스 정의."""

    id: str
    description: str
    target_agent: str
    input: str
    reference_answer: str
    state_overrides: NotRequired[dict[str, Any]]
    eval_criteria: NotRequired[list[str]]  # 케이스 레벨 override


class EvalConfig(TypedDict):
    """평가 설정."""

    judge_model: str
    judge_temperature: float
    pass_threshold: float
    agent_criteria: dict[str, list[str]]


class TestCaseResult(TypedDict):
    """테스트 케이스 실행 결과."""

    test_id: str
    target_agent: str
    passed: bool
    judge_result: JudgeResult
    actual_output: str
    elapsed_seconds: float
