JUDGE_SYSTEM_PROMPT = """당신은 AI 에이전트의 출력 품질을 평가하는 전문 평가자입니다.

주어진 입력, 모범 답안, 실제 출력을 비교하여 각 평가 기준에 대해 1~10점으로 채점하세요.

## 채점 기준
- 1~3: 매우 부족 (핵심 요구사항 미충족)
- 4~6: 보통 (부분적으로 충족하나 개선 필요)
- 7~8: 우수 (대부분 충족, 사소한 개선 가능)
- 9~10: 탁월 (완벽하거나 거의 완벽)

## 평가 기준 설명
- correctness: 결과의 정확성. 모범 답안과 비교하여 핵심 내용이 일치하는지.
- step_reasoning: 풀이 과정의 논리성. 중간 단계가 명확하게 설명되었는지.
- fluency: 문장의 유창성. 문법적으로 자연스럽고 읽기 쉬운지.
- naturalness: 번역의 자연스러움. 원어민이 쓴 것처럼 자연스러운지.
- formality: 격식체 적절성. 비즈니스/공식 상황에 맞는 어조인지.

## 응답 형식
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요.

```json
{{
  "scores": {{
    "<기준명>": {{"score": <1-10>, "reason": "<근거>"}},
    ...
  }},
  "overall_score": <기준별 점수의 평균, 소수점 1자리>,
  "summary": "<전체 평가 요약>"
}}
```"""


JUDGE_USER_PROMPT_TEMPLATE = """## 평가 대상

**입력**: {input}

**모범 답안**: {reference_answer}

**실제 출력**: {actual_output}

## 평가 기준
다음 기준에 대해 각각 채점하세요: {criteria}"""


def build_judge_user_prompt(
    input_text: str,
    reference_answer: str,
    actual_output: str,
    criteria: list[str],
) -> str:
    """Judge에게 전달할 user 프롬프트를 생성한다.

    Args:
        input_text: 테스트 케이스 입력
        reference_answer: 모범 답안
        actual_output: 에이전트의 실제 출력
        criteria: 평가 기준 목록

    Returns:
        포맷된 user 프롬프트
    """
    return JUDGE_USER_PROMPT_TEMPLATE.format(
        input=input_text,
        reference_answer=reference_answer,
        actual_output=actual_output,
        criteria=", ".join(criteria),
    )
