# Response Generator 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** supervisor가 FINISH 결정 시 페르소나가 적용된 최종 답변을 생성하는 response_generator 노드를 추가한다.

**Architecture:** response_generator는 파이프라인 노드로, supervisor_router에서 FINISH 판단 시 END 대신 라우팅된다. 전체 `state["messages"]`를 받아 페르소나 시스템 프롬프트와 함께 LLM에 전달하고, 최종 AIMessage를 반환한다.

**Tech Stack:** LangGraph, LangChain (ChatOpenAI), Python 3.13

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| `src/agents/response_generator/__init__.py` | 모듈 export |
| `src/agents/response_generator/prompt.py` | 페르소나 시스템 프롬프트 상수 |
| `src/agents/response_generator/generator.py` | response_generator_node 함수 |
| `tests/test_response_generator.py` | 단위 테스트 |
| `src/agents/supervisor/supervisor.py` (수정) | supervisor_router에서 FINISH → "response_generator" |
| `src/main.py` (수정) | 그래프에 노드/엣지 추가 |

---

### Task 1: response_generator 프롬프트 모듈

**Files:**
- Create: `src/agents/response_generator/prompt.py`
- Test: `tests/test_response_generator.py`

- [ ] **Step 1: 테스트 작성 — 프롬프트 상수 존재 확인**

```python
# tests/test_response_generator.py
"""response_generator 단위 테스트.

LLM 호출 없이 프롬프트 구성과 노드 로직을 검증한다.
"""

from __future__ import annotations

from src.agents.response_generator.prompt import RESPONSE_GENERATOR_SYSTEM_PROMPT


class TestPrompt:
    def test_prompt_is_nonempty_string(self) -> None:
        assert isinstance(RESPONSE_GENERATOR_SYSTEM_PROMPT, str)
        assert len(RESPONSE_GENERATOR_SYSTEM_PROMPT) > 0

    def test_prompt_instructs_to_ignore_json(self) -> None:
        assert "JSON" in RESPONSE_GENERATOR_SYSTEM_PROMPT
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `uv run pytest tests/test_response_generator.py::TestPrompt -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 프롬프트 모듈 구현**

```python
# src/agents/response_generator/prompt.py
"""최종 답변 생성기의 페르소나 프롬프트 정의."""

RESPONSE_GENERATOR_SYSTEM_PROMPT = """당신은 사용자에게 최종 답변을 전달하는 어시스턴트입니다.

## 역할
대화 기록에서 사용자의 질문과 워커 에이전트의 실행 결과를 참고하여,
사용자에게 전달할 최종 답변을 생성하세요.

## 규칙
1. JSON 형식의 내부 판단 메시지(next, reason, plan 필드를 포함하는 메시지)는 시스템 내부 라우팅 기록이므로 무시하세요.
2. 워커 에이전트의 결과를 자연스러운 문장으로 재구성하세요.
3. 사용자의 질문 톤에 맞춰 답변하세요 (예: "알려줘" → 친근, "보고해주세요" → 격식).
4. 여러 워커의 결과가 있으면 논리적 순서로 종합하세요.
5. 워커 결과의 핵심 정보를 빠뜨리지 마세요.

## 출력 형식
최종 답변만 출력하세요. 내부 처리 과정이나 워커 이름을 언급하지 마세요."""
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `uv run pytest tests/test_response_generator.py::TestPrompt -v`
Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add src/agents/response_generator/prompt.py tests/test_response_generator.py
git commit -m "feat(response_generator): add persona system prompt"
```

---

### Task 2: response_generator 노드 구현

**Files:**
- Create: `src/agents/response_generator/generator.py`
- Create: `src/agents/response_generator/__init__.py`
- Modify: `tests/test_response_generator.py`

- [ ] **Step 1: 테스트 작성 — 노드 동작 검증**

`tests/test_response_generator.py`에 추가:

