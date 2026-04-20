# 쿼리 전처리 및 최종 답변 생성 파이프라인 설계

## 개요

supervisor-subagent 시스템에 두 가지 노드를 추가하여 파이프라인을 확장한다:

1. **query_rewriter** — 사용자 쿼리 전처리 (구현 완료)
2. **response_generator** — 페르소나 주입 및 톤앤매너 통일을 위한 최종 답변 생성 (신규)

## 전체 흐름

```
START → query_rewriter → supervisor → router → [subagent] → supervisor → ...
                                             → response_generator → END
```

- `query_rewriter`: 고정 전처리, 최초 1회만 실행
- `supervisor ↔ subagent`: 기존 루프 유지 (MAX_ITERATIONS = 5)
- `response_generator`: supervisor가 FINISH 결정 시 END 대신 이 노드로 라우팅

## query_rewriter 노드

### 배치 전략: 고정 전처리

3가지 접근법을 비교 검토한 결과, 고정 전처리를 선택했다.

| 접근법 | 설명 | 누락 위험 | 복잡도 |
|--------|------|-----------|--------|
| **고정 전처리 (채택)** | 항상 실행 | 없음 | 낮음 |
| supervisor 선택적 호출 | supervisor가 필요 시만 호출 | 있음 | 중간 |
| 조건부 전처리 | 경량 분류기로 판단 후 호출 | 있음 | 높음 |

**선택 근거:**

- 쿼리의 약 50%가 리라이팅 필요
- 리라이팅 누락 시 서브에이전트가 잘못된 결과를 반환하거나 실패 (치명적)
- 속도보다 정확도 우선
- 속도가 중요해지는 시점에 접근법 3(조건부 전처리)으로 전환 가능

### 기능

단일 LLM 호출로 3가지 리라이팅을 수행한다:

1. **상대적 시간 표현 해석** — "지난주", "이번 달" 등을 현재 시각 기준 구체적 날짜로 변환
2. **대화 맥락 보충** — "이거", "더 해줘" 등 모호한 지시어를 이전 대화에서 대상을 찾아 명시
3. **용어 사전 치환** — 사전에 정의된 도메인 용어를 구체적 정의로 치환

### 동작

- 전체 대화 히스토리를 LLM에 전달하여 맥락 보충 품질 확보
- 리라이팅 결과가 원본과 동일하면 빈 메시지 반환 (원본 유지)
- 리라이팅 결과가 다르면 새 HumanMessage로 추가

### 위치

- 그래프: `START → query_rewriter → supervisor`
- 코드: `src/agents/query_rewriter/`

## response_generator 노드

### 목적

- 페르소나 주입: 시스템 전체에서 일관된 캐릭터/톤 유지
- 톤앤매너 통일: 서브에이전트별로 다른 응답 스타일을 최종 단계에서 통일
- 서브에이전트 결과 종합: 멀티 에이전트 체이닝 시 결과를 자연스럽게 합성

### 컨텍스트 구성

최종 답변 노드에 전달하는 정보:

| 포함 | 제외 |
|------|------|
| 페르소나 시스템 프롬프트 | supervisor 내부 JSON 판단 (next, reason, plan) |
| 사용자 원본 쿼리 | |
| 서브에이전트 결과(들) | |

- `state["messages"]`에는 supervisor의 JSON 응답도 포함되어 있다. 메시지 필터링(JSON 형태의 AIMessage 제거) 대신, 페르소나 프롬프트에서 "JSON 형식의 내부 판단 메시지는 무시하고 사용자 질문과 워커 결과만 참고하라"고 지시하는 방식을 사용한다. 이유: 필터링 로직은 메시지 포맷 변경 시 깨지기 쉽고, LLM이 무관한 메시지를 무시하는 것은 신뢰할 수 있는 동작이다
- 사용자 원본 쿼리를 포함하는 이유: 질문 톤에 맞춘 답변 생성 ("알려줘" → 친근, "보고해주세요" → 격식)

### 페르소나 프롬프트 설계

- `prompt.py`에 상수로 분리하여 교체 가능한 구조
- 구체적인 페르소나 내용은 설계 범위 밖 (운영 시 결정)

### 그래프 연결

- `supervisor_router`에서 FINISH 판단 시 `END` 대신 `"response_generator"` 반환
- `response_generator → END` 엣지 추가

### 위치

- 그래프: `supervisor_router` → `response_generator` → `END`
- 코드: `src/agents/response_generator/`
- 레지스트리에 등록하지 않음 (에이전트가 아닌 파이프라인 노드)

## 변경 범위

### 신규 파일

| 파일 | 설명 |
|------|------|
| `src/agents/response_generator/__init__.py` | 모듈 export |
| `src/agents/response_generator/prompt.py` | 페르소나 프롬프트 정의 |
| `src/agents/response_generator/generator.py` | response_generator_node 구현 |
| `tests/test_response_generator.py` | 단위 테스트 |

### 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/agents/supervisor/supervisor.py` | `supervisor_router`에서 END 대신 `"response_generator"` 반환 |
| `src/main.py` | response_generator 노드 추가, response_generator → END 엣지 추가, 실행 흐름 docstring 업데이트 |

### 변경하지 않는 것

- 서브에이전트 구조 (math, translate, sql)
- State 정의
- 레지스트리 패턴
- query_rewriter (이미 구현 완료)
