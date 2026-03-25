# Agents

## Overview

이 프로젝트의 에이전트 시스템은 두 가지 역할로 구성된다.

1. **Supervisor** — 사용자 요청을 분석하고 적절한 에이전트에게 라우팅하는 조율자
2. **Subagents** — 특정 도메인 작업을 수행하는 전문 에이전트

레지스트리를 통한 에이전트 등록·관리에 대해서는 [AgentRegistry.md](./AgentRegistry.md)를 참고한다.

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
{"next": "<agent_name>", "reason": "결정 근거", "plan": "실행 계획"}
```

- `next`: 다음 에이전트의 라우팅 키 또는 `"FINISH"`
- `reason`: 결정 근거
- `plan`: 전체 실행 계획 (State에 저장되어 다음 호출 시 참조)

### 안전 장치

- **JSON 파싱 실패 시 FINISH**: 파싱 실패 시 `next_agent: "FINISH"`로 안전 종료
- **MAX_ITERATIONS = 5**: `completed_agents` 수가 5 이상이면 강제 종료하여 무한 루프 방지

## Subagents

### 공통 구조

모든 subagent는 동일한 패턴을 따른다:

1. **wrapper 함수** — `State`를 받아 서브그래프/LLM을 실행하고 결과를 `State` 형태로 반환
2. **`completed_agents` 업데이트** — 자신의 이름을 추가하여 Supervisor가 진행 상황을 추적할 수 있게 함
3. **결과 태깅** — 접두어를 붙여 메시지 출처를 명확히 함

### 에이전트 구현 패턴

Subagent는 복잡도에 따라 두 가지 패턴으로 구현할 수 있다:

**ReAct 패턴 (도구 사용 에이전트)**:
```
[agent_node] → (tool_calls?) → [tool_executor_node] → [agent_node] → ... → [END]
```
LLM이 도구 호출을 결정하고, 커스텀 `tool_executor_node`가 실행한다. `ToolNode` 대신 커스텀 노드를 사용하는 이유는 `@log_node` 데코레이터를 적용하여 도구 호출을 로깅하기 위함이다.

**단순 LLM 호출 패턴 (도구 없는 에이전트)**:
```
[agent_node] → (결과 반환)
```
서브그래프 없이 LLM을 직접 호출한다. 도구가 필요 없는 작업에 적합하다.

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
