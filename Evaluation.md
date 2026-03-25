# Evaluation

## Overview

**LLM-as-Judge** 방식으로 각 에이전트의 출력 품질을 자동 평가한다. Judge LLM이 에이전트의 실제 출력을 모범 답안과 비교하여 여러 기준에 대해 1~10점으로 채점한다.

### LLM-as-Judge를 선택한 이유

- 숫자 정확도 같은 단순 검증은 rule-based로 가능하지만, 논리적 풀이 과정이나 번역 자연스러움은 LLM 판단이 필요
- 에이전트 유형에 관계없이 동일한 파이프라인에서 기준만 교체하면 됨

## 구조

```
evals/
├── run.py              # CLI 엔트리포인트
├── runner.py           # 테스트 실행 오케스트레이션
├── judge.py            # Judge LLM 호출 + 응답 파싱
├── prompts.py          # Judge 프롬프트 템플릿
└── types.py            # TypedDict 정의

res/                    # 테스트 케이스 YAML (재귀 수집)
```

## 실행 흐름

1. `res/` 하위 모든 YAML 수집 → `eval_config` + `test_cases` 파싱
2. 각 test_case: registry에서 wrapper 조회 → 직접 호출 → Judge LLM 평가
3. `pass_threshold` 기준 PASS/FAIL 판정 → 콘솔 리포트

### wrapper 직접 호출 방식

전체 그래프(Supervisor → Agent)를 실행하지 않고 wrapper를 직접 호출한다.

- **격리된 평가**: Supervisor 라우팅 오류가 subagent 평가에 영향 없음
- **빠른 피드백**: 전체 파이프라인 대비 실행 시간 단축

## 테스트 케이스 작성

### YAML 스키마

```yaml
eval_config:
  judge_model: "gpt-4o"
  judge_temperature: 0.0
  pass_threshold: 7.0
  agent_criteria:
    <agent_name>:
      - correctness
      - <domain_specific_criteria>

test_cases:
  - id: "unique_id"
    description: "설명"
    target_agent: "<agent_name>"
    input: "에이전트에 전달할 입력"
    reference_answer: "모범 답안"
    state_overrides:       # (선택) State 필드 override
      completed_agents: []
    eval_criteria:         # (선택) 케이스 레벨 기준 override
      - correctness
      - formality
```

### 다중 파일 지원

`res/` 하위의 `*.yaml`/`*.yml`을 재귀 수집한다. `eval_config`는 첫 번째 파일에서, `test_cases`는 전체에서 병합한다.

## 평가 기준

### 기준 결정 우선순위

1. 테스트 케이스의 `eval_criteria` (케이스 레벨 override)
2. `eval_config.agent_criteria[target_agent]` (에이전트 유형별 기본값)
3. `["correctness"]` (fallback)

### 기본 제공 기준

| 기준 | 설명 |
|------|------|
| `correctness` | 결과의 정확성. 모범 답안의 핵심 내용과 일치하는지 |
| `step_reasoning` | 풀이 과정의 논리성. 중간 단계가 명확한지 |
| `fluency` | 문장의 유창성. 문법적으로 자연스러운지 |
| `naturalness` | 번역의 자연스러움. 원어민 수준인지 |
| `formality` | 격식체 적절성. 비즈니스 상황에 맞는 어조인지 |

## Judge 응답

```json
{
  "scores": {
    "<criterion>": {"score": 9, "reason": "근거"}
  },
  "overall_score": 8.5,
  "summary": "전체 평가 요약"
}
```

파싱 실패 시 모든 기준 0점 + 에러 메시지를 기록하여 평가 결과 누락 없이 실패를 표시한다.

## CLI

```bash
uv run python -m evals.run                          # 전체
uv run python -m evals.run --filter <id_substring>  # ID 필터
uv run python -m evals.run --agent <agent_name>     # 에이전트 필터
```

Exit code: `0` (all pass) / `1` (any fail). CI 품질 게이트에 활용 가능.
