"""query_rewriter + router 워크플로우 스모크.

`scripts.cli.query_rewriter_router.route_trace` 를 in-process로 직접
호출하고, 반환된 (리라이팅, 목적지 노드명) 튜플을 기대값과 결정적으로
비교한다. 실제 LLM을 호출하므로 비결정적·유료이며 의도적으로 실행한다.

실행:
    uv run python -m scripts.smoke_query_rewriter_router
"""

from __future__ import annotations

import sys
from typing import TypedDict

from dotenv import load_dotenv

load_dotenv()

from scripts.cli._common import Role, to_messages  # noqa: E402
from scripts.cli.query_rewriter_router import route_trace  # noqa: E402


class RouteCase(TypedDict):
    """라우팅 스모크 케이스."""

    id: str
    history: list[tuple[Role, str]]
    query: str
    expected: str


CASES: list[RouteCase] = [
    {
        "id": "single-math",
        "history": [],
        "query": "3 곱하기 7은 얼마야?",
        "expected": "math_agent",
    },
    {
        "id": "single-translate",
        "history": [],
        "query": "'안녕하세요'를 영어로 번역해줘",
        "expected": "translate_agent",
    },
    {
        "id": "single-sql",
        "history": [],
        "query": "연봉이 5천만원 이상인 직원은 몇 명이야?",
        "expected": "sql_agent",
    },
    {
        "id": "multiturn-toolcall",
        "history": [
            ("human", "브랜치에서 제품 재고 조사해줘"),
            ("ai", "어떤 브랜치에서 재고를 조사할까요?"),
        ],
        "query": "공장2",
        "expected": "tool_call_agent",
    },
    {
        "id": "multiturn-translate-referent",
        "history": [
            ("human", "'좋은 아침입니다'를 영어로 번역해줘"),
            ("ai", "Good morning."),
        ],
        "query": "이거 다시 일본어로",
        "expected": "translate_agent",
    },
]


def run() -> int:
    """모든 케이스를 in-process로 실행하고 PASS/FAIL을 출력한다."""
    pass_count = 0
    for idx, case in enumerate(CASES, start=1):
        history = to_messages(case["history"])
        rewritten = ""
        actual = ""
        error: str | None = None
        try:
            rewritten, actual = route_trace(case["query"], history)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        passed = error is None and actual == case["expected"]
        if passed:
            pass_count += 1

        status = "PASS" if passed else "FAIL"
        print(f"[{idx:02d}] [{status}] {case['id']}")
        print(f"     query    : {case['query']}")
        print(f"     rewritten: {rewritten}")
        print(f"     expected : {case['expected']}")
        print(f"     actual   : {actual}")
        if error is not None:
            print(f"     error    : {error}")
        print()

    total = len(CASES)
    print(f"결과: {pass_count}/{total} 통과")
    return 0 if pass_count == total else 1


if __name__ == "__main__":
    sys.exit(run())
