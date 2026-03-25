# Agents

## Overview

이 프로젝트의 에이전트 시스템은 세 가지 핵심 컴포넌트로 구성된다.

1. **Agent Registry** — 에이전트 등록·조회·프롬프트 생성을 담당하는 중앙 레지스트리
2. **Supervisor** — 사용자 요청을 분석하고 적절한 에이전트에게 라우팅하는 조율자
3. **Subagents** — 특정 도메인 작업을 수행하는 전문 에이전트 (Math, Translate)

## Agent Registry

### 설계 의도

에이전트를 추가할 때 그래프 빌드 코드, Supervisor 프롬프트, 라우터 분기 로직을 모두 수정해야 하는 문제를 해결하기 위해 레지스트리 패턴을 도입했다. 에이전트가 자신을 레지스트리에 등록하면 나머지는 자동으로 처리된다.

### 구조

```
src/agents/
├── registry.py           # AgentRegistry + AgentEntry + @registry.agent 데코레이터
├── __init__.py            # 에이전트 모듈 import → 자동 등록 트리거
├── supervisor/
├── math_agent/
└── translate_agent/
```

### AgentEntry

레지스트리에 등록된 각 에이전트는 `AgentEntry` 데이터클래스로 관리된다.

| 필드 | 설명 | 예시 |
|------|------|------|
| `name` | 라우팅 키. Supervisor가 JSON으로 선택하는 이름 | `"math"` |
| `node_name` | LangGraph 그래프 노드 이름 | `"math_agent"` |
| `wrapper` | 실제 실행할 wrapper 함수 | `math_wrapper` |
| `description` | Supervisor 프롬프트에 삽입되는 설명 | wrapper의 docstring |

### @registry.agent 데코레이터

에이전트 등록은 wrapper 함수 정의 시점에 데코레이터로 수행된다.

```python
@registry.agent("math")
def math_wrapper(state: State) -> dict:
    """수학 계산을 수행합니다. 덧셈, 곱셈, 나눗셈 등의 계산이 필요할 때 사용합니다."""
    ...
```

데코레이터가 하는 일:
1. `name`으로 라우팅 키 설정
2. `node_name`을 `"{name}_agent"` 형태로 자동 생성 (override 가능)
3. wrapper 함수의 **docstring**을 `description`으로 추출
4. `AgentEntry`를 생성하여 레지스트리에 등록

docstring이 없으면 `ValueError`가 발생한다. 이는 Supervisor 프롬프트에 에이전트 설명이 반드시 필요하기 때문이다.

### 레지스트리가 프로젝트에 기여하는 방식

**그래프 빌드** (`src/main.py`):
```python
for entry in registry.entries:
    graph.add_node(entry.node_name, entry.wrapper)
    graph.add_edge(entry.node_name, "supervisor")
```

레지스트리에 등록된 에이전트를 순회하며 자동으로 노드와 엣지를 추가한다. 새 에이전트를 등록하면 `main.py` 수정 없이 그래프에 포함된다.

**Supervisor 프롬프트 생성** (`registry.build_workers_prompt()`):

등록된 에이전트의 이름과 description을 조합하여 Supervisor 시스템 프롬프트의 "사용 가능한 워커" 섹션을 동적으로 생성한다.

**라우터 분기** (`supervisor_router()`):

`registry.get(next_agent)`로 에이전트를 조회하여 해당 노드로 라우팅한다. 하드코딩된 if-elif 분기가 없다.

## Supervisor

### 역할

Supervisor는 에이전트이면서 동시에 오케스트레이터이다. LLM을 호출하여 다음에 실행할 에이전트를 결정한다.

### 실행 흐름

1. `_build_system_prompt()`: 레지스트리에서 워커 목록, 현재 계획, 완료된 에이전트를 조합하여 시스템 프롬프트 생성
2. `supervisor_node()`: LLM 호출 → JSON 응답 파싱 → `next_agent`, `plan` 반환
3. `supervisor_router()`: `next_agent` 값에 따라 해당 에이전트 노드 또는 END로 라우팅

### JSON 라우팅 프로토콜

Supervisor LLM은 다음 형태의 JSON을 반환한다:

```json
{"next": "math", "reason": "계산이 필요합니다", "plan": "1. 계산 2. 번역"}
```

