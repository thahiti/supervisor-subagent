"""query_rewriter + router CLI subprocess 스모크.

scripts.cli.query_rewriter_router 를 subprocess로 호출하고,
출력의 'destination:' 줄을 기대 라우팅 목적지와 결정적으로 비교한다.
파이프라인은 실제 LLM을 호출하므로 비결정적·유료이며 의도적으로 실행한다.

실행:
    uv run python -m scripts.smoke_query_rewriter_router
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TypedDict


class RouteCase(TypedDict):
    """라우팅 스모크 케이스."""

    id: str
    history: list[dict[str, str]]
    query: str
    expected: str


CASES: list[RouteCase] = [
    {"id": "single-math", "history": [], "query": "3 곱하기 7은 얼마야?", "expected": "math_agent"},
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
            {"role": "human", "content": "브랜치에서 제품 재고 조사해줘"},
            {"role": "ai", "content": "어떤 브랜치에서 재고를 조사할까요?"},
        ],
        "query": "공장2",
        "expected": "tool_call_agent",
    },
    {
        "id": "multiturn-translate-referent",
        "history": [
            {"role": "human", "content": "'좋은 아침입니다'를 영어로 번역해줘"},
            {"role": "ai", "content": "Good morning."},
        ],
        "query": "이거 다시 일본어로",
        "expected": "translate_agent",
    },
]


def _parse_destination(stdout: str) -> str:
    """CLI stdout에서 'destination:' 줄의 값을 추출한다."""
    for line in stdout.splitlines():
        if line.startswith("destination"):
            return line.split(":", 1)[1].strip()
    return "<no destination line>"


def run() -> int:
    """모든 케이스를 실행하고 PASS/FAIL을 출력한다."""
    pass_count = 0
    for idx, case in enumerate(CASES, start=1):
        cmd = [
            sys.executable,
            "-m",
            "scripts.cli.query_rewriter_router",
            case["query"],
        ]
        if case["history"]:
            cmd += ["--history", json.dumps(case["history"], ensure_ascii=False)]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        actual = _parse_destination(proc.stdout)
        passed = proc.returncode == 0 and actual == case["expected"]
        if passed:
            pass_count += 1

        status = "PASS" if passed else "FAIL"
        print(f"[{idx:02d}] [{status}] {case['id']}")
        print(f"     query   : {case['query']}")
        print(f"     expected: {case['expected']}")
        print(f"     actual  : {actual}")
        if proc.returncode != 0:
            print(f"     stderr  : {proc.stderr.strip()}")
        print()

    total = len(CASES)
    print(f"결과: {pass_count}/{total} 통과")
    return 0 if pass_count == total else 1


if __name__ == "__main__":
    sys.exit(run())
