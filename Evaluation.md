# Evaluation

## Overview

이 프로젝트의 평가 시스템은 **LLM-as-Judge** 방식으로 각 에이전트의 출력 품질을 자동 평가한다. 별도의 Judge LLM(gpt-4o)이 에이전트의 실제 출력을 모범 답안과 비교하여 여러 기준에 대해 1~10점으로 채점한다.

### LLM-as-Judge를 선택한 이유

- **수학 에이전트**: 숫자 정확도는 rule-based로 검증 가능하지만, "풀이 과정이 논리적인가"는 LLM 판단이 필요
- **번역 에이전트**: 의미 전달·유창성·자연스러움은 키워드 매칭으로 평가하기 어려움
- **일관된 프레임워크**: 에이전트 유형에 관계없이 동일한 평가 파이프라인을 사용하여 기준만 교체하면 됨

## 구조

```
evals/
├── run.py              # CLI 엔트리포인트
├── runner.py           # 테스트 실행 오케스트레이션
├── judge.py            # Judge LLM 호출 + 응답 파싱
├── prompts.py          # Judge 시스템/유저 프롬프트 템플릿
└── types.py            # TypedDict 정의

res/
└── test_cases.yaml     # 테스트 케이스 + 평가 설정
```

## 실행 흐름

```
1. res/ 하위 YAML 파일 수집 → eval_config + test_cases 파싱
2. 각 test_case에 대해:
   a. registry에서 target_agent의 wrapper 함수 조회
   b. State 구성 (input → HumanMessage, state_overrides 병합)
   c. wrapper 직접 호출 → actual_output 획득
   d. (input, reference_answer, actual_output, criteria) → Judge LLM 호출
   e. Judge 응답 JSON 파싱 → 기준별 점수 + overall_score
   f. pass_threshold 기준 PASS/FAIL 판정
3. 콘솔 리포트 출력
```

### wrapper 직접 호출 방식

평가 시 전체 그래프(Supervisor → Agent)를 실행하지 않고, `registry.get(target_agent).wrapper`를 직접 호출한다.

이 설계의 이점:
- **격리된 평가**: Supervisor의 라우팅 오류가 subagent 평가에 영향을 미치지 않음
- **빠른 피드백**: 전체 파이프라인 대비 실행 시간 단축
- **명확한 책임 분리**: 각 에이전트의 출력 품질만 독립적으로 측정

## 테스트 케이스 작성 (`res/*.yaml`)

### 스키마

```yaml
eval_config:                       # 평가 전역 설정 (한 파일에만 필요)
  judge_model: "gpt-4o"
  judge_temperature: 0.0
  pass_threshold: 7.0
  agent_criteria:                  # 에이전트 유형별 기본 평가 기준
    math:
      - correctness
      - step_reasoning
    translate:
      - correctness
      - fluency
      - naturalness

test_cases:
  - id: "math_simple_add"          # 고유 식별자
    description: "단순 덧셈"       # 사람이 읽을 수 있는 설명
    target_agent: "math"           # registry에 등록된 에이전트 이름
    input: "3과 7을 더해주세요"     # 에이전트에 전달할 입력
    reference_answer: "3 + 7 = 10" # Judge가 비교할 모범 답안
    state_overrides:               # (선택) State 필드 override
      completed_agents: ["translate"]
    eval_criteria:                 # (선택) 케이스 레벨 기준 override
      - correctness
      - formality
```

### 필드 상세

| 필드 | 필수 | 설명 |
|------|------|------|
| `id` | O | 테스트 케이스 고유 식별자. `--filter` 옵션에 사용 |
| `description` | O | 콘솔 출력에 표시되는 설명 |
| `target_agent` | O | registry에 등록된 에이전트 이름 |
| `input` | O | 에이전트에 전달할 사용자 입력 |
| `reference_answer` | O | Judge가 비교할 모범 답안 |
| `state_overrides` | X | State에 병합할 추가 필드. 특정 상황 시뮬레이션에 유용 |
| `eval_criteria` | X | 이 케이스에만 적용할 평가 기준. 미지정 시 `agent_criteria`에서 조회 |

### 다중 파일 지원