- `next`: 다음 에이전트의 라우팅 키 또는 `"FINISH"`
- `reason`: 결정 근거
- `plan`: 전체 실행 계획 (State에 저장되어 다음 호출 시 참조)

### 안전 장치

- **JSON 파싱 실패 시 FINISH**: `extract_json_from_text()`가 실패하면 `next_agent: "FINISH"`로 안전 종료
- **MAX_ITERATIONS = 5**: `completed_agents` 수가 5 이상이면 강제 종료하여 무한 루프 방지

## Subagents

### 공통 구조

모든 subagent는 동일한 패턴을 따른다:

1. **wrapper 함수** — `State`를 받아 서브그래프/LLM을 실행하고 결과를 `State` 형태로 반환
2. **`completed_agents` 업데이트** — 자신의 이름을 추가하여 Supervisor가 진행 상황을 추적할 수 있게 함
3. **결과 태깅** — `[수학 계산 결과]`, `[번역 결과]` 등의 접두어를 붙여 메시지 출처를 명확히 함

### Math Agent

**아키텍처**: ReAct(Reasoning + Acting) 패턴의 서브그래프

```
[agent_node] → (tool_calls?) → [tool_executor_node] → [agent_node] → ... → [END]
```

**도구**: `add(a, b)`, `multiply(a, b)`, `divide(a, b)`

도구 실행은 LangGraph의 `ToolNode`가 아닌 커스텀 `tool_executor_node`를 사용한다. 이는 `@log_node` 데코레이터를 적용하여 각 도구 호출과 결과를 로깅하기 위함이다.

**서브그래프 ↔ 메인 그래프 상태 변환**:
- 메인 그래프 `State`의 `messages`를 서브그래프 `WorkerState`의 `messages`로 전달
- 서브그래프 결과의 마지막 메시지를 `[수학 계산 결과]` 태그와 함께 메인 그래프로 반환

### Translate Agent

**아키텍처**: 단일 LLM 호출 (도구 없음)

```
translate_agent_node → (결과 반환)
```

서브그래프 없이 `translate_agent_node()`가 직접 LLM을 호출한다. 번역은 도구가 필요 없는 LLM 고유 능력이므로 가장 단순한 에이전트 구현이다.

시스템 프롬프트로 번역 방향(한↔영)과 톤 유지를 지시한다.

## 새 에이전트 추가 방법

1. `src/agents/` 하위에 에이전트 디렉토리 생성:

```
src/agents/new_agent/
├── __init__.py
└── agent.py
```

2. wrapper 함수에 `@registry.agent` 데코레이터 적용:

```python
from src.agents.registry import registry
from src.state import State

@registry.agent("new_agent_name")
def new_wrapper(state: State) -> dict:
    """에이전트 설명. Supervisor 프롬프트에 표시됩니다."""
    # 에이전트 로직 구현
    completed = list(state.get("completed_agents", []))
    completed.append("new_agent_name")
    return {
        "messages": [...],
        "completed_agents": completed,
    }
```

3. `src/agents/__init__.py`에 import 추가:

```python
from src.agents.new_agent import new_wrapper  # noqa: F401
```

이것으로 완료된다. `main.py`, Supervisor 프롬프트, 라우터 로직은 수정할 필요가 없다.

## State 설계

### State (메인 그래프)

| 필드 | 타입 | 리듀서 | 역할 |
|------|------|--------|------|
| `messages` | `list[BaseMessage]` | `add_messages` | 전체 대화 이력. 리듀서가 중복 없이 자동 병합 |
| `next_agent` | `str` | 없음 | Supervisor가 결정한 다음 에이전트 |
| `plan` | `str` | 없음 | Supervisor의 실행 계획 |
| `completed_agents` | `list[str]` | 없음 | 완료된 에이전트 이력 |

### WorkerState (서브그래프)

| 필드 | 타입 | 리듀서 | 역할 |
|------|------|--------|------|
| `messages` | `list[BaseMessage]` | `add_messages` | 서브그래프 내부 대화 |

메인 그래프의 `messages`를 서브그래프에 전달하고, 서브그래프의 최종 결과만 메인 그래프로 반환한다. 이 분리로 서브그래프 내부의 중간 메시지(tool_calls, ToolMessage 등)가 메인 그래프를 오염시키지 않는다.
