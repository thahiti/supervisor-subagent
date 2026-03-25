# Agent Registry

## 해결하는 문제

멀티 에이전트 시스템에서 새 에이전트를 추가할 때 일반적으로 다음 세 곳을 수정해야 한다:

1. 그래프 빌드 코드에 노드와 엣지 추가
2. Supervisor 시스템 프롬프트에 새 에이전트 설명 추가
3. 라우터 함수에 if-elif 분기 추가

이 분산된 수정은 누락 위험이 높고, 에이전트 수가 늘어날수록 관리 비용이 선형으로 증가한다. Agent Registry는 이 세 가지 관심사를 하나의 등록 지점으로 통합하여 **에이전트 추가를 단일 데코레이터 한 줄로** 완료할 수 있게 한다.

## 핵심 컴포넌트

### AgentEntry

```python
@dataclass
class AgentEntry:
    name: str                           # 라우팅 키 ("math", "translate")
    node_name: str                      # 그래프 노드 이름 ("math_agent")
    wrapper: Callable[[State], dict]    # 실행할 wrapper 함수
    description: str                    # Supervisor 프롬프트에 삽입될 설명
```

하나의 에이전트에 대한 모든 메타데이터를 담는 불변 데이터 구조다. `name`은 Supervisor가 JSON으로 선택하는 라우팅 키이고, `node_name`은 LangGraph 그래프 내부의 노드 식별자이다. 이 두 값을 분리한 이유는 Supervisor에게는 짧고 직관적인 이름(`"math"`)을, 그래프에는 역할이 명확한 이름(`"math_agent"`)을 사용하기 위함이다.

### AgentRegistry

```python
class AgentRegistry:
    _entries: list[AgentEntry]          # 등록 순서 보존
    _by_name: dict[str, AgentEntry]     # O(1) 이름 조회
```

두 가지 내부 저장소를 유지한다:
- `_entries` — 등록 순서를 보존하는 리스트. 그래프 빌드와 프롬프트 생성 시 순회에 사용
- `_by_name` — 이름 기반 O(1) 조회용 딕셔너리. 라우터에서 사용

## API 상세

### `register(name, wrapper, *, node_name, description)`

명시적 등록 메서드. 내부적으로 `@registry.agent` 데코레이터가 이 메서드를 호출한다.

**description 결정 순서:**
1. `description` 파라미터가 직접 전달되면 사용
2. 미전달 시 `wrapper.__doc__` (docstring) 추출
3. 둘 다 없으면 `ValueError` 발생

description을 필수로 강제하는 이유: Supervisor의 시스템 프롬프트에 각 에이전트의 설명이 포함되어야 LLM이 올바른 라우팅 결정을 내릴 수 있다. description 없는 에이전트는 Supervisor가 언제 호출해야 하는지 판단할 수 없으므로 등록 자체를 거부한다.

**node_name 자동 생성:**

미지정 시 `f"{name}_agent"` 형태로 생성된다. 예를 들어 `name="math"`이면 `node_name="math_agent"`. 이 컨벤션으로 에이전트 이름만 결정하면 노드 이름은 자동으로 일관성 있게 생성된다.

### `@registry.agent(name, *, node_name, description)`

데코레이터 방식의 등록. wrapper 함수 정의 시점에 자동으로 레지스트리에 등록된다.

```python
@registry.agent("math")
def math_wrapper(state: State) -> dict:
    """수학 계산을 수행합니다. 덧셈, 곱셈, 나눗셈 등의 계산이 필요할 때 사용합니다."""
    ...
```

데코레이터는 원본 함수를 그대로 반환한다 (`return func`). 함수를 감싸거나 동작을 변경하지 않으므로, 데코레이터 적용 후에도 함수를 직접 호출할 수 있다. 이는 평가 시스템(`evals/runner.py`)에서 `entry.wrapper(state)`로 wrapper를 직접 호출하는 것을 가능하게 한다.

### `entries` / `agent_names`

```python
registry.entries      # → [AgentEntry("math", ...), AgentEntry("translate", ...)]
registry.agent_names  # → ["math", "translate"]
```

`entries`는 방어적 복사(`list(self._entries)`)를 반환하여 외부에서 내부 리스트를 변경할 수 없게 한다.

### `get(name)`

```python
entry = registry.get("math")    # → AgentEntry or None
```

