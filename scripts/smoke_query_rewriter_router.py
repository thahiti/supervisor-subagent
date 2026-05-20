"""query_rewriter + router 워크플로우 스모크.

`scripts.cli.query_rewriter_router.route_trace`를 공통 평가
프레임워크(`scripts.eval.run_eval`)로 호출한다. 실제 LLM을 호출하므로
비결정적·유료이며 의도적으로 실행한다.

실행:
    uv run python -m scripts.smoke_query_rewriter_router
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import HumanMessage  # noqa: E402

from scripts.cli._common import to_messages  # noqa: E402
from scripts.cli.query_rewriter_router import route_trace  # noqa: E402
from scripts.eval import EvalCase, run_eval  # noqa: E402


CASES: list[EvalCase] = [
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


if __name__ == "__main__":
    sys.exit(run_eval(CASES, route_trace))
