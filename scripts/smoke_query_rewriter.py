"""query_rewriter CLI subprocess 스모크.

scripts.cli.query_rewriter 를 --now 고정 시각으로 subprocess 호출하고,
출력의 'rewritten:' 줄에서 기대 정규식 패턴이 모두 발견되는지 검사한다.
--now 로 상대 날짜 변환은 결정적이며, MAX_RETRIES 로 LLM 표현 편차를 흡수한다.

scripts/Test_query_rewriter.py 를 CLI + subprocess 형태로 대체한다.

실행:
    uv run python -m scripts.smoke_query_rewriter
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import NotRequired, TypedDict

FIXED_NOW = "2026-04-29T14:30"
MAX_RETRIES = 3


class Case(TypedDict):
    """리라이터 스모크 케이스."""

    category: str
    input: str
    expected_patterns: list[str]
    history: NotRequired[list[dict[str, str]]]


CASES: list[Case] = [
    {"category": "일:오늘", "input": "오늘 매출 알려줘", "expected_patterns": [r"2026-04-29"]},
    {"category": "일:어제", "input": "어제 매출 알려줘", "expected_patterns": [r"2026-04-28"]},
    {
        "category": "주:지난주",
        "input": "지난주 매출 알려줘",
        "expected_patterns": [r"2026-04-20", r"2026-04-26"],
    },
    {
        "category": "월:지난달",
        "input": "지난달 매출 알려줘",
        "expected_patterns": [r"2026-03-01", r"2026-03-31"],
    },
    {
        "category": "최근:N일",
        "input": "최근 7일 매출 알려줘",
        "expected_patterns": [r"2026-04-22", r"2026-04-29"],
    },
    {
        "category": "년:작년",
        "input": "작년 매출",
        "expected_patterns": [r"2025-01-01", r"2025-12-31"],
    },
    {
        "category": "분기:1분기",
        "input": "1분기 매출",
        "expected_patterns": [r"2026-01-01", r"2026-03-31"],
    },
    {
        "category": "자연어:N월 N일",
        "input": "4월 17일 매출",
        "expected_patterns": [r"2026-04-17"],
    },
    {
        "category": "coref:번역 결과 → 이거",
        "history": [
            {"role": "human", "content": "Hello, how are you?를 한국어로 번역해줘"},
            {"role": "ai", "content": "안녕하세요, 어떻게 지내세요?"},
        ],
        "input": "이거 일본어로도 번역해줘",
        "expected_patterns": [r"안녕하세요|Hello"],
    },
    {
        "category": "ellipsis:동사 재사용",
        "history": [
            {"role": "human", "content": "어제 매출 알려줘"},
            {"role": "ai", "content": "2026-04-28 매출은 1억원입니다."},
        ],
        "input": "오늘은?",
        "expected_patterns": [r"2026-04-29", r"매출"],
    },
    {
        "category": "독립:번역 → 수학 (오염 없음)",
        "history": [
            {"role": "human", "content": "Hello를 한국어로 번역해줘"},
            {"role": "ai", "content": "안녕하세요"},
        ],
        "input": "3과 7을 더해줘",
        "expected_patterns": [r"3.{0,5}7|7.{0,5}3", r"더해|더하|덧셈|합"],
    },
]


def _parse_rewritten(stdout: str) -> str:
    """CLI stdout에서 'rewritten:' 줄의 값을 추출한다."""
    for line in stdout.splitlines():
        if line.startswith("rewritten"):
            return line.split(":", 1)[1].strip()
    return ""


def run() -> int:
    """모든 케이스를 실행하고 PASS/FAIL을 출력한다."""
    print(f"기준 시각 (--now): {FIXED_NOW}")
    print(f"테스트 케이스: {len(CASES)}건\n")

    pass_count = 0
    for idx, case in enumerate(CASES, start=1):
        cmd = [
            sys.executable,
            "-m",
            "scripts.cli.query_rewriter",
            case["input"],
            "--now",
            FIXED_NOW,
        ]
        history = case.get("history")
        if history:
            cmd += ["--history", json.dumps(history, ensure_ascii=False)]

        rewritten = ""
        missing: list[str] = []
        passed = False
        attempts = 0
        for attempt in range(1, MAX_RETRIES + 1):
            attempts = attempt
            proc = subprocess.run(cmd, capture_output=True, text=True)
            rewritten = _parse_rewritten(proc.stdout)
            missing = [
                p for p in case["expected_patterns"] if not re.search(p, rewritten)
            ]
            passed = proc.returncode == 0 and not missing
            if passed:
                break

        if passed:
            pass_count += 1
        status = "PASS" if passed else "FAIL"
        note = f" (attempts={attempts})" if attempts > 1 else ""
        print(f"[{idx:02d}] [{status}] {case['category']}{note}")
        print(f"     입력  : {case['input']}")
        print(f"     출력  : {rewritten}")
        print(f"     기대  : {case['expected_patterns']}")
        if missing:
            print(f"     누락  : {missing}")
        print()

    total = len(CASES)
    print(f"결과: {pass_count}/{total} 통과")
    return 0 if pass_count == total else 1


if __name__ == "__main__":
    sys.exit(run())
