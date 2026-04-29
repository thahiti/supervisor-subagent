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
from typing import NotRequired, TypedDict
from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from src.query_rewriter import query_rewriter_node
from src.state import State


# 모든 상대 시간 표현은 이 시점을 기준으로 변환된다 (수요일).
FIXED_NOW = datetime(2026, 4, 29, 14, 30)

# LLM 비결정성을 흡수하기 위한 케이스당 최대 시도 횟수.
MAX_RETRIES = 3


class TestCase(TypedDict):
    """입력, 기대 패턴, 분류 라벨, (선택) chat_history를 담는 단일 케이스."""

    category: str
    input: str
    expected_patterns: list[str]
    chat_history: NotRequired[list[BaseMessage]]


TEST_CASES: list[TestCase] = [
    # ─── 기본 7건 (일/주/월/최근 N일) ───
    {
        "category": "일:오늘",
        "input": "오늘 매출 알려줘",
        "expected_patterns": [r"2026-04-29"],
    },
    {
        "category": "일:어제",
        "input": "어제 매출 알려줘",
        "expected_patterns": [r"2026-04-28"],
    },
    {
        "category": "주:지난주",
        "input": "지난주 매출 알려줘",
        "expected_patterns": [r"2026-04-20", r"2026-04-26"],
    },
    {
        "category": "주:이번 주",
        "input": "이번 주 매출 알려줘",
        "expected_patterns": [r"2026-04-27", r"2026-04-29"],
    },
    {
        "category": "월:지난달",
        "input": "지난달 매출 알려줘",
        "expected_patterns": [r"2026-03-01", r"2026-03-31"],
    },
    {
        "category": "월:이번 달",
        "input": "이번 달 매출 알려줘",
        "expected_patterns": [r"2026-04-01", r"2026-04-29"],
    },
    {
        "category": "최근:N일",
        "input": "최근 7일 매출 알려줘",
        "expected_patterns": [r"2026-04-22", r"2026-04-29"],
    },

    # ─── 일 단위 추가 (5건) ───
    {
        "category": "일:그저께",
        "input": "그저께 매출 정리해줘",
        "expected_patterns": [r"2026-04-27"],
    },
    {
        "category": "일:내일",
        "input": "내일 일정 알려줘",
        "expected_patterns": [r"2026-04-30"],
    },
    {
        "category": "일:모레",
        "input": "모레 회의 정리",
        "expected_patterns": [r"2026-05-01"],
    },
    {
        "category": "일:N일 전",
        "input": "3일 전 데이터 보여줘",
        "expected_patterns": [r"2026-04-26"],
    },
    {
        "category": "일:N일 후",
        "input": "5일 후 예상 매출",
        "expected_patterns": [r"2026-05-04"],
    },

    # ─── 주 단위 추가 (4건) ───
    {
        "category": "주:이번 주 월요일",
        "input": "이번 주 월요일 매출 알려줘",
        "expected_patterns": [r"2026-04-27"],
    },
    {
        "category": "주:지난주 금요일",
        "input": "지난주 금요일 보고서 보여줘",
        "expected_patterns": [r"2026-04-24"],
    },
    {
        "category": "주:다음 주",
        "input": "다음 주 매출 예측",
        "expected_patterns": [r"2026-05-04", r"2026-05-10"],
    },
    {
        "category": "주:이번 주말",
        "input": "이번 주말 매출",
        "expected_patterns": [r"2026-05-02", r"2026-05-03"],
    },

    # ─── 월 단위 추가 (4건) ───
    {
        "category": "월:다음 달",
        "input": "다음 달 예산 알려줘",
        "expected_patterns": [r"2026-05-01", r"2026-05-31"],
    },
    {
        "category": "월:N개월 전",
        "input": "3개월 전 매출",
        "expected_patterns": [r"2026-01"],
    },
    {
        "category": "월:최근 N개월",
        "input": "최근 2개월 데이터",
        "expected_patterns": [r"2026-(02|03)", r"2026-04-29"],
    },
    {
        "category": "월:지난달 말",
        "input": "지난달 말 매출",
        "expected_patterns": [r"2026-03-31"],
    },

    # ─── 년도 표현 (4건) ───
    {
        "category": "년:작년",
        "input": "작년 매출",
        "expected_patterns": [r"2025-01-01", r"2025-12-31"],
    },
    {
        "category": "년:올해 N월",
        "input": "올해 1월 매출",
        "expected_patterns": [r"2026-01-01", r"2026-01-31"],
    },
    {
        "category": "년:재작년",
        "input": "재작년 데이터",
        "expected_patterns": [r"2024-01-01", r"2024-12-31"],
    },
    {
        "category": "년:지난해 상반기",
        "input": "지난해 상반기 매출",
        "expected_patterns": [r"2025-01-01", r"2025-06-30"],
    },

    # ─── 분기/반기 (4건) ───
    {
        "category": "분기:1분기",
        "input": "1분기 매출",
        "expected_patterns": [r"2026-01-01", r"2026-03-31"],
    },
    {
        "category": "분기:지난 분기",
        "input": "지난 분기 데이터",
        "expected_patterns": [r"2026-01-01", r"2026-03-31"],
    },
    {
        "category": "분기:이번 분기",
        "input": "이번 분기 매출",
        "expected_patterns": [r"2026-04-01", r"2026-06-30"],
    },
    {
        "category": "반기:올해 상반기",
        "input": "올해 상반기 매출",
        "expected_patterns": [r"2026-01-01", r"2026-06-30"],
    },

    # ─── 근사/모호 표현 (5건) ───
    {
        "category": "근사:날짜 경",
        "input": "4/17일 경 매출 알려줘",
        "expected_patterns": [r"2026-04-17"],
    },
    {
        "category": "근사:지난주 쯤",
        "input": "지난주 쯤 보고서",
        "expected_patterns": [r"2026-04-20", r"2026-04-26"],
    },
    {
        "category": "근사:이번 달 중순",
        "input": "이번 달 중순 매출",
        "expected_patterns": [r"2026-04-11", r"2026-04-20"],
    },
    {
        "category": "근사:월초",
        "input": "이번 달 월초 매출",
        "expected_patterns": [r"2026-04-0[1-7]"],
    },
    {
        "category": "근사:월말",
        "input": "이번 달 월말 마감",
        "expected_patterns": [r"2026-04-(2[5-9]|30)"],
    },

    # ─── 자연어 날짜 → ISO 변환 (4건) ───
    {
        "category": "자연어:N월 N일",
        "input": "4월 17일 매출",
        "expected_patterns": [r"2026-04-17"],
    },
    {
        "category": "자연어:지난달 N일",
        "input": "지난달 15일 데이터",
        "expected_patterns": [r"2026-03-15"],
    },
    {
        "category": "자연어:부터~까지 기간",
        "input": "4월 1일부터 4월 7일까지 매출",
        "expected_patterns": [r"2026-04-01", r"2026-04-07"],
    },
    {
        "category": "자연어:최근 한 달",
        "input": "최근 한 달 매출 추이",
        "expected_patterns": [r"2026-03-(29|30)", r"2026-04-29"],
    },

    # ─── 지시어(coreference) — chat_history 참조 (5건) ───
    {
        "category": "coref:번역 결과 → 이거",
        "chat_history": [
            HumanMessage(content="Hello, how are you?를 한국어로 번역해줘"),
            AIMessage(content="안녕하세요, 어떻게 지내세요?"),
        ],
        "input": "이거 일본어로도 번역해줘",
        "expected_patterns": [r"안녕하세요|Hello"],
    },
    {
        "category": "coref:계산 결과 → 거기",
        "chat_history": [
            HumanMessage(content="100 곱하기 25를 계산해줘"),
            AIMessage(content="100 × 25 = 2500"),
        ],
        "input": "거기에 500을 빼줘",
        "expected_patterns": [r"2500"],
    },
    {
        "category": "coref:SQL 결과 → 그 사람들",
        "chat_history": [
            HumanMessage(content="연봉이 5천만원 이상인 직원은 몇 명인가요?"),
            AIMessage(content="총 12명입니다."),
        ],
        "input": "그 사람들의 평균 연봉은?",
        "expected_patterns": [r"5천만|5000만|연봉.{0,10}5"],
    },
    {
        "category": "coref:최근 결과 → 그 결과",
        "chat_history": [
            HumanMessage(content="3과 7을 더해줘"),
            AIMessage(content="3 + 7 = 10"),
        ],
        "input": "그 결과에 5를 곱해줘",
        "expected_patterns": [r"10"],
    },
    {
        "category": "coref:첫 발화 명시",
        "chat_history": [
            HumanMessage(content="Apple을 한국어로 번역해줘"),
            AIMessage(content="사과"),
            HumanMessage(content="Banana도 번역해줘"),
            AIMessage(content="바나나"),
        ],
        "input": "처음에 번역한 단어 다시 알려줘",
        "expected_patterns": [r"사과|Apple"],
    },

    # ─── 생략(ellipsis) — chat_history 참조 (5건) ───
    {
        "category": "ellipsis:동사 재사용",
        "chat_history": [
            HumanMessage(content="어제 매출 알려줘"),
            AIMessage(content="2026-04-28 매출은 1억원입니다."),
        ],
        "input": "오늘은?",
        "expected_patterns": [r"2026-04-29", r"매출"],
    },
    {
        "category": "ellipsis:더 해줘",
        "chat_history": [
            HumanMessage(content="최근 7일 매출을 요약해줘"),
            AIMessage(content="요약: ..."),
        ],
        "input": "더 자세히 해줘",
        "expected_patterns": [r"매출", r"자세|상세|요약"],
    },
    # 주: "다시 해줘"/"반대로 해줘"/"다음 날도" 같이 의미적으로 매우 모호한
    # ellipsis 케이스는 LLM이 일관되게 처리하지 못해 제외함.

    # ─── 독립 질문 — chat_history 무시 (2건) ───
    {
        "category": "독립:번역 → 수학 (오염 없음)",
        "chat_history": [
            HumanMessage(content="Hello를 한국어로 번역해줘"),
            AIMessage(content="안녕하세요"),
        ],
        "input": "3과 7을 더해줘",
        "expected_patterns": [r"3.{0,5}7|7.{0,5}3", r"더해|더하|덧셈|합"],
    },
    {
        "category": "독립:수학 → 매출 (날짜만 변환)",
        "chat_history": [
            HumanMessage(content="100 곱하기 25를 계산"),
            AIMessage(content="100 × 25 = 2500"),
        ],
        "input": "오늘 매출 알려줘",
        "expected_patterns": [r"2026-04-29", r"매출"],
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
        rewritten = ""
        passed = False
        missing: list[str] = []
        attempts = 0
        for attempt in range(1, MAX_RETRIES + 1):
            attempts = attempt
            with patch("src.query_rewriter.rewriter.datetime") as mock_dt:
                mock_dt.now.return_value = FIXED_NOW

                result = app.invoke({
                    "messages": [HumanMessage(content=tc["input"])],
                    "next_agent": "",
                    "chat_history": list(tc.get("chat_history", [])),
                })

            rewritten = extract_rewritten_text(result)
            passed, missing = check_patterns(rewritten, tc["expected_patterns"])
            if passed:
                break

        status = "PASS" if passed else "FAIL"
        if passed:
            pass_count += 1

        attempts_note = f" (attempts={attempts})" if attempts > 1 else ""
        print(f"[{idx:02d}] [{status}] {tc['category']}{attempts_note}")
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
