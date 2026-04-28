# Query Rewriter Curated chat_history Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** query_rewriter가 LangGraph 체크포인터로 복원된 `state["messages"]`가 아니라, 호출자가 명시적으로 넘기는 큐레이션된 `chat_history` 필드를 컨텍스트로 사용하도록 전환한다.

**Architecture:** `State`에 `chat_history: list[BaseMessage]` 필드를 `operator.add` 리듀서로 추가한다. `query_rewriter_node`는 `state["messages"]` 대신 이 필드를 LLM 입력에 끼워 넣고 현재 턴 질의는 단독 `HumanMessage`로 전달한다. `response_generator_node`는 턴 종료 시 마지막 `HumanMessage`(리라이팅된 질의)와 자신이 만든 `AIMessage`(최종 출력) 2개를 `chat_history`에 append한다.

**Tech Stack:** Python 3.13, LangGraph, LangChain Core, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-04-28-query-rewriter-curated-chat-history-design.md`

---

## File Structure

**Modified files:**
- `src/state.py` — `chat_history` 필드 추가.
- `src/query_rewriter/rewriter.py` — `state["messages"]` 의존 제거, `chat_history` + 현재 질의로 LLM 호출.
- `src/query_rewriter/prompt.py` — "대화 맥락 보충" 섹션 문구 다듬어 chat_history 명시.
- `src/response_generator/generator.py` — 반환 dict에 `chat_history` 키 포함.
- `src/main.py` — 멀티턴 데모 시나리오 E 추가.
- `tests/test_query_rewriter.py` — chat_history 기반 LLM 호출 검증 케이스 교체/추가.
- `tests/test_response_generator.py` — chat_history append 검증 케이스 추가.

**Created files:** none.

---

## Task 1: State에 chat_history 필드 추가

**Files:**
- Modify: `src/state.py`

- [ ] **Step 1: `src/state.py` 변경 — chat_history 필드 추가**

`src/state.py` 전체를 다음 내용으로 교체:

```python
import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class State(TypedDict):
    """Router-Subagent 시스템의 공유 상태.

    Attributes:
        messages: 단일 invocation 내의 메시지 흐름 (add_messages 리듀서로 자동 병합)
        next_agent: 라우터가 결정한 다음 워커 (registry 이름 또는 "FINISH")
        chat_history: 호출자가 큐레이션한 과거 대화. 한 턴 종료 시
            (리라이팅된 사용자 질의 HumanMessage, 최종 출력 AIMessage) 2개가
            operator.add 리듀서로 누적된다.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    next_agent: str
    chat_history: Annotated[list[BaseMessage], operator.add]


class WorkerState(TypedDict):
    """워커 서브그래프의 내부 상태."""

    messages: Annotated[list[BaseMessage], add_messages]
```

- [ ] **Step 2: 기존 테스트가 깨지지 않는지 확인**

Run: `uv run pytest tests/ -v`
Expected: 모든 기존 테스트 PASS (TypedDict는 추가 필드를 강제하지 않으므로 기존 dict 리터럴은 그대로 동작).

- [ ] **Step 3: 그래프 빌드 smoke 확인**

Run: `uv run python -c "from src.main import build_graph; build_graph(); print('OK')"`
Expected: `OK` 출력. operator.add 리듀서가 LangGraph에서 정상 인식되는지 확인.

- [ ] **Step 4: Commit**

```bash
git add src/state.py
git commit -m "feat(state): add chat_history field with concat reducer"
```

---

## Task 2: query_rewriter — chat_history를 컨텍스트로 사용

**Files:**
- Modify: `src/query_rewriter/rewriter.py`
- Test: `tests/test_query_rewriter.py`

- [ ] **Step 1: 실패 테스트 작성 — 빈 chat_history**

`tests/test_query_rewriter.py`의 `TestQueryRewriterNode` 클래스 내부, `test_passes_full_conversation_to_llm` 메서드(파일 마지막 메서드, 라인 122–143)를 다음 두 메서드로 교체:

```python
    @patch("src.query_rewriter.rewriter.get_chat_model")
    def test_passes_empty_chat_history_to_llm(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="리라이팅 결과")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [HumanMessage(content="현재 질의")],
            "next_agent": "",
            "chat_history": [],
        }

        query_rewriter_node(state)

        call_args = mock_llm.invoke.call_args[0][0]
        # SystemMessage + 현재 HumanMessage = 2개
        assert len(call_args) == 2
        assert call_args[1].content == "현재 질의"

    @patch("src.query_rewriter.rewriter.get_chat_model")
    def test_passes_nonempty_chat_history_to_llm(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="리라이팅 결과")
        mock_get_model.return_value = mock_llm

        chat_history = [
            HumanMessage(content="과거 질의"),
            AIMessage(content="과거 출력"),
        ]
        state = {
            "messages": [HumanMessage(content="현재 질의")],
            "next_agent": "",
            "chat_history": chat_history,
        }

        query_rewriter_node(state)

        call_args = mock_llm.invoke.call_args[0][0]
        # SystemMessage + chat_history 2개 + 현재 HumanMessage = 4개
        assert len(call_args) == 4
        assert call_args[1].content == "과거 질의"
        assert call_args[2].content == "과거 출력"
        assert call_args[3].content == "현재 질의"
```

또한 같은 클래스 내 기존 `test_returns_rewritten_message`, `test_skips_when_no_change`, `test_skips_when_no_human_message` 세 메서드의 state dict에서 `"plan": "", "completed_agents": []` 를 `"chat_history": []` 로 교체 (의미 없는 잔재 키 제거 + 신규 키 명시).

`test_returns_rewritten_message` 의 state:
```python
        state = {
            "messages": [HumanMessage(content="지난주 매출 알려줘")],
            "next_agent": "",
            "chat_history": [],
        }
```

`test_skips_when_no_change` 의 state:
```python
        state = {
            "messages": [HumanMessage(content=original)],
            "next_agent": "",
            "chat_history": [],
        }
```

`test_skips_when_no_human_message` 의 state:
```python
        state = {
            "messages": [AIMessage(content="ai only")],
            "next_agent": "",
            "chat_history": [],
        }
```

- [ ] **Step 2: 새 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_query_rewriter.py::TestQueryRewriterNode -v`
Expected: `test_passes_empty_chat_history_to_llm`과 `test_passes_nonempty_chat_history_to_llm`이 FAIL (현재 구현은 `state["messages"]` 전체를 넘기므로 메시지 개수 assert 실패).

- [ ] **Step 3: rewriter.py 변경 — chat_history 사용**

`src/query_rewriter/rewriter.py`의 `query_rewriter_node` 함수 본문에서 LLM 호출 부분을 변경. 구체적으로 라인 56–60의 LLM 호출 블록을 다음으로 교체:

기존 (라인 56–60):
```python
    system_prompt = build_rewriter_system_prompt(now=datetime.now(), dictionary=dictionary)
    llm = get_chat_model()

    response = llm.invoke(
        [SystemMessage(content=system_prompt)] + list(state["messages"]),
    )
```

변경 후:
```python
    system_prompt = build_rewriter_system_prompt(now=datetime.now(), dictionary=dictionary)
    llm = get_chat_model()

    chat_history = state.get("chat_history", [])
    response = llm.invoke(
        [SystemMessage(content=system_prompt)]
        + list(chat_history)
        + [HumanMessage(content=original)],
    )
```

- [ ] **Step 4: 모든 query_rewriter 테스트가 통과하는지 확인**

Run: `uv run pytest tests/test_query_rewriter.py -v`
Expected: 전체 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/query_rewriter/rewriter.py tests/test_query_rewriter.py
git commit -m "feat(query_rewriter): use curated chat_history instead of state messages"
```

---

## Task 3: query_rewriter prompt에 chat_history 명시

**Files:**
- Modify: `src/query_rewriter/prompt.py`

- [ ] **Step 1: prompt.py의 "대화 맥락 보충" 섹션 문구 다듬기**

`src/query_rewriter/prompt.py`의 `REWRITER_SYSTEM_PROMPT` 상수, "### 2. 대화 맥락 보충" 섹션의 첫 문장을 변경. 구체적으로 라인 50–55를 다음으로 교체:

기존:
```
### 2. 대화 맥락 보충
이전 대화 내용을 참고하여 모호한 지시어를 구체적으로 바꿔주세요:
```

변경 후:
```
### 2. 대화 맥락 보충
이전 턴들의 대화(시스템 메시지 다음에 주어지는 사용자/어시스턴트 메시지 쌍)는 큐레이션된 과거 대화입니다. 이를 참고하여 현재 사용자 메시지의 모호한 지시어를 구체적으로 바꿔주세요:
```

(나머지 글머리 항목 4개와 다른 섹션은 그대로 둘 것.)

- [ ] **Step 2: 기존 prompt 테스트가 통과하는지 확인**

Run: `uv run pytest tests/test_query_rewriter.py::TestPrompt -v`
Expected: 전체 PASS (기존 assert는 형식만 검증하므로 영향 없음).

- [ ] **Step 3: Commit**

```bash
git add src/query_rewriter/prompt.py
git commit -m "docs(query_rewriter): clarify prompt that history is curated"
```

---

## Task 4: response_generator — chat_history에 한 턴 append

**Files:**
- Modify: `src/response_generator/generator.py`
- Test: `tests/test_response_generator.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_response_generator.py`의 `TestResponseGeneratorNode` 클래스 끝(라인 97 이후, `from src.supervisor.supervisor import ...` 위)에 다음 4개 메서드 추가:

```python
    @patch("src.response_generator.generator.get_chat_model")
    def test_returns_chat_history_with_two_messages(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="최종 출력")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="리라이팅된 질의"),
                AIMessage(content="에이전트 결과"),
            ],
            "next_agent": "FINISH",
            "chat_history": [],
        }

        result = response_generator_node(state)
        assert "chat_history" in result
        assert len(result["chat_history"]) == 2

    @patch("src.response_generator.generator.get_chat_model")
    def test_chat_history_first_is_last_human_message(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="최종 출력")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="원본 질의"),
                HumanMessage(content="리라이팅된 질의"),
                AIMessage(content="에이전트 결과"),
            ],
            "next_agent": "FINISH",
            "chat_history": [],
        }

        result = response_generator_node(state)
        first = result["chat_history"][0]
        assert isinstance(first, HumanMessage)
        assert first.content == "리라이팅된 질의"

    @patch("src.response_generator.generator.get_chat_model")
    def test_chat_history_second_is_generated_ai_message(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="최종 출력")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [
                HumanMessage(content="질의"),
                AIMessage(content="에이전트 결과"),
            ],
            "next_agent": "FINISH",
            "chat_history": [],
        }

        result = response_generator_node(state)
        second = result["chat_history"][1]
        assert isinstance(second, AIMessage)
        assert second.content == "최종 출력"

    @patch("src.response_generator.generator.get_chat_model")
    def test_omits_chat_history_when_no_human_message(self, mock_get_model: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="최종 출력")
        mock_get_model.return_value = mock_llm

        state = {
            "messages": [AIMessage(content="ai only")],
            "next_agent": "FINISH",
            "chat_history": [],
        }

        result = response_generator_node(state)
        assert "chat_history" not in result
        assert "messages" in result
```

- [ ] **Step 2: 새 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_response_generator.py::TestResponseGeneratorNode -v`
Expected: 새로 추가한 4개 메서드가 FAIL (현재 generator는 `chat_history` 키를 반환하지 않음).

- [ ] **Step 3: generator.py 변경 — chat_history 반환**

`src/response_generator/generator.py` 전체를 다음 내용으로 교체:

```python
"""최종 답변 생성 노드: 페르소나를 적용하여 사용자에게 전달할 답변을 생성한다."""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src.response_generator.prompt import RESPONSE_GENERATOR_SYSTEM_PROMPT
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.state import State

logger = get_logger("response_generator")


def _find_last_human_message(messages: list[BaseMessage]) -> HumanMessage | None:
    """메시지 리스트에서 마지막 HumanMessage를 찾는다."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg
    return None


