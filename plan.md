# Logging Plan

## 목표

모든 노드의 상태 변화, LLM 결정, 실패 가능 지점을 구조화된 로그로 남긴다.

## 핵심 컴포넌트

### 1. Node Decorator (`src/logging/decorator.py`)

모든 노드 함수에 적용하는 데코레이터. 일관된 포맷으로 before/after 상태와 diff를 로깅한다.

```
[NODE:supervisor] === BEFORE ===
  state.messages: 2 messages
  state.next_agent: ""
  state.plan: ""
  state.completed_agents: []

[NODE:supervisor] === AFTER ===
  state.messages: 3 messages (+1)
  state.next_agent: "math"
  state.plan: "1. 계산 2. 번역"
  state.completed_agents: []

[NODE:supervisor] === DIFF ===
  next_agent: "" → "math"
  plan: "" → "1. 계산 2. 번역"
  messages: +1 (AIMessage: '{"next": "math"...}')
```

- `@log_node("supervisor")` 형태로 사용
- State와 WorkerState 모두 지원
- 노드 실행 시간 측정
- 예외 발생 시 에러 로그 + re-raise

### 2. Logger 설정 (`src/logging/config.py`)

- Python `logging` 모듈 기반
- 포맷: `%(asctime)s [%(levelname)s] %(name)s - %(message)s`
- 로거 이름 체계: `supervisor_subagent.{component}`
  - `supervisor_subagent.node.supervisor`
  - `supervisor_subagent.node.math_agent`
  - `supervisor_subagent.node.translate_agent`
  - `supervisor_subagent.llm`
  - `supervisor_subagent.router`
- 레벨: INFO (기본), DEBUG (상태 diff 상세)

### 3. State Diff 유틸 (`src/logging/diff.py`)

- 두 state dict를 비교하여 변경된 필드만 추출
- messages는 개수 변화 + 추가된 메시지 요약 (content 앞 100자)
- list 필드는 추가/제거된 항목 표시

## 로깅 대상

### 노드 (decorator 적용)

| 노드 | 파일 | 적용 대상 |
|------|------|-----------|
| supervisor | supervisor/supervisor.py | `supervisor_node` |
| math_wrapper | agents/math_agent/agent.py | `math_wrapper` |
| math_agent_node | agents/math_agent/agent.py | `math_agent_node` (서브그래프 내부) |
| translate_wrapper | agents/translate_agent/agent.py | `translate_wrapper` |
| translate_agent_node | agents/translate_agent/agent.py | `translate_agent_node` |

### LLM 호출 (각 노드 내부에서 직접 로깅)

| 위치 | 로깅 내용 |
|------|-----------|
| supervisor_node | LLM 응답 원문, 파싱된 JSON (next, reason, plan) |
| math_agent_node | LLM 응답, tool_calls 유무 및 호출 내용 |
| translate_agent_node | LLM 응답 원문 |

### 라우터 결정

| 라우터 | 로깅 내용 |
|--------|-----------|
| supervisor_router | next_agent 값, 라우팅 결과, MAX_ITERATIONS 체크 |
| should_continue | tool_calls 유무, 계속/종료 결정 |

### 실패 가능 지점

| 위치 | 실패 유형 | 로깅 |
|------|-----------|------|
| extract_json_from_text | JSON 파싱 실패 | WARNING + 원본 텍스트 |
| supervisor_node | JSONDecodeError, ValueError | ERROR + fallback 동작 |
| LLM invoke (3곳) | API 에러, 네트워크 에러 | ERROR + 예외 정보 |
| math_subgraph.invoke | 서브그래프 실행 에러 | ERROR + 예외 정보 |
| divide tool | 0으로 나누기 시도 | WARNING |

## 파일 구조

```
src/
├── logging/
│   ├── __init__.py        # setup_logging() 및 log_node export
│   ├── config.py          # 로거 설정
│   ├── decorator.py       # @log_node 데코레이터
│   └── diff.py            # state diff 유틸
```

## 구현 단계

### Step 1: logging 모듈 생성
- `config.py`: 로거 설정 함수
- `diff.py`: state diff 계산 함수
- `decorator.py`: `@log_node` 데코레이터
- `__init__.py`: public API export

### Step 2: 각 노드에 decorator 적용
- `supervisor_node`, `supervisor_router`에 적용
- `math_wrapper`, `math_agent_node`, `should_continue`에 적용
- `translate_wrapper`, `translate_agent_node`에 적용

### Step 3: LLM 호출 및 실패 지점에 로깅 추가
- 기존 print문을 logger 호출로 교체
- LLM invoke에 try-except + 로깅 추가
- JSON 파싱 실패에 WARNING 로그 추가

### Step 4: main.py에서 로깅 초기화
- `setup_logging()` 호출 추가
- 기존 print문을 logger로 교체
