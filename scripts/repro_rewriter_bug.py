"""쿼리 리라이터 버그 재현 스크립트.

두 가지 실패 모드를 분리해서 측정한다:
1. 단발 짧은 명사 입력에서 응답-형식 출력이 나오는지 ("고객지원" → "...정보를 안내드립니다")
2. 멀티턴 chat_history 활용해 짧은 명사 응답을 완전한 질문으로 풀어쓰는지
   ("고객지원" + chat_history → "고객지원 부서의 평균 급여를 알려줘")
"""

from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.llm import get_chat_model
from src.query_rewriter.prompt import build_rewriter_system_prompt


def rewrite_once(user_query: str, chat_history: list) -> str:
    """rewriter LLM을 직접 호출해 결과 텍스트만 반환."""
    system_prompt = build_rewriter_system_prompt(now=datetime.now())
    llm = get_chat_model()
    response = llm.invoke(
        [SystemMessage(content=system_prompt)]
        + list(chat_history)
        + [HumanMessage(content=user_query)]
    )
    return response.content  # type: ignore[return-value]


def run_case(label: str, user_query: str, chat_history: list, n: int = 5) -> None:
    print(f"\n===== {label} =====")
    print(f"입력: {user_query!r}")
    if chat_history:
        print("chat_history:")
        for m in chat_history:
            kind = "U" if isinstance(m, HumanMessage) else "A"
            print(f"  [{kind}] {m.content}")
    for i in range(1, n + 1):
        out = rewrite_once(user_query, chat_history)
        print(f"  run {i}: {out!r}")


def main() -> None:
    # 케이스 1: 단발 짧은 명사 — 응답-형식 출력이 나오는지
    run_case("CASE 1: 단발 '고객지원' (chat_history 없음)", "고객지원", [], n=5)

    # 케이스 2: 멀티턴 — 부서 안내 후 "고객지원" 단답
    multi_history = [
        HumanMessage(content="부서별 평균급여"),
        AIMessage(content="무슨 부서가 궁금하세요?"),
        HumanMessage(content="무슨 부서가 있는데?"),
        AIMessage(content="고객지원, 인사, 재무, 운영 부서가 있습니다."),
    ]
    run_case("CASE 2: 멀티턴 + '고객지원'", "고객지원", multi_history, n=5)

    # 케이스 3: 비교군 — 정상 동작 확인용
    run_case("CASE 3: '상품 재고 알려줘'", "상품 재고 알려줘", [], n=3)


if __name__ == "__main__":
    main()