`res/` 하위의 모든 `*.yaml`/`*.yml` 파일을 재귀적으로 수집한다. 에이전트별·카테고리별로 파일을 분리할 수 있다.

```
res/
├── config.yaml          # eval_config만 정의
├── math_basic.yaml      # 수학 기본 테스트
├── math_edge.yaml       # 수학 엣지 케이스
└── translate.yaml       # 번역 테스트
```

`eval_config`는 첫 번째로 발견된 파일의 것을 사용한다. `test_cases`는 모든 파일에서 병합한다.

## 평가 기준 (Criteria)

### 기본 제공 기준

| 기준 | 설명 | 적용 대상 |
|------|------|-----------|
| `correctness` | 결과의 정확성. 모범 답안의 핵심 내용과 일치하는지 | 모든 에이전트 |
| `step_reasoning` | 풀이 과정의 논리성. 중간 단계가 명확한지 | math |
| `fluency` | 문장의 유창성. 문법적으로 자연스러운지 | translate |
| `naturalness` | 번역의 자연스러움. 원어민이 쓴 것처럼 느껴지는지 | translate |
| `formality` | 격식체 적절성. 비즈니스 상황에 맞는 어조인지 | translate (선택) |

### 기준 결정 우선순위

1. 테스트 케이스의 `eval_criteria` (케이스 레벨 override)
2. `eval_config.agent_criteria[target_agent]` (에이전트 유형별 기본값)
3. `["correctness"]` (fallback)

이 계층 구조의 이점: 대부분의 케이스는 에이전트 유형별 기본 기준을 사용하되, 특수한 케이스(예: 격식체 번역)에서만 추가 기준을 override할 수 있다.

## Judge LLM

### 프롬프트 구조 (`prompts.py`)

**시스템 프롬프트**: Judge의 역할 정의, 채점 기준 설명(1~10점 루브릭), JSON 응답 형식 지정

**유저 프롬프트**: 3가지 입력(input, reference_answer, actual_output)과 평가할 기준 목록을 구조화하여 전달

### Judge 응답 형식

```json
{
  "scores": {
    "correctness": {"score": 9, "reason": "정확한 계산 결과 제시"},
    "step_reasoning": {"score": 8, "reason": "중간 과정 설명 포함"}
  },
  "overall_score": 8.5,
  "summary": "정확한 결과를 제시하였으나 풀이 과정이 더 상세하면 좋겠음"
}
```

### 실패 처리 (`judge.py`)

Judge LLM 응답의 JSON 파싱이 실패하면 모든 기준에 0점을 부여하고 에러 메시지를 summary에 기록한다. 이는 평가 결과를 누락시키지 않으면서 파싱 실패를 명확히 표시하기 위함이다.

## CLI 사용법

```bash
# 전체 실행
uv run python -m evals.run

# ID로 필터링 (substring match)
uv run python -m evals.run --filter math

# 에이전트 유형으로 필터링
uv run python -m evals.run --agent translate

# 조합 가능
uv run python -m evals.run --agent math --filter chained
```

### Exit Code

- `0`: 모든 테스트 PASS
- `1`: 하나 이상 FAIL 또는 필터 결과 없음

CI 파이프라인에서 exit code로 품질 게이트를 구현할 수 있다.

## 콘솔 출력 형식

```
============================================================
  EVALUATION RESULTS (judge: gpt-4o)
============================================================

[1/4] math_simple_add - 단순 덧셈 .................. PASS (8.5, 2.1s)
  ✓ correctness     : 9/10 - 정확한 계산 결과
  ✓ step_reasoning  : 8/10 - 풀이 과정 포함

[2/4] translate_en_kr - 영한 번역 .................. FAIL (5.7, 1.8s)
  ✓ correctness     : 7/10 - 의미 전달 정확
  ✗ fluency         : 5/10 - 어색한 표현 존재
  ✗ naturalness     : 5/10 - 직역 느낌

------------------------------------------------------------
  SUMMARY: 3/4 passed (threshold: 7.0)
  Failed: translate_en_kr
  Total time: 8.2s
------------------------------------------------------------
```

개별 기준의 pass/fail은 `pass_threshold`와 비교하여 ✓/✗로 표시한다. 테스트 케이스 전체의 pass/fail은 `overall_score`(기준별 평균)로 판정한다.