@log_node("response_generator")
def response_generator_node(state: State) -> dict:
    """서브에이전트 결과를 종합하여 페르소나가 적용된 최종 답변을 생성하고
    chat_history에 한 턴분(리라이팅된 사용자 질의 + 최종 출력)을 append한다.
    """
    llm = get_chat_model()

    messages = [
        SystemMessage(content=RESPONSE_GENERATOR_SYSTEM_PROMPT),
    ] + list(state["messages"])

    logger.info("최종 답변 생성 LLM 호출 시작")
    response = llm.invoke(messages)

    content: str = response.content  # type: ignore[assignment]
    logger.info("최종 답변: %s", content)

    final_ai = AIMessage(content=content)
    update: dict = {"messages": [final_ai]}

    last_human = _find_last_human_message(state["messages"])
    if last_human is not None:
        update["chat_history"] = [
            HumanMessage(content=last_human.content),
            final_ai,
        ]

    return update
```

- [ ] **Step 4: 모든 response_generator 테스트가 통과하는지 확인**

Run: `uv run pytest tests/test_response_generator.py -v`
Expected: 전체 PASS (기존 5개 + 신규 4개 + Supervisor 라우터 잔재 3개).

- [ ] **Step 5: Commit**

```bash
git add src/response_generator/generator.py tests/test_response_generator.py
git commit -m "feat(response_generator): append turn to chat_history on completion"
```

---

## Task 5: main.py에 멀티턴 데모 시나리오 추가

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: 멀티턴 시나리오 함수 추가**

`src/main.py`의 `run_scenario` 함수 바로 아래에 멀티턴 헬퍼 함수를 추가. 즉 라인 81 다음, `def main():` 바로 위에 다음 함수를 삽입:

```python
def run_multiturn_scenario(
    app,
    name: str,
    description: str,
    first_message: str,
    second_message: str,
) -> None:
    """1차 invoke의 chat_history를 2차 invoke에 인계하는 멀티턴 시나리오."""
    logger.info("시나리오 %s: %s", name, description)
    logger.info("1차 입력: %s", first_message)

    first_result = app.invoke({
        "messages": [HumanMessage(content=first_message)],
        "next_agent": "",
        "chat_history": [],
    })

    chat_history = first_result.get("chat_history", [])
    logger.info("1차 종료 후 chat_history 길이: %d", len(chat_history))

    logger.info("2차 입력: %s", second_message)
    second_result = app.invoke({
        "messages": [HumanMessage(content=second_message)],
        "next_agent": "",
        "chat_history": chat_history,
    })

    logger.info(
        "\n%s\n"
        "  [SCENARIO %s] Finished\n"
        "%s\n"
        "  Final State (turn 2):\n%s\n"
        "%s",
        "=" * 60, name, "=" * 60,
        format_state_pretty(second_result),
        "=" * 60,
    )