```python
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.response_generator.generator import response_generator_node


class TestResponseGeneratorNode:
    @patch("src.agents.response_generator.generator.get_chat_model")
    def test_returns_ai_message(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="연봉 5천만원 이상 직원은 3명입니다.")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="연봉이 5천만원 이상인 직원은 몇 명인가요?"),
                AIMessage(content='{"next": "sql", "reason": "SQL 조회 필요", "plan": "sql 실행"}'),
                AIMessage(content="[SQL 결과]\n| count |\n|-------|\n| 3 |"),
                AIMessage(content='{"next": "FINISH", "reason": "완료", "plan": "완료"}'),
            ],
            "next_agent": "FINISH",
            "plan": "완료",
            "completed_agents": ["sql"],
        }

        result = response_generator_node(state)
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert "3명" in result["messages"][0].content

    @patch("src.agents.response_generator.generator.get_chat_model")
    def test_passes_system_prompt_and_messages(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="답변")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="질문"),
                AIMessage(content="결과"),
            ],
            "next_agent": "FINISH",
            "plan": "",
            "completed_agents": [],
        }

        response_generator_node(state)

        call_args = mock_llm.invoke.call_args[0][0]
        # 시스템 프롬프트 1개 + 대화 메시지 2개 = 총 3개
        assert len(call_args) == 3

    @patch("src.agents.response_generator.generator.get_chat_model")
    def test_handles_multi_agent_results(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content="123 곱하기 456은 56,088입니다. In English: 56,088.",
        )
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="123 곱하기 456을 계산하고 영어로 설명해줘"),
                AIMessage(content='{"next": "math", "reason": "계산", "plan": "math → translate"}'),
                AIMessage(content="[수학 계산 결과]\n56088"),
                AIMessage(content='{"next": "translate", "reason": "번역", "plan": "translate"}'),
                AIMessage(content="[번역 결과]\n56,088"),
                AIMessage(content='{"next": "FINISH", "reason": "완료", "plan": "완료"}'),
            ],
            "next_agent": "FINISH",
            "plan": "완료",
            "completed_agents": ["math", "translate"],
        }

        result = response_generator_node(state)
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `uv run pytest tests/test_response_generator.py::TestResponseGeneratorNode -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: generator.py 구현**

```python
# src/agents/response_generator/generator.py
"""최종 답변 생성 노드: 페르소나를 적용하여 사용자에게 전달할 답변을 생성한다."""

from langchain_core.messages import AIMessage, SystemMessage

from src.agents.response_generator.prompt import RESPONSE_GENERATOR_SYSTEM_PROMPT
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.state import State

logger = get_logger("response_generator")


@log_node("response_generator")
def response_generator_node(state: State) -> dict:
    """서브에이전트 결과를 종합하여 페르소나가 적용된 최종 답변을 생성한다."""
    llm = get_chat_model()

    messages = [
        SystemMessage(content=RESPONSE_GENERATOR_SYSTEM_PROMPT),
    ] + list(state["messages"])

    logger.info("최종 답변 생성 LLM 호출 시작")
    response = llm.invoke(messages)

    content: str = response.content  # type: ignore[assignment]
    logger.info("최종 답변: %s", content)

    return {"messages": [AIMessage(content=content)]}
```

- [ ] **Step 4: __init__.py 작성**

```python
# src/agents/response_generator/__init__.py
from src.agents.response_generator.generator import response_generator_node

__all__ = ["response_generator_node"]
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `uv run pytest tests/test_response_generator.py -v`
Expected: 5 passed (TestPrompt 2개 + TestResponseGeneratorNode 3개)

- [ ] **Step 6: 커밋**

```bash
git add src/agents/response_generator/__init__.py src/agents/response_generator/generator.py tests/test_response_generator.py
git commit -m "feat(response_generator): add response generator node with persona prompt"
```

---

### Task 3: supervisor_router 수정 — FINISH → response_generator

**Files:**
- Modify: `src/agents/supervisor/supervisor.py:118-135`
- Modify: `tests/test_response_generator.py`

- [ ] **Step 1: 테스트 작성 — 라우터 변경 검증**

`tests/test_response_generator.py`에 추가:

```python
from src.agents.supervisor.supervisor import supervisor_router


class TestSupervisorRouterChange:
    def test_finish_routes_to_response_generator(self) -> None:
        state = {
            "messages": [],
            "next_agent": "FINISH",
            "plan": "",
            "completed_agents": [],
        }
        result = supervisor_router(state)
        assert result == "response_generator"

    def test_max_iterations_routes_to_response_generator(self) -> None:
        state = {
            "messages": [],
            "next_agent": "math",
            "plan": "",
            "completed_agents": ["a", "b", "c", "d", "e"],
        }
        result = supervisor_router(state)
        assert result == "response_generator"

    def test_agent_routes_normally(self) -> None:
        import src.agents  # noqa: F401
        state = {
            "messages": [],
            "next_agent": "math",
            "plan": "",
            "completed_agents": [],
        }
        result = supervisor_router(state)
        assert result == "math_agent"
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `uv run pytest tests/test_response_generator.py::TestSupervisorRouterChange -v`
Expected: FAIL — `test_finish_routes_to_response_generator`와 `test_max_iterations_routes_to_response_generator`가 `END`를 반환

