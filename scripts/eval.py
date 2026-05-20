"""공통 평가 프레임워크 — 스모크들이 공유하는 케이스 실행·검증·출력.

`EvalCase` 데이터를 받아 워크플로우(`(CliState) -> CliState`)를 호출하고,
선언적 `expected` dict로 결과 state를 검증한다. 워크플로우 자체에 대해
아무것도 모른다 — 호출자가 워크플로우를 인자로 넘긴다.

op 추론 규칙:
- ``str``/``int``/``bool`` 등 plain → ``actual == value`` (정확히 같음)
- ``re.Pattern`` → ``value.search(str(actual))`` (정규식 매칭)
- ``list[re.Pattern]`` → 모든 패턴이 매치 (정규식 AND)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, NotRequired, TypedDict, cast

import yaml
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from scripts.cli._common import CliState, patched_now


class _Missing:
    """결과 state에 expected 필드가 없을 때 ``result.get`` 기본값으로 쓰는 sentinel."""

    def __repr__(self) -> str:
        return "<missing>"

    def __str__(self) -> str:
        return "<missing>"


_MISSING = _Missing()


class EvalCase(TypedDict):
    """선언적 평가 케이스. 케이스는 입력 데이터와 기대 검증값만 가진다.
    실행 정책(고정 시각, 재시도 횟수)은 ``run_eval`` 인자로 받는다.
    """

    id: str
    description: str
    input: dict[str, Any]
    expected: dict[str, Any]


class _ExamplesLoader(yaml.SafeLoader):
    """``!regex`` / ``!regex_all`` 태그를 ``re.Pattern``으로 변환하는 SafeLoader."""


def _regex_ctor(loader: _ExamplesLoader, node: yaml.Node) -> re.Pattern[str]:
    return re.compile(loader.construct_scalar(cast(yaml.ScalarNode, node)))


def _regex_all_ctor(
    loader: _ExamplesLoader, node: yaml.Node
) -> list[re.Pattern[str]]:
    raw = loader.construct_sequence(cast(yaml.SequenceNode, node))
    return [re.compile(str(p)) for p in raw]


_ExamplesLoader.add_constructor("!regex", _regex_ctor)
_ExamplesLoader.add_constructor("!regex_all", _regex_all_ctor)


def _to_message(item: dict[str, Any]) -> BaseMessage:
    """{role, content} 항목을 BaseMessage로 변환한다."""
    role = item["role"]
    content = str(item["content"])
    if role == "human":
        return HumanMessage(content=content)
    if role == "ai":
        return AIMessage(content=content)
    raise ValueError(f"unsupported role: {role!r} (지원: 'human', 'ai')")


def load_examples(path: str | Path) -> list[EvalCase]:
    """YAML 파일에서 예제 리스트를 읽어 EvalCase 리스트로 반환한다.

    YAML 스키마 (top-level list):
        - id: str
          description: str
          input:
            query: str
            chat_history:                # optional
              - {role: human|ai, content: str}
          expected:
            <field>: <scalar | !regex "..." | !regex_all [...]>

    파싱 시 ``chat_history``의 각 항목은 ``BaseMessage``로 변환된다.
    ``!regex``/``!regex_all`` 태그는 ``re.Pattern`` 또는 그 리스트로 변환된다.

    Raises:
        FileNotFoundError: 파일이 없을 때.
        ValueError: 지원하지 않는 role.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    raw = yaml.load(text, Loader=_ExamplesLoader)
    if raw is None:
        return []
    cases: list[EvalCase] = []
    for entry in raw:
        input_data = dict(entry.get("input", {}))
        if "chat_history" in input_data:
            input_data["chat_history"] = [_to_message(m) for m in input_data["chat_history"]]
        cases.append({
            "id": entry["id"],
            "description": entry["description"],
            "input": input_data,
            "expected": entry.get("expected", {}),
        })
    return cases


def _check(expected_value: Any, actual: Any) -> bool:
    """op를 ``expected_value``의 타입으로 추론하여 어션을 평가한다."""
    if isinstance(expected_value, re.Pattern):
        return expected_value.search(str(actual)) is not None
    if (
        isinstance(expected_value, list)
        and expected_value
        and all(isinstance(p, re.Pattern) for p in expected_value)
    ):
        return all(p.search(str(actual)) is not None for p in expected_value)
    return actual == expected_value


def _build_initial_state(overrides: dict[str, Any]) -> CliState:
    """베이스라인 CliState에 ``overrides``를 머지하여 입력 state를 만든다."""
    baseline: CliState = {
        "messages": [],
        "next_agent": "",
        "chat_history": [],
    }
    return {**baseline, **overrides}


def _check_case(
    expected: dict[str, Any], result: CliState
) -> tuple[bool, dict[str, tuple[Any, Any]]]:
    """결과 state의 각 expected 필드를 검증한다.

    Returns:
        (모두 통과 여부, 실패한 필드별 (expected, actual) 매핑).
    """
    failures: dict[str, tuple[Any, Any]] = {}
    for field, expected_value in expected.items():
        actual: Any = result.get(field, _MISSING)  # type: ignore[arg-type]
        if not _check(expected_value, actual):
            failures[field] = (expected_value, actual)
    return (not failures, failures)


def _print_case(
    idx: int,
    total: int,
    case: EvalCase,
    *,
    passed: bool,
    result: CliState | None,
    failures: dict[str, tuple[Any, Any]],
    attempts: int,
    error: str | None,
) -> None:
    """한 케이스의 결과를 출력한다."""
    status = "PASS" if passed else "FAIL"
    note = f" (attempts={attempts})" if attempts > 1 else ""
    print(f"[{idx:02d}/{total:02d}] [{status}] {case['id']} — {case['description']}{note}")
    print(f"     input    : {case['input']}")
    print(f"     expected : {case['expected']}")
    if result is not None:
        # expected에 등장한 필드만 발췌 출력
        actuals = {k: result.get(k, _MISSING) for k in case["expected"]}
        print(f"     actual   : {actuals}")
    if failures:
        print(f"     failed   : {failures}")
    if error is not None:
        print(f"     error    : {error}")
    print()


def run_eval(
    cases: list[EvalCase],
    workflow: Callable[[CliState], CliState],
    *,
    now: str = "",
    max_retries: int = 1,
) -> int:
    """각 케이스를 워크플로우에 통과시키고 expected 어션을 검증한다.

    Args:
        cases: 실행할 케이스들.
        workflow: ``(CliState) -> CliState`` 함수.
        now: 비어있지 않으면 ``patched_now(now)``로 전체 실행을 감싼다.
        max_retries: 어션 FAIL 시 케이스당 재시도 횟수 (기본 1 = 재시도 없음).
            예외는 재시도하지 않고 즉시 FAIL.

    Returns:
        모두 통과면 0, 하나라도 실패면 1.
    """
    total = len(cases)
    pass_count = 0

    with patched_now(now):
        for idx, case in enumerate(cases, start=1):
            result: CliState | None = None
            failures: dict[str, tuple[Any, Any]] = {}
            passed = False
            error: str | None = None
            attempts = 0

            for attempt in range(1, max_retries + 1):
                attempts = attempt
                try:
                    result = workflow(_build_initial_state(case["input"]))
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    break
                passed, failures = _check_case(case["expected"], result)
                if passed:
                    break

            if passed:
                pass_count += 1
            _print_case(
                idx,
                total,
                case,
                passed=passed,
                result=result,
                failures=failures,
                attempts=attempts,
                error=error,
            )

    print(f"결과: {pass_count}/{total} 통과")
    return 0 if pass_count == total else 1
