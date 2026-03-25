# Logging

## Overview

이 프로젝트의 로깅 시스템은 멀티 에이전트 실행 흐름을 추적하고 디버깅하기 위해 설계되었다. 핵심 설계 원칙은 세 가지이다:

1. **어떤 노드가 실행 중인지 명확히 표시** — 복잡한 그래프 순환에서 현재 위치를 즉시 파악
2. **상태 변화를 git diff 스타일로 시각화** — 노드 실행 전후의 State 변경을 한눈에 파악
3. **LLM 응답을 원문 그대로 기록** — 요약이나 truncation 없이 디버깅에 필요한 모든 정보 보존

## 구조

```
src/logging/
├── __init__.py       # setup_logging, get_logger, log_node export
├── config.py         # 로거 설정 (포맷, 핸들러)
├── decorator.py      # @log_node 데코레이터
└── diff.py           # 상태 포맷팅 + diff 계산
```

## 로거 설정 (`config.py`)

### 네이밍 체계

모든 로거는 `supervisor_subagent` 루트 아래에 계층적으로 구성된다.

```
supervisor_subagent
├── main                         # 메인 엔트리포인트
├── supervisor                   # Supervisor LLM 호출
├── router.supervisor            # Supervisor 라우팅 결정
├── agent.math                   # Math Agent 내부 동작
├── router.math                  # Math Agent ReAct 루프 분기
├── agent.translate              # Translate Agent 내부 동작
├── node.supervisor              # @log_node 데코레이터 출력
├── node.math_agent_internal     # Math 서브그래프 내부 노드
├── node.math_tool_executor      # Math 도구 실행 노드
└── node.translate_agent_internal
```

이 계층 구조의 이점:
- `supervisor_subagent.node` 레벨을 필터링하면 데코레이터 로그만 확인 가능
- `supervisor_subagent.router` 레벨로 라우팅 결정만 추적 가능
- 특정 에이전트의 로그만 선택적으로 확인 가능

### 포맷

```
2026-03-25 14:30:15 [INFO] supervisor_subagent.node.supervisor - [SUPERVISOR] Processing started
```

`%(asctime)s [%(levelname)s] %(name)s - %(message)s` 포맷으로, 시간·레벨·컴포넌트·메시지가 한 줄에 표시된다.

## @log_node 데코레이터 (`decorator.py`)

### 설계 의도

모든 노드 함수에 동일한 로깅 패턴(진입 → 실행 → 완료/실패)을 적용하되, 노드 로직을 수정하지 않고 데코레이터로 일관된 포맷을 보장한다.

### 동작 방식

```python
@log_node("supervisor")
def supervisor_node(state: State) -> dict:
    ...
```

데코레이터가 자동으로 수행하는 것:

1. **진입 로그**: 현재 처리 중인 노드를 `========` 구분선으로 강조

```
============================================================
  [SUPERVISOR] Processing started
============================================================
```

2. **완료 로그**: 실행 시간 + State 변화를 git diff 스타일로 출력

```
------------------------------------------------------------
  [SUPERVISOR] Completed (1.234s)
------------------------------------------------------------
  State:
  messages: (list[BaseMessage]) 2 messages
    [0] type: HumanMessage, content: 3과 7을 더해주세요
+   [1] type: AIMessage, content:
+       {
+         "next": "math",
+         "reason": "계산 필요"
+       }
-   next_agent: (str) ''
+   next_agent: (str) 'math'
-   plan: (str) ''
+   plan: (str) '1. 덧셈 수행'
  completed_agents: (list) []
------------------------------------------------------------
```

3. **실패 로그**: 예외 발생 시 `!!!` 구분선 + traceback

```
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  [SUPERVISOR] Failed (0.512s)
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
```

### 적용 대상

| 노드 | 파일 | 역할 |
|------|------|------|
| `supervisor` | `supervisor/supervisor.py` | Supervisor 결정 |
| `math_agent_internal` | `math_agent/agent.py` | Math LLM 호출 |
| `math_tool_executor` | `math_agent/agent.py` | 도구 실행 |
| `translate_agent_internal` | `translate_agent/agent.py` | Translate LLM 호출 |