- [ ] **Step 3: supervisor_router 수정**

`src/agents/supervisor/supervisor.py`에서 `supervisor_router` 함수를 수정한다:

```python
RESPONSE_GENERATOR_NODE = "response_generator"


def supervisor_router(state: State) -> str:
    """슈퍼바이저의 결정에 따라 다음 노드를 라우팅한다."""
    next_agent = state.get("next_agent", "FINISH")

    completed = state.get("completed_agents", [])
    if len(completed) >= MAX_ITERATIONS:
        router_logger.warning(
            "최대 반복 횟수(%d) 도달 → response_generator", MAX_ITERATIONS,
        )
        return RESPONSE_GENERATOR_NODE

    entry = registry.get(next_agent)
    if entry is not None:
        router_logger.info("라우팅: → %s", entry.node_name)
        return entry.node_name

    router_logger.info("라우팅: → response_generator (FINISH)")
    return RESPONSE_GENERATOR_NODE
```

변경 사항:
- `END` 반환 2곳을 모두 `RESPONSE_GENERATOR_NODE`(`"response_generator"`)로 변경
- `from langgraph.graph import END` import는 더 이상 사용되지 않으므로 제거

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `uv run pytest tests/test_response_generator.py -v`
Expected: 8 passed (전체)

- [ ] **Step 5: 기존 테스트 깨지지 않는지 확인**

Run: `uv run pytest tests/ -v`
Expected: 전체 통과

- [ ] **Step 6: 커밋**

```bash
git add src/agents/supervisor/supervisor.py tests/test_response_generator.py
git commit -m "refactor(supervisor): route FINISH to response_generator instead of END"
```

---

### Task 4: main.py 그래프 연결 수정

**Files:**
- Modify: `src/main.py:34-55`

- [ ] **Step 1: main.py 수정 — response_generator 노드 및 엣지 추가**

```python
# src/main.py 상단 import 추가
from src.agents.response_generator import response_generator_node

# build_graph() 수정
def build_graph():
    """Supervisor-Subagent 메인 그래프를 빌드한다."""
    graph = StateGraph(State)

    graph.add_node("query_rewriter", query_rewriter_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("response_generator", response_generator_node)

    node_names: list[str] = []
    for entry in registry.entries:
        graph.add_node(entry.node_name, entry.wrapper)
        graph.add_edge(entry.node_name, "supervisor")
        node_names.append(entry.node_name)

    graph.add_edge(START, "query_rewriter")
    graph.add_edge("query_rewriter", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        supervisor_router,
        [*node_names, "response_generator"],
    )
    graph.add_edge("response_generator", END)

    return graph.compile()
```

변경 사항:
- `response_generator_node` import 추가
- `graph.add_node("response_generator", ...)` 추가
- `add_conditional_edges`에서 `END`를 `"response_generator"`로 변경
- `graph.add_edge("response_generator", END)` 추가

- [ ] **Step 2: 모듈 docstring 흐름도 업데이트**

```python
"""
실행 흐름:
    [START] → [query_rewriter] → [supervisor] → (라우터) → [math_agent]      → [supervisor] → ...
                                                         → [translate_agent] → [supervisor]
                                                         → [response_generator] → END (FINISH)
"""
```

- [ ] **Step 3: 그래프 빌드 검증**

Run: `uv run python -c "from src.main import build_graph; g = build_graph(); print('Nodes:', list(g.get_graph().nodes))"`
Expected: `Nodes: ['__start__', 'query_rewriter', 'supervisor', 'response_generator', 'math_agent', 'sql_agent', 'translate_agent', '__end__']`

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `uv run pytest tests/ -v`
Expected: 전체 통과

- [ ] **Step 5: 커밋**

```bash
git add src/main.py
git commit -m "feat(main): wire response_generator node into graph pipeline"
```
