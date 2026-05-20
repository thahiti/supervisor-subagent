"""query_rewriter 워크플로우 스모크.

`scripts.cli.query_rewriter.rewrite` 를 in-process로 직접 호출하고,
반환 문자열에서 기대 정규식 패턴이 모두 발견되는지 검사한다.
FIXED_NOW 로 상대 날짜 변환은 결정적이며, MAX_RETRIES 로 LLM 표현
편차를 흡수한다. 실제 LLM을 호출하므로 비결정적·유료이며 의도적으로
실행한다.

`scripts/Test_query_rewriter.py` 를 subprocess-free 형태로 대체한다.

실행:
    uv run python -m scripts.smoke_query_rewriter
"""

from __future__ import annotations

import re
import sys
from typing import NotRequired, TypedDict

from dotenv import load_dotenv

load_dotenv()

from scripts.cli._common import CliState, Role, patched_now, to_messages  # noqa: E402
from scripts.cli.query_rewriter import rewrite  # noqa: E402

FIXED_NOW = "2026-04-29T14:30"
MAX_RETRIES = 3


class Case(TypedDict):
    """리라이터 스모크 케이스."""

    category: str
    input: str
    expected_patterns: list[str]
    history: NotRequired[list[tuple[Role, str]]]


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
            ("human", "Hello, how are you?를 한국어로 번역해줘"),
            ("ai", "안녕하세요, 어떻게 지내세요?"),
        ],
        "input": "이거 일본어로도 번역해줘",
        "expected_patterns": [r"안녕하세요|Hello"],
    },
    {
        "category": "ellipsis:동사 재사용",
        "history": [
            ("human", "어제 매출 알려줘"),
            ("ai", "2026-04-28 매출은 1억원입니다."),
        ],
        "input": "오늘은?",
        "expected_patterns": [r"2026-04-29", r"매출"],
    },
    {
        "category": "독립:번역 → 수학 (오염 없음)",
        "history": [
            ("human", "Hello를 한국어로 번역해줘"),
            ("ai", "안녕하세요"),
        ],
        "input": "3과 7을 더해줘",
        "expected_patterns": [r"3.{0,5}7|7.{0,5}3", r"더해|더하|덧셈|합"],
    },
]


def run() -> int:
    """모든 케이스를 in-process로 실행하고 PASS/FAIL을 출력한다."""
    from langchain_core.messages import HumanMessage

    print(f"기준 시각 (FIXED_NOW): {FIXED_NOW}")
    print(f"테스트 케이스: {len(CASES)}건\n")

    pass_count = 0
    for idx, case in enumerate(CASES, start=1):
        history = to_messages(list(case.get("history", [])))
        initial: CliState = {
            "messages": [HumanMessage(content=case["input"])],
            "next_agent": "",
            "chat_history": history,
        }

        rewritten = ""
        missing: list[str] = []
        passed = False
        error: str | None = None
        attempts = 0
        for attempt in range(1, MAX_RETRIES + 1):
            attempts = attempt
            try:
                with patched_now(FIXED_NOW):
                    result = rewrite(initial)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                break
            rewritten = result.get("rewritten", "")
            missing = [
                p for p in case["expected_patterns"] if not re.search(p, rewritten)
            ]
            passed = not missing
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
        if error is not None:
            print(f"     에러  : {error}")
        print()

    total = len(CASES)
    print(f"결과: {pass_count}/{total} 통과")
    return 0 if pass_count == total else 1


if __name__ == "__main__":
    sys.exit(run())
