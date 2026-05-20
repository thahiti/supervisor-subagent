"""CLI/스모크가 공유하는 예제 입력 테이블 (SSOT).

스모크는 ``CASES``로 import해 검증에 사용한다.
CLI는 ``--example`` 인자로 골라 ``input``만 사용한다 (``expected``는 무시).
스키마는 ``scripts.eval.EvalCase``와 동일하다.
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage

from scripts.cli._common import to_messages
from scripts.eval import EvalCase


REWRITER_EXAMPLES: list[EvalCase] = [
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


ROUTER_EXAMPLES: list[EvalCase] = [
    {
        "id": "single-math",
        "description": "단일턴 수학 → math_agent",
        "input": {"messages": [HumanMessage(content="3 곱하기 7은 얼마야?")]},
        "expected": {"next_node": "math_agent"},
    },
    {
        "id": "single-translate",
        "description": "단일턴 번역 → translate_agent",
        "input": {"messages": [HumanMessage(content="'안녕하세요'를 영어로 번역해줘")]},
        "expected": {"next_node": "translate_agent"},
    },
    {
        "id": "single-sql",
        "description": "단일턴 SQL → sql_agent",
        "input": {
            "messages": [HumanMessage(content="연봉이 5천만원 이상인 직원은 몇 명이야?")],
        },
        "expected": {"next_node": "sql_agent"},
    },
    {
        "id": "multiturn-toolcall",
        "description": "공장2 단답 복원 → tool_call_agent",
        "input": {
            "messages": [HumanMessage(content="공장2")],
            "chat_history": to_messages([
                ("human", "브랜치에서 제품 재고 조사해줘"),
                ("ai", "어떤 브랜치에서 재고를 조사할까요?"),
            ]),
        },
        "expected": {"next_node": "tool_call_agent"},
    },
    {
        "id": "multiturn-translate-referent",
        "description": "이거 다시 일본어로 → translate_agent",
        "input": {
            "messages": [HumanMessage(content="이거 다시 일본어로")],
            "chat_history": to_messages([
                ("human", "'좋은 아침입니다'를 영어로 번역해줘"),
                ("ai", "Good morning."),
            ]),
        },
        "expected": {"next_node": "translate_agent"},
    },
]
