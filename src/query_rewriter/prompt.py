"""쿼리 리라이터 프롬프트 정의."""

from datetime import date, datetime, timedelta


WEEKDAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]


def _format_dictionary(dictionary: dict[str, str]) -> str:
    """용어 사전을 프롬프트에 삽입할 문자열로 변환한다."""
    if not dictionary:
        return "없음"
    return "\n".join(f"- {term} → {definition}" for term, definition in dictionary.items())


def _format_weekday_table(monday: date) -> str:
    """월요일 기준 7일간의 요일=날짜 매핑 문자열."""
    return ", ".join(
        f"{WEEKDAY_NAMES[i]}={monday + timedelta(days=i)}" for i in range(7)
    )


def _compute_reference_dates(now: datetime) -> dict[str, str]:
    """상대적 시간 표현 변환에 필요한 날짜들을 ISO 문자열로 미리 계산한다."""
    today = now.date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    day_after_tomorrow = today + timedelta(days=2)
    day_before_yesterday = today - timedelta(days=2)

    # 년
    this_year_start = today.replace(month=1, day=1)
    this_year_end = today.replace(month=12, day=31)
    last_year_start = today.replace(year=today.year - 1, month=1, day=1)
    last_year_end = today.replace(year=today.year - 1, month=12, day=31)

    # 주 (월=0~일=6)
    this_monday = today - timedelta(days=today.weekday())
    this_saturday = this_monday + timedelta(days=5)
    this_sunday = this_monday + timedelta(days=6)
    last_monday = this_monday - timedelta(days=7)
    last_sunday = this_monday - timedelta(days=1)
    next_monday = this_monday + timedelta(days=7)
    next_sunday = next_monday + timedelta(days=6)

    # 월
    this_month_first = today.replace(day=1)
    last_month_last = this_month_first - timedelta(days=1)
    last_month_first = last_month_last.replace(day=1)
    this_month_mid_start = this_month_first.replace(day=11)
    this_month_mid_end = this_month_first.replace(day=20)

    # 분기 (Q1=1-3, Q2=4-6, Q3=7-9, Q4=10-12)
    q1_start = today.replace(month=1, day=1)
    q1_end = today.replace(month=3, day=31)
    q2_start = today.replace(month=4, day=1)
    q2_end = today.replace(month=6, day=30)
    q3_start = today.replace(month=7, day=1)
    q3_end = today.replace(month=9, day=30)
    q4_start = today.replace(month=10, day=1)
    q4_end = today.replace(month=12, day=31)

    quarter = (today.month - 1) // 3 + 1
    quarter_ranges = [(q1_start, q1_end), (q2_start, q2_end), (q3_start, q3_end), (q4_start, q4_end)]
    this_q_start, this_q_end = quarter_ranges[quarter - 1]
    if quarter == 1:
        last_q_start = today.replace(year=today.year - 1, month=10, day=1)
        last_q_end = today.replace(year=today.year - 1, month=12, day=31)
    else:
        last_q_start, last_q_end = quarter_ranges[quarter - 2]

    # 상반기/하반기
    h1_start = q1_start
    h1_end = q2_end
    h2_start = q3_start
    h2_end = q4_end

    # 최근 한 달 (30일 윈도우)
    one_month_ago = today - timedelta(days=30)

    return {
        "today": today.isoformat(),
        "yesterday": yesterday.isoformat(),
        "tomorrow": tomorrow.isoformat(),
        "day_after_tomorrow": day_after_tomorrow.isoformat(),
        "day_before_yesterday": day_before_yesterday.isoformat(),
        "this_year_start": this_year_start.isoformat(),
        "this_year_end": this_year_end.isoformat(),
        "last_year_start": last_year_start.isoformat(),
        "last_year_end": last_year_end.isoformat(),
        "this_monday": this_monday.isoformat(),
        "this_saturday": this_saturday.isoformat(),
        "this_sunday": this_sunday.isoformat(),
        "this_weekday_table": _format_weekday_table(this_monday),
        "last_monday": last_monday.isoformat(),
        "last_sunday": last_sunday.isoformat(),
        "last_weekday_table": _format_weekday_table(last_monday),
        "next_monday": next_monday.isoformat(),
        "next_sunday": next_sunday.isoformat(),
        "this_month_first": this_month_first.isoformat(),
        "last_month_first": last_month_first.isoformat(),
        "last_month_last": last_month_last.isoformat(),
        "this_month_mid_start": this_month_mid_start.isoformat(),
        "this_month_mid_end": this_month_mid_end.isoformat(),
        "q1_start": q1_start.isoformat(),
        "q1_end": q1_end.isoformat(),
        "q2_start": q2_start.isoformat(),
        "q2_end": q2_end.isoformat(),
        "q3_start": q3_start.isoformat(),
        "q3_end": q3_end.isoformat(),
        "q4_start": q4_start.isoformat(),
        "q4_end": q4_end.isoformat(),
        "this_q_start": this_q_start.isoformat(),
        "this_q_end": this_q_end.isoformat(),
        "last_q_start": last_q_start.isoformat(),
        "last_q_end": last_q_end.isoformat(),
        "h1_start": h1_start.isoformat(),
        "h1_end": h1_end.isoformat(),
        "h2_start": h2_start.isoformat(),
        "h2_end": h2_end.isoformat(),
        "one_month_ago": one_month_ago.isoformat(),
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

아래 표는 현재 시각 기준으로 미리 계산된 값입니다. 표의 "상대 표현" 열과 사용자 메시지의 표현이 **정확히 동일한 의미일 때만** 변환 결과를 그대로 사용하세요.

**중요**: 사용자 표현이 표 항목과 다른 시간 표현(월/일/요일 등)과 결합되어 있으면, 표 항목 전체를 그대로 쓰지 말고 결합된 의미로 좁혀 직접 계산하세요. 예시:
- "올해 1월" → 2026-01-01~2026-01-31 (올해 전체 아님)
- "작년 5월" → 2025-05-01~2025-05-31 (작년 전체 아님)
- "이번 달 15일" → 2026-04-15 (이번 달 전체 아님)
- "지난주 금요일" → 표의 "지난주 요일별"에서 금요일에 해당하는 단일 날짜

| 상대 표현 | 변환 결과 |
|-----------|-----------|
| 오늘 | {today} |
| 어제 | {yesterday} |
| 그저께 | {day_before_yesterday} |
| 내일 | {tomorrow} |
| 모레 | {day_after_tomorrow} |
| 올해 | {this_year_start}~{this_year_end} |
| 작년 | {last_year_start}~{last_year_end} |
| 이번 주 | {this_monday}~{today} |
| 이번 주 요일별 | {this_weekday_table} |
| 이번 주말 | {this_saturday}~{this_sunday} |
| 지난주 | {last_monday}~{last_sunday} |
| 지난주 요일별 | {last_weekday_table} |
| 다음 주 | {next_monday}~{next_sunday} |
| 이번 달 | {this_month_first}~{today} |
| 이번 달 중순 | {this_month_mid_start}~{this_month_mid_end} |
| 지난달 | {last_month_first}~{last_month_last} |
| 1분기 | {q1_start}~{q1_end} |
| 2분기 | {q2_start}~{q2_end} |
| 3분기 | {q3_start}~{q3_end} |
| 4분기 | {q4_start}~{q4_end} |
| 이번 분기 | {this_q_start}~{this_q_end} |
| 지난 분기 | {last_q_start}~{last_q_end} |
| 상반기 | {h1_start}~{h1_end} |
| 하반기 | {h2_start}~{h2_end} |
| 최근 한 달 | {one_month_ago}~{today} |

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
