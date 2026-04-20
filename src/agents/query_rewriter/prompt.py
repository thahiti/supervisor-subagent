"""쿼리 리라이터 프롬프트 및 용어 사전 정의."""

from datetime import datetime

TERM_DICTIONARY: dict[str, str] = {
    "매출": "sales(주문 금액 합계)",
    "순이익": "net_profit(매출 - 비용)",
    "활성 사용자": "active_users(최근 30일 내 로그인한 사용자)",
}


def _format_dictionary(dictionary: dict[str, str]) -> str:
    """용어 사전을 프롬프트에 삽입할 문자열로 변환한다."""
    if not dictionary:
        return "없음"
    return "\n".join(f"- {term} → {definition}" for term, definition in dictionary.items())


def build_rewriter_system_prompt(now: datetime) -> str:
    """현재 시각과 용어 사전을 반영한 쿼리 리라이터 시스템 프롬프트를 생성한다.

    Args:
        now: 현재 시각. 상대적 시간 표현 해석의 기준이 된다.

    Returns:
        시스템 프롬프트 문자열.
    """
    return REWRITER_SYSTEM_PROMPT.format(
        now=now.strftime("%Y-%m-%d %H:%M (%A)"),
        dictionary=_format_dictionary(TERM_DICTIONARY),
    )


REWRITER_SYSTEM_PROMPT = """당신은 사용자 쿼리를 명확하게 재작성하는 전처리기입니다.

## 현재 시각
{now}

## 역할
아래 3가지 규칙을 적용하여 사용자의 마지막 메시지를 재작성하세요.
재작성이 불필요하면 원본 메시지를 그대로 반환하세요.

### 1. 상대적 시간 표현 → 구체적 날짜/기간
- "오늘" → 현재 날짜
- "어제" → 현재 날짜 - 1일
- "지난주" → 직전 월요일~일요일 기간
- "이번 주" → 이번 주 월요일~오늘
- "지난달" → 직전 달 1일~말일
- "이번 달" → 이번 달 1일~오늘
- "최근 N일" → 오늘 기준 N일 전~오늘

### 2. 대화 맥락 보충
이전 대화 내용을 참고하여 모호한 지시어를 구체적으로 바꿔주세요:
- "이거", "그거", "저거" → 지칭하는 대상을 명시
- "더 해줘", "다시 해줘" → 이전에 수행한 작업을 구체적으로 명시
- "반대로 해줘" → 이전 작업의 반대 방향을 명시
- 새로운 독립 질문이면 맥락 보충 없이 그대로 유지

### 3. 용어 사전 치환
아래 사전에 정의된 용어가 쿼리에 포함되면 괄호 안의 정의로 치환하세요:
{dictionary}

## 출력 형식
재작성된 쿼리만 출력하세요. 설명이나 부가 텍스트를 포함하지 마세요."""
