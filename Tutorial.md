# Supervisor-Subagent 멀티 에이전트 시스템: 종합 자습서

> LangGraph 기반의 Supervisor-Subagent 패턴 구현에 대한 기술 보고서.
> 아키텍처 설계, 구현 디테일, 기술적 선택의 근거, 그리고 대안 기술과의 비교를 다룬다.

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [아키텍처](#2-아키텍처)
3. [State 설계](#3-state-설계)
4. [Supervisor 구현](#4-supervisor-구현)
5. [Subagent 구현 패턴](#5-subagent-구현-패턴)
6. [Agent Registry](#6-agent-registry)
7. [로깅 시스템](#7-로깅-시스템)
8. [평가 시스템 (LLM-as-Judge)](#8-평가-시스템-llm-as-judge)
9. [기술적 선택과 대안 분석](#9-기술적-선택과-대안-분석)
10. [프로젝트 구조 및 실행 방법](#10-프로젝트-구조-및-실행-방법)
11. [참고 자료](#11-참고-자료)

---

## 1. 프로젝트 개요

이 프로젝트는 [LangGraph](https://www.langchain.com/langgraph) 기반의 멀티 에이전트 시스템으로, **Supervisor가 사용자 요청을 분석하고 전문 Subagent에게 작업을 위임하는 패턴**을 구현한다. 핵심 의존성은 다음과 같다.

| 라이브러리 | 역할 |
|-----------|------|
| [`langgraph`](https://docs.langchain.com/oss/python/langgraph/graph-api) (>=0.2.0) | 그래프 기반 에이전트 오케스트레이션 |
| [`langchain-openai`](https://docs.langchain.com/oss/python/integrations/chat/openai) (>=0.1.0) | OpenAI LLM 통합 |
| [`langchain-core`](https://reference.langchain.com/python/langchain-core/tools) (>=0.2.0) | 메시지, 도구 등 핵심 추상화 |
| `python-dotenv` (>=1.0.0) | 환경 변수 관리 |
| `pyyaml` (>=6.0) | 테스트 케이스 YAML 파싱 |

Python 3.11 이상을 요구하며, `uv`를 패키지 매니저로 사용한다.

---

## 2. 아키텍처

### 2.1 전체 실행 흐름

```
[START] --> [Supervisor] --> (Router) --+--> [Agent A] --> [Supervisor] (cycle)
                                       +--> [Agent B] --> [Supervisor] (cycle)
                                       +--> [END] (FINISH)
```

Supervisor는 사용자 요청을 JSON 형태로 분석하여 적절한 에이전트를 선택하고, 에이전트 실행 결과를 받아 다음 단계를 결정한다. 모든 작업이 완료되면 최종 응답을 반환한다.

이 패턴은 LangGraph 공식 문서에서 권장하는 [**Supervisor Pattern**](https://docs.langchain.com/oss/python/langgraph/workflows-agents)에 해당한다. LangGraph의 [`StateGraph`](https://docs.langchain.com/oss/python/langgraph/graph-api)는 노드(node)와 엣지(edge)로 구성된 그래프를 정의하고, [조건부 엣지(conditional edges)](https://docs.langchain.com/oss/python/langgraph/graph-api)를 통해 동적 분기를 지원한다. 순환(cycle)을 허용하므로 Supervisor → Agent → Supervisor 루프를 자연스럽게 표현할 수 있다.

### 2.2 그래프 빌드 (`src/main.py`)

```python
def build_graph():
    graph = StateGraph(State)
    graph.add_node("supervisor", supervisor_node)

    node_names: list[str] = []
    for entry in registry.entries:
        graph.add_node(entry.node_name, entry.wrapper)
        graph.add_edge(entry.node_name, "supervisor")
        node_names.append(entry.node_name)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        supervisor_router,
        [*node_names, END],
    )
    return graph.compile()
```

레지스트리를 순회하며 노드 등록, 엣지 연결, conditional edges 구성을 자동으로 수행한다. 새 에이전트가 등록되면 이 코드 수정 없이 그래프에 포함된다.

[`add_conditional_edges()`](https://docs.langchain.com/oss/python/langgraph/graph-api)는 라우팅 함수(`supervisor_router`)가 반환하는 문자열에 따라 다음 노드를 결정한다. 가능한 목적지 목록(`[*node_names, END]`)을 미리 제공하여 그래프 컴파일 시 유효성 검증이 가능하다.

### 2.3 데모 시나리오

`main.py`는 세 가지 데모 시나리오를 제공한다.

- **시나리오 A** — 수학 계산만: `"3과 7을 더하고, 그 결과에 5를 곱해주세요"`
- **시나리오 B** — 번역만: `"Hello, how are you?를 한국어로 번역해주세요"`
- **시나리오 C** — 복합 요청 (수학 + 번역): `"123 곱하기 456을 계산하고, 그 결과를 영어 문장으로 설명해주세요"`

시나리오 C는 Supervisor가 먼저 Math Agent를 호출하고, 결과를 받아 Translate Agent를 호출하는 **순차 위임** 패턴을 보여준다.

---

## 3. State 설계

### 3.1 메인 그래프 State

```python
class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    next_agent: str
    plan: str
    completed_agents: list[str]
```

| 필드 | 타입 | 리듀서 | 역할 |
|------|------|--------|------|
| `messages` | `list[BaseMessage]` | `add_messages` | 전체 대화 이력. 리듀서가 중복 없이 자동 병합 |
| `next_agent` | `str` | 없음 | Supervisor가 결정한 다음 에이전트 |
| `plan` | `str` | 없음 | Supervisor의 실행 계획 |
| `completed_agents` | `list[str]` | 없음 | 완료된 에이전트 이력 |

`Annotated[list[BaseMessage], add_messages]`에서 [`add_messages`](https://reference.langchain.com/python/langgraph/graph/message)는 LangGraph가 제공하는 리듀서 함수로, 메시지 리스트를 병합할 때 ID 기반으로 중복을 제거한다. ([참고: add_messages 리듀서 가이드](https://dev.to/aiengineering/a-beginners-guide-to-getting-started-with-addmessages-reducer-in-langgraph-4gk0)) 이 리듀서가 없으면 각 노드가 반환하는 메시지가 기존 리스트를 덮어쓰게 된다.

### 3.2 서브그래프 WorkerState

```python
class WorkerState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
```

메인 그래프의 `messages`를 서브그래프에 전달하고, 서브그래프의 **최종 결과만** 메인 그래프로 반환한다. 이 분리로 서브그래프 내부의 중간 메시지(`tool_calls`, `ToolMessage` 등)가 메인 그래프를 오염시키지 않는다.

### 3.3 State 분리 설계의 근거

LangGraph는 부모-자식 그래프 간 상태 전달에 두 가지 시나리오를 지원한다. ([참고: LangGraph Subgraph 공식 문서](https://docs.langchain.com/oss/python/langgraph/use-subgraphs))

1. **겹치는 상태 키**: 부모와 서브그래프 스키마가 겹치면 상태가 직접 전달된다. 겹치는 키만 병합되고, 서브그래프 내부 키는 격리된다.
2. **분리된 상태 스키마**: 수동 변환이 필요하며, 부모 노드가 서브그래프를 호출하고 상태를 명시적으로 매핑한다.

이 프로젝트는 시나리오 1을 활용한다. `WorkerState`의 `messages`가 `State`의 `messages`와 키가 같으므로 자동 전달되고, `next_agent`, `plan`, `completed_agents`는 서브그래프에 전달되지 않는다.

> **대안과 비교**: 서브그래프 없이 모든 에이전트를 메인 그래프의 노드로 직접 배치하는 방식도 가능하다. 그러나 이 경우 도구 호출의 중간 메시지(`ToolMessage`)가 메인 `messages`에 누적되어 Supervisor가 불필요한 컨텍스트를 읽게 된다. 서브그래프 격리는 이 문제를 구조적으로 해결한다.

---

## 4. Supervisor 구현

### 4.1 역할

Supervisor는 에이전트이면서 동시에 오케스트레이터이다. LLM을 호출하여 다음에 실행할 에이전트를 결정한다.

### 4.2 실행 흐름

1. `_build_system_prompt()`: 레지스트리에서 워커 목록, 현재 계획, 완료된 에이전트를 조합하여 시스템 프롬프트 생성
2. `supervisor_node()`: LLM 호출 → JSON 응답 파싱 → `next_agent`, `plan` 반환
3. `supervisor_router()`: `next_agent` 값에 따라 해당 에이전트 노드 또는 END로 라우팅

### 4.3 JSON 라우팅 프로토콜

Supervisor LLM은 다음 형태의 JSON을 반환한다:

```json
{"next": "<agent_name>", "reason": "결정 근거", "plan": "실행 계획"}
```

- `next`: 다음 에이전트의 라우팅 키 또는 `"FINISH"`
- `reason`: 결정 근거
- `plan`: 전체 실행 계획 (State에 저장되어 다음 호출 시 참조)

### 4.4 시스템 프롬프트 동적 생성

```python
def _build_system_prompt(plan, completed_agents):
    choices = '" 또는 "'.join(registry.agent_names + ["FINISH"])
    return SUPERVISOR_SYSTEM_PROMPT.format(
        workers=registry.build_workers_prompt(),
        agent_choices=choices,
        plan=plan,
        completed_agents=", ".join(completed_agents) if completed_agents else "없음",
    )
```

`registry.agent_names`로 선택지 목록을, `registry.build_workers_prompt()`로 에이전트 설명을 동적으로 생성한다. 에이전트를 추가하면 프롬프트가 자동으로 확장되므로 수동 수정이 불필요하다.

### 4.5 JSON 추출 로직

```python
def extract_json_from_text(text: str) -> dict:
    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + len("```")
        end = text.index("```", start)
        text = text[start:end].strip()
    return json.loads(text)
```

LLM이 JSON을 markdown 코드 블록으로 감싸서 반환하는 경우를 처리한다. `` ```json `` 블록, 일반 `` ``` `` 블록, 또는 직접 JSON 문자열의 세 가지 경우를 순차적으로 시도한다.

### 4.6 안전 장치

**JSON 파싱 실패 시 FINISH**: 파싱이 실패하면 `next_agent: "FINISH"`로 안전 종료한다. 이는 LLM이 예기치 않은 형식으로 응답하더라도 시스템이 무한 루프에 빠지지 않도록 보장한다.

```python
except (json.JSONDecodeError, ValueError) as e:
    logger.warning("JSON 파싱 실패: %s → FINISH로 안전 종료", e)
    return {
        "messages": [AIMessage(content=content)],
        "next_agent": "FINISH",
        "plan": plan,
    }
```

**MAX_ITERATIONS = 5**: `completed_agents` 수가 5 이상이면 강제 종료하여 무한 루프를 방지한다.

```python
if len(completed) >= MAX_ITERATIONS:
    router_logger.warning("최대 반복 횟수(%d) 도달 → END", MAX_ITERATIONS)
    return END
```

### 4.7 모델 선택: gpt-4o-mini

Supervisor는 `gpt-4o-mini`를 사용한다. 라우팅 결정은 상대적으로 단순한 JSON 생성 작업이므로 비용 효율적인 소형 모델이 적합하다. 복잡한 추론이 필요한 경우 `gpt-4o`나 `gpt-4-turbo`로 교체할 수 있다.

> **대안 분석**: LangGraph의 [`create_supervisor()`](https://github.com/langchain-ai/langgraph-supervisor-py) 유틸리티를 사용하면 [handoff 도구 기반](https://reference.langchain.com/python/langgraph-supervisor)으로 에이전트 간 전환을 자동화할 수 있다. 그러나 이 프로젝트는 JSON 프로토콜을 직접 구현하여 라우팅 로직에 대한 완전한 제어권을 유지한다. 이는 커스텀 `plan` 필드나 `completed_agents` 추적 같은 프로젝트 고유 요구사항을 자연스럽게 수용한다.

---

## 5. Subagent 구현 패턴

### 5.1 공통 구조

모든 subagent는 동일한 패턴을 따른다:

1. **wrapper 함수** — `State`를 받아 서브그래프/LLM을 실행하고 결과를 `State` 형태로 반환
2. **`completed_agents` 업데이트** — 자신의 이름을 추가하여 Supervisor가 진행 상황을 추적할 수 있게 함
3. **결과 태깅** — 접두어(예: `[수학 계산 결과]`, `[번역 결과]`)를 붙여 메시지 출처를 명확히 함

### 5.2 ReAct 패턴 — Math Agent

```
[math_agent_node] --> (tool_calls?) --> [tool_executor_node] --> [math_agent_node] --> ... --> [END]
```

ReAct(Reasoning + Acting)는 [Yao et al.(2022)](https://arxiv.org/abs/2210.03629)이 제안한 패턴으로, LLM이 추론 흔적(reasoning trace)을 생성한 후 도구를 호출하고, 결과를 관찰하여 다음 행동을 결정하는 순환 구조이다. 이 논문은 [ICLR 2023](https://github.com/ysymyth/ReAct)에서 발표되었다.

**Math Agent의 구현:**

```python
# 도구 정의 (@tool 데코레이터: https://docs.langchain.com/oss/python/langchain/tools)
@tool
def add(a: float, b: float) -> float:
    """두 수를 더한다."""
    return a + b

@tool
def multiply(a: float, b: float) -> float:
    """두 수를 곱한다."""
    return a * b

@tool
def divide(a: float, b: float) -> str:
    """두 수를 나눈다. 0으로 나누면 오류 메시지를 반환한다."""
    if b == 0:
        return "오류: 0으로 나눌 수 없습니다."
    return str(a / b)
```

[`@tool` 데코레이터](https://docs.langchain.com/oss/python/langchain/tools)는 `langchain_core`가 제공하며, 함수를 LLM이 호출 가능한 도구로 변환한다. docstring이 도구 설명으로 사용되므로 LLM이 언제 어떤 도구를 사용할지 결정할 수 있다.

**서브그래프 빌드:**

```python
def build_math_agent() -> CompiledStateGraph:
    graph = StateGraph(WorkerState)
    graph.add_node("agent", math_agent_node)
    graph.add_node("tools", tool_executor_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()
```

`should_continue` 함수가 LLM 응답에 `tool_calls`가 있는지 확인하여 루프를 계속할지 종료할지 결정한다.

**커스텀 tool_executor_node**: LangGraph의 내장 `ToolNode` 대신 커스텀 노드를 사용하는 이유는 `@log_node` 데코레이터를 적용하여 도구 호출을 로깅하기 위함이다. 또한 각 도구 실행에 대한 개별 에러 핸들링이 가능하다.

```python
@log_node("math_tool_executor")
def tool_executor_node(state: WorkerState) -> dict:
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", [])

    results: list[ToolMessage] = []
    for tc in tool_calls:
        tool_fn = MATH_TOOLS_BY_NAME.get(tc["name"])
        if tool_fn is None:
            results.append(ToolMessage(
                content=f"오류: 알 수 없는 tool '{tc['name']}'",
                tool_call_id=tc["id"],
            ))
            continue
        try:
            result = tool_fn.invoke(tc["args"])
            results.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        except Exception:
            results.append(ToolMessage(
                content=f"오류: {tc['name']} 실행 중 예외 발생",
                tool_call_id=tc["id"],
            ))
    return {"messages": results}
```

**wrapper 함수:**

```python
@registry.agent("math")
def math_wrapper(state: State) -> dict:
    """수학 계산을 수행합니다. 덧셈, 곱셈, 나눗셈 등의 계산이 필요할 때 사용합니다."""
    result = math_subgraph.invoke({"messages": state["messages"]})
    last_message = result["messages"][-1]
    completed = list(state.get("completed_agents", []))
    completed.append("math")
    return {
        "messages": [AIMessage(content=f"[수학 계산 결과]\n{last_message.content}")],
        "completed_agents": completed,
    }
```

서브그래프에 `messages`만 전달하고, 최종 메시지만 추출하여 메인 그래프에 반환한다. 서브그래프 내부의 `ToolMessage` 등 중간 과정은 메인 그래프에 노출되지 않는다.

### 5.3 단순 LLM 호출 패턴 — Translate Agent

```
[translate_agent_node] --> (결과 반환)
```

도구가 필요 없는 작업에 적합한 패턴이다.

```python
TRANSLATE_SYSTEM_PROMPT = """당신은 전문 번역가입니다.
주어진 텍스트를 정확하고 자연스럽게 번역하세요.

규칙:
1. 한국어 텍스트는 영어로 번역합니다.
2. 영어 텍스트는 한국어로 번역합니다.
3. 번역 결과만 깔끔하게 출력하세요.
4. 원문의 뉘앙스와 톤을 유지하세요."""

@log_node("translate_agent_internal")
def translate_agent_node(state: WorkerState) -> dict:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    messages = [SystemMessage(content=TRANSLATE_SYSTEM_PROMPT)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}

@registry.agent("translate")
def translate_wrapper(state: State) -> dict:
    """텍스트를 번역합니다. 한국어↔영어 번역이 필요할 때 사용합니다."""
    result = translate_agent_node({"messages": state["messages"]})
    last_message = result["messages"][-1]
    completed = list(state.get("completed_agents", []))
    completed.append("translate")
    return {
        "messages": [AIMessage(content=f"[번역 결과]\n{last_message.content}")],
        "completed_agents": completed,
    }
```

서브그래프 없이 LLM을 직접 호출하므로 오버헤드가 최소화된다. `@log_node` 데코레이터로 실행 시간과 상태 변화를 추적한다.

### 5.4 두 패턴의 선택 기준

| 기준 | ReAct (도구 사용) | 단순 LLM 호출 |
|------|-------------------|--------------|
| 외부 도구/API 필요 | O | X |
| 다단계 추론 | O | X |
| 구현 복잡도 | 높음 (서브그래프) | 낮음 (함수 호출) |
| 실행 비용 | 높음 (여러 LLM 호출) | 낮음 (1회 호출) |
| 적합 사례 | 수학 계산, 웹 검색, DB 쿼리 | 번역, 요약, 분류 |

---

## 6. Agent Registry

### 6.1 해결하는 문제

멀티 에이전트 시스템에서 새 에이전트를 추가할 때 일반적으로 세 곳을 수정해야 한다:

1. 그래프 빌드 코드에 노드와 엣지 추가
2. Supervisor 시스템 프롬프트에 새 에이전트 설명 추가
3. 라우터 함수에 if-elif 분기 추가

이 분산된 수정은 누락 위험이 높고, 에이전트 수가 늘어날수록 관리 비용이 선형으로 증가한다. Agent Registry는 이 세 가지 관심사를 하나의 등록 지점으로 통합한다.

### 6.2 핵심 컴포넌트

**AgentEntry** — 에이전트 메타데이터:

```python
@dataclass
class AgentEntry:
    name: str                           # 라우팅 키 ("math", "translate")
    node_name: str                      # 그래프 노드 이름 ("math_agent")
    wrapper: Callable[[State], dict]    # 실행할 wrapper 함수
    description: str                    # Supervisor 프롬프트에 삽입될 설명
```

`name`과 `node_name`을 분리한 이유: Supervisor에게는 짧고 직관적인 이름(`"math"`)을, 그래프에는 역할이 명확한 이름(`"math_agent"`)을 사용하기 위함이다.

**AgentRegistry** — 레지스트리:

```python
class AgentRegistry:
    _entries: list[AgentEntry]          # 등록 순서 보존
    _by_name: dict[str, AgentEntry]     # O(1) 이름 조회
```

두 가지 내부 저장소를 유지한다:
- `_entries` — 등록 순서를 보존하는 리스트. 그래프 빌드와 프롬프트 생성 시 순회에 사용
- `_by_name` — 이름 기반 O(1) 조회용 딕셔너리. 라우터에서 매 라우팅 결정마다 호출되므로 성능이 중요

### 6.3 API 상세

**`register()` 메서드:**

```python
def register(self, name, wrapper, *, node_name=None, description=None):
    resolved_node_name = node_name or f"{name}_agent"
    resolved_description = description or (wrapper.__doc__ or "").strip()
    if not resolved_description:
        raise ValueError(f"에이전트 '{name}'의 description이 없습니다.")
    # ...
```

description 결정 순서: (1) `description` 파라미터 직접 전달 → (2) `wrapper.__doc__` (docstring) 추출 → (3) 둘 다 없으면 `ValueError` 발생.

description을 필수로 강제하는 이유: Supervisor의 시스템 프롬프트에 각 에이전트의 설명이 포함되어야 LLM이 올바른 라우팅 결정을 내릴 수 있다. description 없는 에이전트는 Supervisor가 언제 호출해야 하는지 판단할 수 없으므로 등록 자체를 거부한다.

`node_name` 미지정 시 `f"{name}_agent"` 형태로 자동 생성된다.

**`@registry.agent()` 데코레이터:**

```python
@registry.agent("math")
def math_wrapper(state: State) -> dict:
    """수학 계산을 수행합니다. 덧셈, 곱셈, 나눗셈 등의 계산이 필요할 때 사용합니다."""
    ...
```

데코레이터는 **원본 함수를 그대로 반환**한다(`return func`). 함수를 감싸거나 동작을 변경하지 않으므로, 데코레이터 적용 후에도 함수를 직접 호출할 수 있다. 이는 평가 시스템에서 `entry.wrapper(state)`로 wrapper를 직접 호출하는 것을 가능하게 한다.

**`build_workers_prompt()`:**

```python
registry.build_workers_prompt()
# → "- **math**: 수학 계산을 수행합니다. ...\n- **translate**: 텍스트를 번역합니다. ..."
```

등록된 모든 에이전트의 이름과 description을 Markdown 리스트로 포맷한다. 이 문자열은 Supervisor의 시스템 프롬프트에 `{workers}` 플레이스홀더로 삽입된다.

**`entries` 프로퍼티:**

방어적 복사(`list(self._entries)`)를 반환하여 외부에서 내부 리스트를 변경할 수 없게 한다.

### 6.4 등록 트리거 메커니즘

`@registry.agent` 데코레이터는 **모듈 import 시점**에 실행된다:

```python
# src/agents/__init__.py
from src.agents.math_agent import math_wrapper      # → @registry.agent("math") 실행
from src.agents.translate_agent import translate_wrapper  # → @registry.agent("translate") 실행
```

새 에이전트를 추가할 때 이 파일에 import를 한 줄 추가하면 된다.

### 6.5 글로벌 인스턴스

```python
# src/agents/registry.py 하단
registry = AgentRegistry()
```

모듈 레벨에서 단일 인스턴스를 생성한다. Python 모듈은 한 번만 로드되므로 이 인스턴스는 프로세스 내에서 **싱글턴**으로 동작한다. 별도의 싱글턴 패턴이나 DI 컨테이너 없이 모듈 시스템 자체의 특성을 활용한 설계다.

### 6.6 프로젝트 내 통합 지점

레지스트리는 프로젝트의 세 가지 핵심 컴포넌트에서 사용된다:

1. **그래프 빌드** (`src/main.py`): 레지스트리를 순회하며 노드 등록, 엣지 연결
2. **Supervisor 라우팅** (`supervisor.py`): 프롬프트 생성 + 라우터 분기
3. **평가 시스템** (`evals/runner.py`): wrapper 직접 조회 및 호출

### 6.7 새 에이전트 추가 체크리스트

1. `src/agents/new_agent/agent.py` 생성
2. wrapper 함수에 `@registry.agent("name")` 적용 + docstring 작성
3. `src/agents/__init__.py`에 `from src.agents.new_agent import new_wrapper` 추가

수정이 필요 **없는** 파일: `src/main.py`, `supervisor.py`, `evals/`

> **대안 분석 — 레지스트리 패턴 선택지:**
>
> | 접근법 | 장점 | 단점 | 적합 사례 |
> |--------|------|------|----------|
> | **데코레이터 기반** (이 프로젝트) | 사용이 간편, 정의 시점에 자동 등록 | import 순서에 의존 | 내부 시스템, 알려진 확장 |
> | **[entry_points](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)** (setuptools) | 서드파티 패키지가 확장 가능 | 설정 복잡, 패키징 필요 | 프레임워크, 에코시스템 확장 |
> | **명시적 등록** | 제어권 최대, 이해 용이 | 코드가 장황 | 런타임 등록, 조건부 등록 |
>
> 이 프로젝트는 **에이전트가 모두 단일 패키지 내에 존재**하는 구조이므로 데코레이터 기반이 가장 적합하다. 서드파티 플러그인 지원이 필요하다면 `entry_points` 방식으로 전환해야 한다. ([참고: Python Packaging — Entry Points Specification](https://packaging.python.org/specifications/entry-points/))

---

## 7. 로깅 시스템

### 7.1 설계 원칙

1. **어떤 노드가 실행 중인지 명확히 표시** — 복잡한 그래프 순환에서 현재 위치를 즉시 파악
2. **상태 변화를 git diff 스타일로 시각화** — 노드 실행 전후의 State 변경을 한눈에 파악
3. **LLM 응답을 원문 그대로 기록** — 요약이나 truncation 없이 디버깅에 필요한 모든 정보 보존

### 7.2 구조

```
src/logging/
├── __init__.py       # setup_logging, get_logger, log_node export
├── config.py         # 로거 설정 (포맷, 핸들러)
├── decorator.py      # @log_node 데코레이터
└── diff.py           # 상태 포맷팅 + diff 계산
```

### 7.3 로거 네이밍 체계

모든 로거는 `supervisor_subagent` 루트 아래에 계층적으로 구성된다.

```
supervisor_subagent
├── main              # 엔트리포인트
├── supervisor        # Supervisor 내부 동작
├── router.*          # 라우팅 결정
├── agent.*           # 에이전트 내부 동작
└── node.*            # @log_node 데코레이터 출력
```

이 계층 구조로 `node` 레벨을 필터링하면 데코레이터 로그만, `router` 레벨로 라우팅 결정만 선택적으로 확인할 수 있다.

### 7.4 @log_node 데코레이터

```python
@log_node("node_name")
def some_node(state: State) -> dict:
    ...
```

모든 노드 함수에 동일한 로깅 패턴(진입 → 실행 → 완료/실패)을 노드 로직 수정 없이 적용한다.

**진입**: `========` 구분선으로 현재 노드 강조
**완료**: 실행 시간 + State 변화를 git diff 스타일로 출력
**실패**: `!!!` 구분선 + traceback (`exc_info=True`)

**출력 예시:**

```
------------------------------------------------------------
  [SUPERVISOR] Completed (1.234s)
------------------------------------------------------------
  State:
  messages: (list[BaseMessage]) 2 messages
    [0] type: HumanMessage, content: 입력 텍스트
+   [1] type: AIMessage, content:
+       {
+         "next": "math",
+         "reason": "수학 계산 필요"
+       }
-   next_agent: (str) ''
+   next_agent: (str) 'math'
  completed_agents: (list) []
------------------------------------------------------------
```

### 7.5 상태 diff 포매터

**git diff 스타일:**

| Prefix | 의미 |
|--------|------|
| (공백) | 변경 없음 |
| `+` | 추가된 값 |
| `-` | 제거된 값 |
| `-` / `+` 쌍 | 값이 변경됨 |

개발자가 이미 익숙한 `git diff` 시각 언어를 활용하여 학습 비용 없이 상태 변화를 파악할 수 있다. `+` marker는 기존 들여쓰기의 공백을 대체하여 정렬을 유지한다.

**타입 정보**: 모든 필드에 런타임 타입이 표시된다 — `(str)`, `(list[str])`, `(list[BaseMessage])` 등.

**메시지 콘텐츠 포맷팅:**
- JSON이면 파싱 후 pretty-print
- 일반 텍스트는 원문 그대로 출력
- `tool_calls`는 raw JSON으로 name, args, id 전체 출력
- 빈 콘텐츠는 생략

### 7.6 로깅 레벨

| 레벨 | 용도 |
|------|------|
| `INFO` | 정상 실행 흐름 (LLM 호출, 노드 진입/완료, 라우팅 결정) |
| `WARNING` | 복구 가능한 문제 (JSON 파싱 실패 → FINISH 폴백, MAX_ITERATIONS 도달) |
| `ERROR` | 실패 (LLM API 오류, 도구 실행 예외, 서브그래프 실행 실패). `exc_info=True` 포함 |

### 7.7 구현 세부 사항

**`_prefix_lines()` 함수**는 여러 줄 텍스트의 각 줄 선두에 `+`/`-` marker를 삽입하되, 기존 들여쓰기의 공백을 대체하여 정렬을 유지한다:

```python
def _prefix_lines(text: str, marker: str) -> str:
    result = []
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        indent_len = len(line) - len(stripped)
        if indent_len >= len(marker):
            new_line = marker + " " * (indent_len - len(marker)) + stripped
        else:
            new_line = marker + stripped
        result.append(new_line)
    return "\n".join(result)
```

**`format_state_diff()` 함수**는 `before`(노드 실행 전 상태)와 `after`(노드 반환값)를 비교한다. `messages` 필드는 특별 처리하여 기존 메시지 목록에 새로 추가된 메시지만 `+`로 표시한다.

---

## 8. 평가 시스템 (LLM-as-Judge)

### 8.1 개요

**LLM-as-Judge** 방식으로 각 에이전트의 출력 품질을 자동 평가한다. Judge LLM이 에이전트의 실제 출력을 모범 답안과 비교하여 여러 기준에 대해 1~10점으로 채점한다.

### 8.2 LLM-as-Judge를 선택한 이유

- 숫자 정확도 같은 단순 검증은 rule-based로 가능하지만, **논리적 풀이 과정**이나 **번역 자연스러움**은 LLM 판단이 필요
- 에이전트 유형에 관계없이 동일한 파이프라인에서 **기준만 교체**하면 됨

LLM-as-Judge는 인간 평가를 프로덕션 트래픽 규모로 확장할 수 있는 방법론이다. 다만 사전 배포 단계에서 인간 판단과의 검증이 필요하며, [위치 편향(position bias)](https://arxiv.org/abs/2406.07791) 등의 한계가 알려져 있다. ([참고: A Survey on LLM-as-a-Judge](https://arxiv.org/abs/2411.15594))

### 8.3 구조

```
evals/
├── run.py              # CLI 엔트리포인트
├── runner.py           # 테스트 실행 오케스트레이션
├── judge.py            # Judge LLM 호출 + 응답 파싱
├── prompts.py          # Judge 프롬프트 템플릿
└── types.py            # TypedDict 정의

res/                    # 테스트 케이스 YAML (재귀 수집)
```

### 8.4 실행 흐름

1. `res/` 하위 모든 YAML 수집 → `eval_config` + `test_cases` 파싱
2. 각 test_case: registry에서 wrapper 조회 → **직접 호출** → Judge LLM 평가
3. `pass_threshold` 기준 PASS/FAIL 판정 → 콘솔 리포트

**wrapper 직접 호출 방식**: 전체 그래프(Supervisor → Agent)를 실행하지 않고 wrapper를 직접 호출한다.

- **격리된 평가**: Supervisor 라우팅 오류가 subagent 평가에 영향 없음
- **빠른 피드백**: 전체 파이프라인 대비 실행 시간 단축

```python
def _invoke_agent(target_agent, input_text, state_overrides):
    entry = registry.get(target_agent)
    state = {
        "messages": [HumanMessage(content=input_text)],
        "next_agent": "",
        "plan": "",
        "completed_agents": [],
    }
    if state_overrides:
        state.update(state_overrides)
    result = entry.wrapper(state)
    return result["messages"][-1].content
```

### 8.5 테스트 케이스 작성

**YAML 스키마:**

```yaml
eval_config:
  judge_model: "gpt-4o"
  judge_temperature: 0.0
  pass_threshold: 7.0
  agent_criteria:
    math:
      - correctness
      - step_reasoning
    translate:
      - correctness
      - fluency
      - naturalness

test_cases:
  - id: "math_simple_add"
    description: "단순 덧셈"
    target_agent: "math"
    input: "3과 7을 더해주세요"
    reference_answer: "3 + 7 = 10. 결과는 10입니다."
```

**다중 파일 지원**: `res/` 하위의 `*.yaml`/`*.yml`을 재귀 수집한다. `eval_config`는 첫 번째 파일에서, `test_cases`는 전체에서 병합한다.

### 8.6 평가 기준

**기준 결정 우선순위:**

1. 테스트 케이스의 `eval_criteria` (케이스 레벨 override)
2. `eval_config.agent_criteria[target_agent]` (에이전트 유형별 기본값)
3. `["correctness"]` (fallback)

**기본 제공 기준:**

| 기준 | 설명 |
|------|------|
| `correctness` | 결과의 정확성. 모범 답안의 핵심 내용과 일치하는지 |
| `step_reasoning` | 풀이 과정의 논리성. 중간 단계가 명확한지 |
| `fluency` | 문장의 유창성. 문법적으로 자연스러운지 |
| `naturalness` | 번역의 자연스러움. 원어민 수준인지 |
| `formality` | 격식체 적절성. 비즈니스 상황에 맞는 어조인지 |

### 8.7 Judge 프롬프트

Judge 시스템 프롬프트에는 채점 기준(1~3: 매우 부족, 4~6: 보통, 7~8: 우수, 9~10: 탁월)과 각 평가 기준의 설명이 포함된다. Judge는 JSON 형식으로 응답한다:

```json
{
  "scores": {
    "<criterion>": {"score": 9, "reason": "근거"}
  },
  "overall_score": 8.5,
  "summary": "전체 평가 요약"
}
```

**파싱 실패 시**: 모든 기준 0점 + 에러 메시지를 기록하여 평가 결과 누락 없이 실패를 표시한다.

### 8.8 타입 시스템

평가 시스템은 `TypedDict`를 활용하여 타입 안전성을 확보한다:

```python
class ScoreDetail(TypedDict):
    score: int
    reason: str

class JudgeResult(TypedDict):
    scores: dict[str, ScoreDetail]
    overall_score: float
    summary: str

class TestCase(TypedDict):
    id: str
    description: str
    target_agent: str
    input: str
    reference_answer: str
    state_overrides: NotRequired[dict[str, Any]]
    eval_criteria: NotRequired[list[str]]
```

### 8.9 CLI

```bash
uv run python -m evals.run                          # 전체 실행
uv run python -m evals.run --filter <id_substring>  # ID 필터
uv run python -m evals.run --agent <agent_name>     # 에이전트 필터
```

Exit code: `0` (all pass) / `1` (any fail). CI 품질 게이트에 활용 가능하다.

### 8.10 결과 출력 형식

```
============================================================
  EVALUATION RESULTS (judge: gpt-4o)
============================================================

[1/6] math_simple_add - 단순 덧셈 ................. PASS (9.0, 2.3s)
  ✓ correctness    : 9/10 - 정확한 결과
  ✓ step_reasoning : 9/10 - 명확한 풀이 과정

[2/6] translate_formal - 격식체 번역 ............... FAIL (6.5, 1.8s)
  ✓ correctness    : 8/10 - 의미 전달 정확
  ✗ formality      : 5/10 - 격식체 부족
------------------------------------------------------------
  SUMMARY: 5/6 passed (threshold: 7.0)
  Failed: translate_formal
  Total time: 12.3s
------------------------------------------------------------
```

---

## 9. 기술적 선택과 대안 분석

### 9.1 프레임워크 선택: LangGraph vs 대안

이 프로젝트가 [LangGraph](https://www.langchain.com/langgraph)를 선택한 근거와, 대안 프레임워크와의 비교이다. ([참고: DataCamp 비교 분석](https://www.datacamp.com/tutorial/crewai-vs-langgraph-vs-autogen), [Galileo AI 비교](https://galileo.ai/blog/mastering-agents-langgraph-vs-autogen-vs-crew))

| 프레임워크 | 설계 철학 | 강점 | 약점 |
|-----------|----------|------|------|
| **[LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api)** | 그래프 기반 워크플로우 | 세밀한 제어, 순환 지원, 상태 지속성, [LangSmith](https://www.langchain.com/langsmith/observability) 통합 | 학습 곡선 높음, 빠르게 변화하는 API |
| **[CrewAI](https://www.crewai.com/)** | 역할 기반 팀 모델 | 직관적, 빠른 프로토타이핑, YAML 기반 | 복잡한 상태 동기화 한계, 유연성 부족 |
| **[AutoGen](https://github.com/microsoft/autogen)** | 대화 기반 에이전트 협업 | 비동기 아키텍처, 유연한 상호작용 | 일관성 없는 출력, [Microsoft Agent Framework로 이관 중](https://learn.microsoft.com/en-us/agent-framework/migration-guide/from-autogen/) |
| **[OpenAI Swarm](https://github.com/openai/swarm)** | 경량 프레임워크 | LangGraph보다 가벼움, 학습 용이 | 실험적/교육용, 무상태 설계, 프로덕션 부적합 |

**LangGraph를 선택해야 하는 경우:**
- 복잡한 조건부 분기와 순환이 필요한 워크플로우
- 상태 지속성이 필요한 프로덕션 파이프라인
- LangChain 에코시스템과의 통합
- 각 노드의 실행을 세밀하게 제어해야 하는 경우

**이 프로젝트에서의 defense:** Supervisor-Subagent 패턴은 순환(Supervisor → Agent → Supervisor)이 핵심이다. LangGraph는 순환 그래프를 네이티브로 지원하므로 이 패턴을 자연스럽게 표현할 수 있다. CrewAI의 선형/팀 기반 모델로는 동적 라우팅을 구현하기 어렵다.

**AutoGen 현황 참고**: Microsoft는 2025년 10월에 AutoGen을 Semantic Kernel과 통합한 [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)를 공개 프리뷰로 출시했다. AutoGen은 유지보수 모드로 전환되어 신규 기능 투자 없이 버그 수정과 보안 패치만 제공된다. ([출처: VentureBeat](https://venturebeat.com/ai/microsoft-retires-autogen-and-debuts-agent-framework-to-unify-and-govern), [Microsoft 공식 문서](https://learn.microsoft.com/en-us/agent-framework/overview/agent-framework-overview))

### 9.2 라우팅 방식: JSON 프로토콜 vs 함수 호출(Tool Use)

**이 프로젝트의 선택: JSON 프로토콜**

Supervisor가 JSON 문자열을 생성하여 다음 에이전트를 지정한다.

- 장점: 완전한 제어권 (plan, reason 등 커스텀 필드 추가 가능), 구현이 투명
- 단점: JSON 파싱 실패 가능성, LLM이 형식을 준수하지 않을 수 있음

**대안: [LangGraph Handoff Tools](https://github.com/langchain-ai/langgraph-supervisor-py)**

LangGraph의 [`create_supervisor()`](https://reference.langchain.com/python/langgraph-supervisor)는 handoff 도구를 사용하여 에이전트 전환을 구현한다. ([참고: LangGraph Supervisor 발표](https://changelog.langchain.com/announcements/langgraph-supervisor-a-library-for-hierarchical-multi-agent-systems))

- 장점: 프레임워크가 라우팅을 관리, 파싱 로직 불필요
- 단점: 커스텀 메타데이터(plan, reason) 전달 제한, 프레임워크에 대한 의존성 증가

**대안: Structured Output (Pydantic)**

[`ChatOpenAI`의 `with_structured_output()`](https://docs.langchain.com/oss/python/integrations/chat/openai) 메서드로 Pydantic 모델을 사용하여 타입 안전한 출력을 강제할 수 있다. ([API 레퍼런스](https://api.python.langchain.com/en/latest/openai/chat_models/langchain_openai.chat_models.base.ChatOpenAI.html))

- 장점: 파싱 실패 가능성 제거, 타입 검증 자동화
- 단점: 모델 호환성 제한, 디버깅 시 원본 텍스트 확인 어려움, `bind_tools()`와 동시 사용 시 비호환 이슈 존재 ([관련 이슈](https://github.com/langchain-ai/langchain/issues/28848))

**defense:** JSON 프로토콜은 구현이 투명하고 디버깅이 용이하다. 파싱 실패 시 FINISH 폴백으로 안전성을 보장하며, `plan`과 `reason` 같은 커스텀 필드를 자유롭게 확장할 수 있다. 프로덕션 환경에서는 Structured Output으로 전환하는 것이 더 안정적일 수 있다.

### 9.3 평가 방식: LLM-as-Judge vs 대안

| 방식 | 장점 | 단점 | 적합 사례 |
|------|------|------|----------|
| **LLM-as-Judge** (이 프로젝트) | 유연한 기준 정의, 자연어 평가 가능, 확장 용이 | [위치 편향](https://arxiv.org/abs/2406.07791), [자기 강화 편향](https://arxiv.org/abs/2410.21819), 세밀한 점수 구분 불안정 | 번역 자연스러움, 논리적 추론 평가 |
| **Rule-based** | 결정적, 빠름, 비용 없음 | 복잡한 품질 판단 불가 | 숫자 정확도, 형식 검증 |
| **RAGAS** | 다차원 평가, RAG 특화 | RAG 외 사용 제한적 | RAG 파이프라인 평가 |
| **Human-in-the-Loop** | 가장 정확한 판단 | 느림, 비용 높음, 확장 어려움 | 최종 검증, 캘리브레이션 |

**이 프로젝트에서의 defense:** Math Agent의 "풀이 과정 논리성(`step_reasoning`)"이나 Translate Agent의 "번역 자연스러움(`naturalness`)"은 rule-based로 평가하기 어렵다. LLM-as-Judge는 이러한 주관적 품질 기준을 일관되게 평가할 수 있다.

**알려진 한계와 완화 방안:**
- **위치 편향**: 이 프로젝트는 단일 출력 채점 방식(reference와 비교)을 사용하므로 위치 편향이 최소화된다. ([연구: Judging the Judges](https://arxiv.org/abs/2406.07791), [ACL 2025 발표](https://aclanthology.org/2025.ijcnlp-long.18.pdf))
- **세밀한 점수 구분 불안정**: `pass_threshold: 7.0`으로 이진 판정(PASS/FAIL)을 사용하여 점수 경계의 불안정성을 완화한다
- **Judge 모델**: `gpt-4o`를 사용하여 판단 품질을 최대화한다 (에이전트는 `gpt-4o-mini` 사용)
- **포괄적 편향 분류**: LLM-as-Judge의 12가지 편향 유형에 대한 체계적 분석은 [Justice or Prejudice? (CALM)](https://arxiv.org/abs/2410.02736)를 참고

### 9.4 상태 격리: 서브그래프 vs 단일 그래프

**이 프로젝트의 선택:** 도구 사용 에이전트(Math)는 서브그래프로, 단순 LLM 에이전트(Translate)는 함수 호출로 구현한다. ([LangGraph Subgraph 문서](https://docs.langchain.com/oss/python/langgraph/use-subgraphs))

**대안: 모든 에이전트를 메인 그래프에 직접 배치**

- 장점: 구현 단순, 전체 상태 공유
- 단점: `ToolMessage` 등 중간 메시지가 메인 `messages`에 누적, Supervisor의 컨텍스트 오염

**대안: 모든 에이전트를 서브그래프로**

- 장점: 일관된 격리, 예측 가능한 동작
- 단점: 단순 에이전트에 불필요한 오버헤드

**defense:** 이 프로젝트의 하이브리드 접근법은 복잡도에 따라 적절한 격리 수준을 선택한다. 도구 사용 에이전트는 서브그래프로 중간 메시지를 격리하고, 단순 에이전트는 직접 호출로 오버헤드를 최소화한다.

### 9.5 레지스트리 패턴: 데코레이터 vs 대안

이 주제는 6.7절의 대안 분석에서 상세히 다루었다. 핵심 요약: 단일 패키지 내 에이전트 관리에는 데코레이터 기반이 최적이며, 서드파티 확장이 필요하면 [`entry_points`](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)로 전환해야 한다.

### 9.6 로깅: git diff 스타일 vs 대안

**대안: 구조화된 로깅 (JSON)**

Datadog, ELK 등 로그 분석 도구와 통합하기 쉽다. 그러나 터미널에서의 가독성이 낮다.

**대안: [LangSmith 트레이싱](https://docs.langchain.com/oss/python/langgraph/observability)**

LangGraph 생태계의 기본 관측성 도구이다. 토큰 사용량, 실행 시간, 노드별 트레이스를 UI에서 확인할 수 있다. ([LangSmith 제품 페이지](https://www.langchain.com/langsmith/observability))

**defense:** git diff 스타일은 개발 단계에서 터미널 디버깅에 최적화되어 있다. 개발자가 이미 익숙한 시각 언어를 활용하므로 학습 비용이 없다. 프로덕션 환경에서는 구조화된 로깅이나 LangSmith와 병행 사용하는 것이 권장된다.

---

## 10. 프로젝트 구조 및 실행 방법

### 10.1 전체 프로젝트 구조

```
supervisor-subagent/
├── src/
│   ├── __init__.py
│   ├── main.py                   # 엔트리포인트 + 그래프 빌드
│   ├── state.py                  # 공유 상태 정의 (State, WorkerState)
│   ├── agents/
│   │   ├── __init__.py           # 에이전트 import + registry export
│   │   ├── registry.py           # AgentRegistry + AgentEntry
│   │   ├── supervisor/
│   │   │   ├── __init__.py
│   │   │   └── supervisor.py     # Supervisor 노드 + 라우터
│   │   ├── math_agent/
│   │   │   ├── __init__.py
│   │   │   └── agent.py          # Math 서브그래프 (ReAct 패턴)
│   │   └── translate_agent/
│   │       ├── __init__.py
│   │       └── agent.py          # Translate 에이전트 (LLM 직접 호출)
│   └── logging/
│       ├── __init__.py
│       ├── config.py             # 로거 설정
│       ├── decorator.py          # @log_node 데코레이터
│       └── diff.py               # 상태 diff 포맷터
├── evals/
│   ├── __init__.py
│   ├── run.py                    # CLI 엔트리포인트
│   ├── runner.py                 # 테스트 실행 오케스트레이션
│   ├── judge.py                  # Judge LLM 호출 + 파싱
│   ├── prompts.py                # Judge 프롬프트 템플릿
│   └── types.py                  # TypedDict 정의
├── res/
│   └── test_cases.yaml           # 테스트 케이스 + 평가 설정
└── pyproject.toml                # 의존성 정의
```

### 10.2 실행 방법

```bash
# 환경 설정
cp .env.example .env    # OPENAI_API_KEY 설정

# 데모 실행
uv run python -m src.main

# 평가 실행
uv run python -m evals.run
uv run python -m evals.run --filter math          # Math Agent만
uv run python -m evals.run --agent translate       # Translate Agent만
```

---

## 11. 참고 자료

### 프레임워크 및 라이브러리 공식 문서

- [LangGraph 제품 페이지](https://www.langchain.com/langgraph) — 소개 및 주요 기능
- [LangGraph Graph API 공식 문서](https://docs.langchain.com/oss/python/langgraph/graph-api) — StateGraph, add_conditional_edges, 리듀서 등
- [LangGraph Workflows & Agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) — Supervisor 패턴 포함 멀티 에이전트 워크플로우 가이드
- [LangGraph Subgraph 공식 문서](https://docs.langchain.com/oss/python/langgraph/use-subgraphs) — 서브그래프 상태 전달, 겹치는 키 vs 분리 스키마
- [LangGraph `add_messages` 리듀서](https://reference.langchain.com/python/langgraph/graph/message) — 메시지 병합 리듀서 API 레퍼런스
- [LangGraph Supervisor 라이브러리 (GitHub)](https://github.com/langchain-ai/langgraph-supervisor-py) — `create_supervisor()`, handoff 도구 구현
- [LangGraph Supervisor API 레퍼런스](https://reference.langchain.com/python/langgraph-supervisor) — 함수/클래스 레퍼런스
- [LangGraph Supervisor 발표](https://changelog.langchain.com/announcements/langgraph-supervisor-a-library-for-hierarchical-multi-agent-systems) — 공식 블로그 발표
- [ChatOpenAI 통합 문서](https://docs.langchain.com/oss/python/integrations/chat/openai) — bind_tools(), with_structured_output() 등
- [ChatOpenAI API 레퍼런스](https://api.python.langchain.com/en/latest/openai/chat_models/langchain_openai.chat_models.base.ChatOpenAI.html) — 전체 API 문서
- [LangChain Tools 공식 문서](https://docs.langchain.com/oss/python/langchain/tools) — @tool 데코레이터, 커스텀 도구 생성
- [langchain-core Tools 레퍼런스](https://reference.langchain.com/python/langchain-core/tools) — langchain_core.tools 모듈
- [LangSmith Observability (LangGraph)](https://docs.langchain.com/oss/python/langgraph/observability) — LangGraph 트레이싱 설정
- [LangSmith 제품 페이지](https://www.langchain.com/langsmith/observability) — 관측성 플랫폼 소개

### 멀티 에이전트 프레임워크 비교

- [CrewAI vs LangGraph vs AutoGen (DataCamp)](https://www.datacamp.com/tutorial/crewai-vs-langgraph-vs-autogen) — 포괄적 프레임워크 비교 튜토리얼
- [Mastering Agents: LangGraph vs AutoGen vs CrewAI (Galileo AI)](https://galileo.ai/blog/mastering-agents-langgraph-vs-autogen-vs-crew) — 아키텍처 분석 비교
- [LangGraph vs AutoGen vs CrewAI: Complete Framework Comparison (Latenode)](https://latenode.com/blog/platform-comparisons-alternatives/automation-platform-comparisons/langgraph-vs-autogen-vs-crewai-complete-ai-agent-framework-comparison-architecture-analysis-2025) — 2025 기준 아키텍처 분석
- [A Detailed Comparison of Top AI Agent Frameworks (Turing)](https://www.turing.com/resources/ai-agent-frameworks) — 2026 기준 6대 프레임워크 비교
- [OpenAI Swarm (GitHub)](https://github.com/openai/swarm) — 교육용 경량 멀티 에이전트 프레임워크

### AutoGen → Microsoft Agent Framework 이관

- [AutoGen to Microsoft Agent Framework Migration Guide (Microsoft Learn)](https://learn.microsoft.com/en-us/agent-framework/migration-guide/from-autogen/) — 공식 마이그레이션 가이드
- [Microsoft Agent Framework Overview (Microsoft Learn)](https://learn.microsoft.com/en-us/agent-framework/overview/agent-framework-overview) — 프레임워크 개요
- [Microsoft Agent Framework (GitHub)](https://github.com/microsoft/agent-framework) — 소스 코드 저장소
- [Microsoft retires AutoGen and debuts Agent Framework (VentureBeat)](https://venturebeat.com/ai/microsoft-retires-autogen-and-debuts-agent-framework-to-unify-and-govern) — 발표 보도

### ReAct 패턴

- [Yao et al. (2022), "ReAct: Synergizing Reasoning and Acting in Language Models" (arXiv)](https://arxiv.org/abs/2210.03629) — 원논문
- [ReAct 논문 PDF](https://arxiv.org/pdf/2210.03629) — 전문 PDF
- [ReAct 공식 프로젝트 페이지](https://react-lm.github.io/) — 저자 운영 사이트
- [ReAct GitHub (ICLR 2023)](https://github.com/ysymyth/ReAct) — 재현 코드
- [Google Research Blog: ReAct](https://research.google/blog/react-synergizing-reasoning-and-acting-in-language-models/) — Google 리서치 블로그 해설

### LLM-as-Judge 평가

- [Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge (arXiv)](https://arxiv.org/abs/2406.07791) — 위치 편향 체계적 연구
- [ACL 2025 발표 논문 PDF](https://aclanthology.org/2025.ijcnlp-long.18.pdf) — 학회 발표 버전
- [Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge (arXiv)](https://arxiv.org/abs/2410.02736) — 12가지 편향 유형 분류 (CALM 프레임워크)
- [Self-Preference Bias in LLM-as-a-Judge (arXiv)](https://arxiv.org/abs/2410.21819) — 자기 강화 편향 연구
- [A Survey on LLM-as-a-Judge (arXiv)](https://arxiv.org/abs/2411.15594) — LLM-as-Judge 서베이 논문
- [Humans or LLMs as the Judge? A Study on Judgement Bias (arXiv)](https://arxiv.org/abs/2402.10669) — 인간 vs LLM 판단 편향 비교

### 레지스트리 및 플러그인 패턴

- [Python Packaging — Entry Points Specification](https://packaging.python.org/specifications/entry-points/) — 공식 사양
- [setuptools Entry Points User Guide](https://setuptools.pypa.io/en/latest/userguide/entry_point.html) — setuptools 공식 문서