`_by_name` 딕셔너리를 사용하므로 O(1) 조회. 라우터에서 매 라우팅 결정마다 호출되므로 성능이 중요하다.

### `build_workers_prompt()`

```python
registry.build_workers_prompt()
# → "- **math**: 수학 계산을 수행합니다. ...\n- **translate**: 텍스트를 번역합니다. ..."
```

등록된 모든 에이전트의 이름과 description을 Markdown 리스트로 포맷한다. 이 문자열은 Supervisor의 시스템 프롬프트에 `{workers}` 플레이스홀더로 삽입된다.

에이전트를 추가하면 이 메서드의 출력이 자동으로 확장되므로, Supervisor 프롬프트를 수동으로 수정할 필요가 없다.

## 프로젝트 내 통합 지점

레지스트리는 프로젝트의 세 가지 핵심 컴포넌트에서 사용된다:

### 1. 그래프 빌드 (`src/main.py`)

```python
for entry in registry.entries:
    graph.add_node(entry.node_name, entry.wrapper)
    graph.add_edge(entry.node_name, "supervisor")
    node_names.append(entry.node_name)

graph.add_conditional_edges("supervisor", supervisor_router, [*node_names, END])
```

레지스트리를 순회하며 노드 등록, 엣지 연결, conditional edges 구성을 자동으로 수행한다. 새 에이전트가 등록되면 이 코드 수정 없이 그래프에 포함된다.

### 2. Supervisor 라우팅 (`src/agents/supervisor/supervisor.py`)

**프롬프트 생성:**
```python
def _build_system_prompt(plan, completed_agents):
    choices = '" 또는 "'.join(registry.agent_names + ["FINISH"])
    return SUPERVISOR_SYSTEM_PROMPT.format(
        workers=registry.build_workers_prompt(),
        agent_choices=choices,
        ...
    )
```

`registry.agent_names`로 선택지 목록을, `registry.build_workers_prompt()`로 에이전트 설명을 동적으로 생성한다.

**라우터 분기:**
```python
def supervisor_router(state):
    entry = registry.get(next_agent)
    if entry is not None:
        return entry.node_name
    return END
```

`registry.get()`으로 에이전트를 조회하여 해당 노드 이름을 반환한다. if-elif 체인이 없으므로 에이전트 수에 관계없이 코드가 동일하다.

### 3. 평가 시스템 (`evals/runner.py`)

```python
def _invoke_agent(target_agent, input_text, state_overrides):
    entry = registry.get(target_agent)
    result = entry.wrapper(state)
    return result["messages"][-1].content
```

평가 시 레지스트리에서 wrapper를 조회하여 직접 호출한다. 이로써 평가 코드가 특정 에이전트 구현에 의존하지 않는다.

## 등록 트리거 메커니즘

`@registry.agent` 데코레이터는 모듈 import 시점에 실행된다. 따라서 에이전트 모듈이 import되어야 등록이 완료된다.

```python
# src/agents/__init__.py
from src.agents.math_agent import math_wrapper      # → @registry.agent("math") 실행
from src.agents.translate_agent import translate_wrapper  # → @registry.agent("translate") 실행
```

`src/agents/__init__.py`에서 각 에이전트 모듈을 import하면 데코레이터가 자동 실행되어 레지스트리에 등록된다. 새 에이전트를 추가할 때 이 파일에 import를 한 줄 추가하면 된다.

## 글로벌 인스턴스

```python
# src/agents/registry.py 하단
registry = AgentRegistry()
```

모듈 레벨에서 단일 인스턴스를 생성한다. Python 모듈은 한 번만 로드되므로 이 인스턴스는 프로세스 내에서 싱글턴으로 동작한다. 별도의 싱글턴 패턴이나 DI 컨테이너 없이 모듈 시스템 자체의 특성을 활용한 설계다.

## 새 에이전트 추가 체크리스트

1. `src/agents/new_agent/agent.py` 생성
2. wrapper 함수에 `@registry.agent("name")` 적용 + docstring 작성
3. `src/agents/__init__.py`에 `from src.agents.new_agent import new_wrapper` 추가

수정이 필요 **없는** 파일:
- `src/main.py` (그래프 빌드)
- `src/agents/supervisor/supervisor.py` (프롬프트, 라우터)
- `evals/` (평가 시스템)
