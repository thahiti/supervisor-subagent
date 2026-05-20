"""query_rewriter 워크플로우 스모크.

`scripts.cli.query_rewriter.rewrite`를 공통 평가 프레임워크
(`scripts.eval.run_eval`)로 호출한다. FIXED_NOW로 상대 날짜 변환은
결정적이며, MAX_RETRIES로 LLM 표현 편차를 흡수한다. 실제 LLM을
호출하므로 비결정적·유료이며 의도적으로 실행한다.

실행:
    uv run python -m scripts.smoke_query_rewriter
"""

from __future__ import annotations

import re
import sys

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import HumanMessage  # noqa: E402

from scripts.cli._common import to_messages  # noqa: E402
from scripts.cli.query_rewriter import rewrite  # noqa: E402
from scripts.eval import EvalCase, run_eval  # noqa: E402

FIXED_NOW = "2026-04-29T14:30"
MAX_RETRIES = 3


CASES: list[EvalCase] = [
    {
        "id": "일:오늘",
        "description": "일:오늘",
        "input": {"messages": [HumanMessage(content="오늘 매출 알려줘")]},
        "expected": {"rewritten": re.compile(r"2026-04-29")},
    },
    {
        "id": "일:어제",
        "description": "일:어제",
        "input": {"messages": [HumanMessage(content="어제 매출 알려줘")]},
        "expected": {"rewritten": re.compile(r"2026-04-28")},
    },
    {
        "id": "주:지난주",
        "description": "주:지난주",
        "input": {"messages": [HumanMessage(content="지난주 매출 알려줘")]},
        "expected": {
            "rewritten": [re.compile(r"2026-04-20"), re.compile(r"2026-04-26")],
        },
    },
    {
        "id": "월:지난달",
        "description": "월:지난달",
        "input": {"messages": [HumanMessage(content="지난달 매출 알려줘")]},
        "expected": {
            "rewritten": [re.compile(r"2026-03-01"), re.compile(r"2026-03-31")],
        },
    },
    {
        "id": "최근:N일",
        "description": "최근:N일",
        "input": {"messages": [HumanMessage(content="최근 7일 매출 알려줘")]},
        "expected": {
            "rewritten": [re.compile(r"2026-04-22"), re.compile(r"2026-04-29")],
        },
    },
    {
        "id": "년:작년",
        "description": "년:작년",
        "input": {"messages": [HumanMessage(content="작년 매출")]},
        "expected": {
            "rewritten": [re.compile(r"2025-01-01"), re.compile(r"2025-12-31")],
        },
    },
    {
        "id": "분기:1분기",
        "description": "분기:1분기",
        "input": {"messages": [HumanMessage(content="1분기 매출")]},
        "expected": {
            "rewritten": [re.compile(r"2026-01-01"), re.compile(r"2026-03-31")],
        },
    },
    {
        "id": "자연어:N월 N일",
        "description": "자연어:N월 N일",
        "input": {"messages": [HumanMessage(content="4월 17일 매출")]},
        "expected": {"rewritten": re.compile(r"2026-04-17")},
    },
    {
        "id": "coref:번역 결과 → 이거",
        "description": "이거 → 직전 번역 결과 복원",
        "input": {
            "messages": [HumanMessage(content="이거 일본어로도 번역해줘")],
            "chat_history": to_messages([
                ("human", "Hello, how are you?를 한국어로 번역해줘"),
                ("ai", "안녕하세요, 어떻게 지내세요?"),
            ]),
        },
        "expected": {"rewritten": re.compile(r"안녕하세요|Hello")},
    },
    {
        "id": "ellipsis:동사 재사용",
        "description": "오늘은? → 직전 동사(매출) 복원 + 오늘 날짜",
        "input": {
            "messages": [HumanMessage(content="오늘은?")],
            "chat_history": to_messages([
                ("human", "어제 매출 알려줘"),
                ("ai", "2026-04-28 매출은 1억원입니다."),
            ]),
        },
        "expected": {
            "rewritten": [re.compile(r"2026-04-29"), re.compile(r"매출")],
        },
    },
    {
        "id": "독립:번역 → 수학 (오염 없음)",
        "description": "독립 질문은 chat_history 무시",
        "input": {
            "messages": [HumanMessage(content="3과 7을 더해줘")],
            "chat_history": to_messages([
                ("human", "Hello를 한국어로 번역해줘"),
                ("ai", "안녕하세요"),
            ]),
        },
        "expected": {
            "rewritten": [
                re.compile(r"3.{0,5}7|7.{0,5}3"),
                re.compile(r"더해|더하|덧셈|합"),
            ],
        },
    },
]


if __name__ == "__main__":
    sys.exit(run_eval(CASES, rewrite, now=FIXED_NOW, max_retries=MAX_RETRIES))
