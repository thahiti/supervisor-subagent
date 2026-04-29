"""쿼리 리라이터 단독 실행 스크립트.

query_rewriter 노드 하나만으로 구성된 작은 서브그래프를 빌드해서, 인라인
테스트 케이스를 하나씩 invoke한다. 각 케이스의 기대 날짜 패턴이 출력
문자열에서 정규식으로 발견되면 통과, 누락되면 실패로 분류한다.

datetime.now()는 FIXED_NOW로 모킹하므로 결과는 결정적이다.

실행:
    uv run python -m scripts.Test_query_rewriter
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from typing import TypedDict
from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from src.query_rewriter import query_rewriter_node
from src.state import State


# 모든 상대 시간 표현은 이 시점을 기준으로 변환된다 (수요일).
FIXED_NOW = datetime(2026, 4, 29, 14, 30)


class TestCase(TypedDict):
    """입력, 기대 패턴, 분류 라벨을 담는 단일 테스트 케이스."""

    category: str
    input: str
    expected_patterns: list[str]


TEST_CASES: list[TestCase] = [
    {
        "category": "상대시간:오늘",
        "input": "오늘 매출 알려줘",
        "expected_patterns": [r"2026-04-29"],
    },
    {
        "category": "상대시간:어제",
        "input": "어제 매출 알려줘",
        "expected_patterns": [r"2026-04-28"],
    },
    {
        "category": "상대시간:지난주",
        "input": "지난주 매출 알려줘",
        "expected_patterns": [r"2026-04-20", r"2026-04-26"],
    },
    {
        "category": "상대시간:이번 주",
        "input": "이번 주 매출 알려줘",
        "expected_patterns": [r"2026-04-27", r"2026-04-29"],
    },
    {
        "category": "상대시간:지난달",
        "input": "지난달 매출 알려줘",
        "expected_patterns": [r"2026-03-01", r"2026-03-31"],
    },
    {
        "category": "상대시간:이번 달",
        "input": "이번 달 매출 알려줘",
        "expected_patterns": [r"2026-04-01", r"2026-04-29"],
    },
    {
        "category": "상대시간:최근 7일",
        "input": "최근 7일 매출 알려줘",
        "expected_patterns": [r"2026-04-22", r"2026-04-29"],
    },
]


def build_subgraph():
    """query_rewriter 노드 하나만 가진 서브그래프를 빌드한다."""
    graph = StateGraph(State)
    graph.add_node("query_rewriter", query_rewriter_node)
    graph.add_edge(START, "query_rewriter")
    graph.add_edge("query_rewriter", END)
    return graph.compile()


def extract_rewritten_text(result: dict) -> str:
    """서브그래프 결과 state에서 마지막 HumanMessage 본문을 추출한다."""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


def check_patterns(text: str, patterns: list[str]) -> tuple[bool, list[str]]:
    """모든 정규식 패턴이 text에 포함되는지 검사하고 누락 패턴을 반환한다."""
    missing = [p for p in patterns if not re.search(p, text)]
    return (not missing, missing)


def run() -> int:
    """모든 테스트 케이스를 실행하고 통과/실패를 출력한다."""
    app = build_subgraph()

    print(f"기준 시각 (mocked): {FIXED_NOW.strftime('%Y-%m-%d %H:%M (%A)')}")
    print(f"테스트 케이스: {len(TEST_CASES)}건\n")

    pass_count = 0
    for idx, tc in enumerate(TEST_CASES, start=1):
        with patch("src.query_rewriter.rewriter.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW

            result = app.invoke({
                "messages": [HumanMessage(content=tc["input"])],
                "next_agent": "",
                "chat_history": [],
            })

        rewritten = extract_rewritten_text(result)
        passed, missing = check_patterns(rewritten, tc["expected_patterns"])

        status = "PASS" if passed else "FAIL"
        if passed:
            pass_count += 1

        print(f"[{idx:02d}] [{status}] {tc['category']}")
        print(f"     입력  : {tc['input']}")
        print(f"     출력  : {rewritten}")
        print(f"     기대  : {tc['expected_patterns']}")
        if missing:
            print(f"     누락  : {missing}")
        print()

    total = len(TEST_CASES)
    print(f"결과: {pass_count}/{total} 통과")
    return 0 if pass_count == total else 1


if __name__ == "__main__":
    sys.exit(run())