## 상태 diff 포매터 (`diff.py`)

### git diff 스타일 출력

`format_state_diff(before, after)` 함수는 노드 실행 전 상태와 반환된 업데이트를 비교하여 다음 규칙으로 출력한다:

| Prefix | 의미 |
|--------|------|
| (공백) | 변경 없음 |
| `+` | 추가된 값 |
| `-` | 제거된 값 |
| `-` / `+` 쌍 | 값이 변경됨 (이전 → 이후) |

이 방식을 선택한 이유: 개발자가 이미 익숙한 `git diff` 시각 언어를 사용하여 학습 비용 없이 상태 변화를 즉시 파악할 수 있다.

### 타입 정보 표시

모든 필드에 타입이 표시된다:

```
  next_agent: (str) 'math'
  completed_agents: (list[str]) ['math', 'translate']
  messages: (list[BaseMessage]) 3 messages
```

TypedDict 기반의 State에서 런타임 타입을 확인할 수 있어 디버깅 시 타입 관련 문제를 빠르게 발견한다.

### 메시지 콘텐츠 처리

메시지 내용은 **원문 그대로** 출력된다. truncation이 없다.

- **JSON 콘텐츠**: 파싱 후 pretty-print (들여쓰기 적용)
- **일반 텍스트**: 그대로 출력
- **tool_calls**: raw JSON으로 전체 내용 출력 (name, args, id, type)
- **빈 콘텐츠**: 생략 (tool_calls만 있는 AIMessage의 경우)

```
[2] type: AIMessage, tool_calls:
        [
          {
            "name": "add",
            "args": { "a": 3, "b": 7 },
            "id": "call_abc123",
            "type": "tool_call"
          }
        ]
[3] type: ToolMessage, content: 10.0
```

이 설계의 이점: LLM이 반환한 원본 데이터를 그대로 볼 수 있어, JSON 파싱 실패나 예상치 못한 응답 형식을 디버깅할 때 원인을 즉시 파악할 수 있다.

### `_prefix_lines` 정렬 알고리즘

`+` marker를 추가할 때 기존 들여쓰기를 유지하는 것이 중요하다. 단순히 prefix를 prepend하면 들여쓰기가 밀린다.

```
# 잘못된 방식 (들여쓰기 밀림)
+       [1] type: AIMessage, content: ...

# 올바른 방식 (정렬 유지)
+   [1] type: AIMessage, content: ...
```

`_prefix_lines()`는 각 줄의 선두 공백을 marker로 대체하여 기존 들여쓰기 수준을 유지한다.

## 로깅 레벨 활용

| 레벨 | 용도 | 예시 |
|------|------|------|
| `INFO` | 정상 실행 흐름 | LLM 호출, 노드 진입/완료, 라우팅 결정 |
| `WARNING` | 복구 가능한 문제 | JSON 파싱 실패 → FINISH 폴백, 0 나누기 시도 |
| `ERROR` | 실패 | LLM API 오류, 서브그래프 실행 실패, 알 수 없는 도구 |

모든 `ERROR` 로그에는 `exc_info=True`가 포함되어 traceback이 함께 기록된다.

## 로깅이 커버하는 실패 지점

| 위치 | 실패 유형 | 로그 레벨 |
|------|-----------|-----------|
| Supervisor LLM 호출 | API 오류, 네트워크 실패 | ERROR |
| JSON 파싱 (`extract_json_from_text`) | 잘못된 JSON, 누락된 코드 블록 | WARNING |
| Math Agent LLM 호출 | API 오류 | ERROR |
| 도구 실행 (`tool_executor_node`) | 도구 함수 예외, 알 수 없는 도구 | ERROR |
| `divide` 도구 | 0 나누기 시도 | WARNING |
| Translate Agent LLM 호출 | API 오류 | ERROR |
| 서브그래프 invoke | 서브그래프 내부 예외 | ERROR |
| MAX_ITERATIONS 도달 | 무한 루프 방지 | WARNING |
