"""쿼리 리라이터 프롬프트 정의."""

from datetime import datetime, timedelta


def _format_dictionary(dictionary: dict[str, str]) -> str:
    """용어 사전을 프롬프트에 삽입할 문자열로 변환한다."""
    if not dictionary:
        return "없음"
    return "\n".join(f"- {term} → {definition}" for term, definition in dictionary.items())


def _compute_reference_dates(now: datetime) -> dict[str, str]:
    """상대적 시간 표현 변환에 필요한 날짜들을 ISO 문자열로 미리 계산한다.

    LLM이 주 경계나 월 말일을 직접 산술하지 않도록 사전 계산된 값을 프롬프트에
    주입한다. weekday는 월=0~일=6 기준이다.
    """
    today = now.date()
    yesterday = today - timedelta(days=1)
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    last_sunday = this_monday - timedelta(days=1)
    this_month_first = today.replace(day=1)
    last_month_last = this_month_first - timedelta(days=1)
    last_month_first = last_month_last.replace(day=1)
    return {
        "today": today.isoformat(),
        "yesterday": yesterday.isoformat(),
        "this_monday": this_monday.isoformat(),
        "last_monday": last_monday.isoformat(),
        "last_sunday": last_sunday.isoformat(),
        "this_month_first": this_month_first.isoformat(),
        "last_month_first": last_month_first.isoformat(),
        "last_month_last": last_month_last.isoformat(),
    }


def build_rewriter_system_prompt(
    now: datetime,
    dictionary: dict[str, str] | None = None,
) -> str:
    """현재 시각과 용어 사전을 반영한 쿼리 리라이터 시스템 프롬프트를 생성한다.

    Args:
        now: 현재 시각. 상대적 시간 표현 해석의 기준이 된다.
        dictionary: 용어 사전. None이면 용어 치환 규칙이 "없음"으로 표시.

    Returns:
        시스템 프롬프트 문자열.
    """
    refs = _compute_reference_dates(now)
    return REWRITER_SYSTEM_PROMPT.format(
        now=now.strftime("%Y-%m-%d %H:%M (%A)"),
        dictionary=_format_dictionary(dictionary or {}),
        **refs,
    )


REWRITER_SYSTEM_PROMPT = """당신은 사용자 쿼리를 명확하게 재작성하는 전처리기입니다.

## 현재 시각
{now}

## 역할
아래 3가지 규칙을 적용하여 사용자의 마지막 메시지를 재작성하세요.
재작성이 불필요하면 원본 메시지를 그대로 반환하세요.

### 1. 상대적 시간 표현 → 구체적 날짜/기간
모든 날짜는 반드시 `YYYY-MM-DD` 형식으로 출력하고, 기간은 `YYYY-MM-DD~YYYY-MM-DD` 형식으로 출력하세요.
"YYYY년 M월 D일" 같은 자연어 형식이나 "YYYY/MM/DD" 같은 다른 구분자는 절대 사용하지 마세요.

아래 표는 현재 시각 기준으로 미리 계산된 값입니다. 직접 산술 계산하지 말고 그대로 사용하세요.

| 상대 표현 | 변환 결과 |
|-----------|-----------|
| 오늘 | {today} |
| 어제 | {yesterday} |
| 이번 주 | {this_monday}~{today} |
| 지난주 | {last_monday}~{last_sunday} |
| 이번 달 | {this_month_first}~{today} |
| 지난달 | {last_month_first}~{last_month_last} |

"최근 N일"은 N의 값에 따라 (오늘 - N일) ~ 오늘로 직접 계산하세요. 오늘은 {today}입니다.

### 2. 대화 맥락 보충
이전 턴들의 대화(시스템 메시지 다음에 주어지는 사용자/어시스턴트 메시지 쌍)는 큐레이션된 과거 대화입니다. 이를 참고하여 현재 사용자 메시지의 모호한 지시어를 구체적으로 바꿔주세요:
- "이거", "그거", "저거" → 지칭하는 대상을 명시
- "더 해줘", "다시 해줘" → 이전에 수행한 작업을 구체적으로 명시
- "반대로 해줘" → 이전 작업의 반대 방향을 명시
- 새로운 독립 질문이면 맥락 보충 없이 그대로 유지

### 3. 용어 사전 치환
아래 사전에 정의된 용어가 쿼리에 포함되면 괄호 안의 정의로 치환하세요:
{dictionary}

## 출력 형식
재작성된 쿼리만 출력하세요. 설명이나 부가 텍스트를 포함하지 마세요."""