```

- [ ] **Step 2: `main()` 함수에 시나리오 E 호출 추가**

`src/main.py`의 `main()` 함수, 시나리오 D 호출 바로 다음(라인 108 직후, `if __name__ == "__main__":` 위)에 다음을 추가:

```python
    run_multiturn_scenario(
        app, "E", "멀티턴 — 1차 결과를 chat_history로 인계해 2차 맥락 보충",
        "Hello, how are you?를 한국어로 번역해주세요",
        "이거 다시 영어로 번역해주세요",
    )
```

- [ ] **Step 3: 데모 실행 (수동 확인)**

Run: `uv run python -m src.main 2>&1 | tail -80`
Expected: 시나리오 E 로그에서 "1차 종료 후 chat_history 길이: 2"가 출력되고, 2차 invoke에서 query_rewriter가 "이거"를 1차 출력 컨텍스트로 풀어 리라이팅하는 흔적이 보임. (LLM이므로 정확 문구는 재현 불가; 핵심은 길이 2와 정상 종료.)

- [ ] **Step 4: 단위 테스트 회귀 확인**

Run: `uv run pytest tests/ -v`
Expected: 전체 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/main.py
git commit -m "feat(main): add multiturn demo handing chat_history across invokes"
```

---

## Verification

모든 태스크 완료 후 한 번 더 회귀 확인:

- [ ] `uv run pytest tests/ -v` — 전체 PASS
- [ ] `uv run python -m src.main` — 시나리오 A~E 모두 정상 종료, E의 chat_history 길이 2 확인
- [ ] `git log --oneline -10` — 5개의 의미 있는 커밋이 순차적으로 들어가 있는지 확인
