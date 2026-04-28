# Query Rewriter — Curated chat_history 도입

## 배경 / 목적

현재 `query_rewriter_node`는 `state["messages"]` 전체를 LLM에 그대로 넘겨 맥락 보충(예: "이거 다시 해줘")을 수행한다. 운영 환경에서는 LangGraph 체크포인터가 `state["messages"]`를 자동 복원하므로, 리라이터가 보는 "과거 대화"는 사실상 체크포인트에 의존한다.

본 작업의 목표는 **리라이터가 참조하는 과거 대화를, 체크포인터가 아니라 호출자가 직접 큐레이션해서 명시적으로 넘기는 별도 필드**로 전환하는 것이다. 한 턴이 끝날 때마다 시스템이 "리라이팅된 사용자 질의"와 "에이전트 최종 출력"을 자동으로 누적하여, 다음 invoke 시 호출자가 그대로 전달할 수 있게 한다.

## 범위

### In scope
- `State`에 `chat_history` 필드 신설 (`list[BaseMessage]` + concat 리듀서).
- `query_rewriter_node`가 `state["messages"]` 대신 `chat_history`를 컨텍스트로 사용하도록 변경.
- `response_generator_node`가 턴 종료 시 `chat_history`에 2개 메시지(리라이팅된 사용자 질의 + 최종 출력) append.
- 단위 테스트 갱신 / 신규.
- `main.py`에 멀티턴 시나리오 1개 추가하여 동작 시연.

### Out of scope
- 외부 저장소 연동, chat_history의 영속화 — 호출자 책임으로 위임.
- 큐레이션 정책(요약·필터링·압축 등) — 단순 누적만 수행.
- 원본 질의 저장 — 사용자 결정에 따라 리라이팅된 결과만 저장.
- evals/ 갱신.

## 설계

### 1. State 변경

`src/state.py`:

```python
import operator
from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    next_agent: str
    chat_history: Annotated[list[BaseMessage], operator.add]
```

- 형태: `list[BaseMessage]` (한 턴 = `HumanMessage` + `AIMessage` 2개).
- 리듀서: `operator.add` (단순 list concat). `add_messages`를 쓰지 않는 이유는 ID 기반 병합/덮어쓰기 의도가 없기 때문.
- 기존 `messages` 흐름은 그대로 (라우터·서브에이전트·response_generator 동작 변경 없음).

### 2. query_rewriter 변경

`src/query_rewriter/rewriter.py`:

기존:
```python
response = llm.invoke([SystemMessage(content=system_prompt)] + list(state["messages"]))
```

변경 후:
```python
chat_history = state.get("chat_history", [])
response = llm.invoke(
    [SystemMessage(content=system_prompt)]
    + list(chat_history)
    + [HumanMessage(content=original)]
)
```

- 리라이터는 더 이상 `state["messages"]` 전체를 컨텍스트로 사용하지 않는다. 명시적으로 호출자가 넣어준 `chat_history`만 참고한다.
- 현재 턴의 사용자 질의는 마지막 메시지로 단독 전달하여, "지금 풀어야 할 입력"이 모호하지 않게 한다.
- `chat_history`가 비어 있으면 (첫 턴) prompt + 현재 `HumanMessage`만 전달되어, 시간 표현·용어 치환 같은 단일 턴 동작은 정상 작동한다.
- prompt 본문(`src/query_rewriter/prompt.py`)의 "### 2. 대화 맥락 보충" 섹션 문구를 약간 다듬어, 리라이터에게 "이전 대화는 큐레이션된 chat_history로 주어진다"는 점을 명시한다. (규칙 자체는 유지)

### 3. response_generator 변경

`src/response_generator/`:

기존 반환값:
```python
return {"messages": [AIMessage(content=final_output)]}
```

변경 후:
```python
last_human = _find_last_human_message(state)
update = {"messages": [AIMessage(content=final_output)]}
if last_human is not None:
    update["chat_history"] = [
        HumanMessage(content=last_human.content),
        AIMessage(content=final_output),
    ]
return update
```

- "마지막 `HumanMessage`" = 리라이팅된 사용자 질의. 리라이터가 변경을 만들었다면 두 번째 `HumanMessage`, no-op이면 호출자가 넣은 원본 `HumanMessage`. 어느 쪽이든 의미상 "리라이팅 결과"로 합의된 형태.
- 이 시점에 `chat_history` reducer가 누적해 다음 turn 호출자가 통째로 활용 가능.
- `state["messages"]`에 `HumanMessage`가 전혀 없는 비정상 상황에서는 `chat_history` 업데이트를 생략하고 `messages`만 반환.

`_find_last_human_message`는 `query_rewriter`의 동명 헬퍼와 동일 동작이다. 두 노드가 공유하도록 별도 모듈(예: `src/state_utils.py`)로 추출하는 안도 검토 가능하나, 함수가 4줄 짜리이고 도메인 차이가 크지 않으므로 일단 각 모듈에 그대로 두고, 중복이 더 늘어나면 그때 추출한다.

### 4. 데이터 흐름 (멀티턴)

```
[Turn 1]
caller invoke({messages: [HumanMessage("지난주 매출")], chat_history: [], next_agent: ""})
  → query_rewriter (chat_history=[] 이므로 단일 턴 리라이팅)
  → ... → response_generator
  → result.chat_history = [HumanMessage("2026-04-13~2026-04-19 매출 알려줘"), AIMessage("...결과...")]

[Turn 2]
caller invoke({
  messages: [HumanMessage("이거 영어로 바꿔줘")],
  chat_history: <turn 1 결과의 chat_history>,
  next_agent: "",
})
  → query_rewriter (chat_history 참조하여 "이거"의 지칭 대상을 turn 1의 출력으로 풀이)
  → ... → response_generator
  → result.chat_history = [<turn1 두개>, HumanMessage("리라이팅된 turn 2 질의"), AIMessage("...영어 출력...")]
```

호출자는 이전 턴의 결과 state에서 `chat_history` 리스트를 받아, 다음 invoke 입력에 그대로 전달한다. 영속화·자르기·요약은 호출자 결정.

## 테스트 계획

### tests/test_query_rewriter.py
- 기존 `test_passes_full_conversation_to_llm`을 `test_passes_chat_history_to_llm`로 교체.
  - mock LLM 호출 인자가 `[SystemMessage, ...chat_history, HumanMessage(current)]` 구조인지 검증.
- 기존 케이스의 state dict에 `chat_history: []` 추가 (가독성/명시성).
- 신규: 빈 `chat_history`일 때 LLM에 `[SystemMessage, HumanMessage(current)]` 2개만 전달되는지.
- 신규: `chat_history`에 메시지가 있을 때, 그것이 SystemMessage 뒤·현재 HumanMessage 앞 위치에 들어가는지.

### tests/test_response_generator.py
- 신규: 반환값 dict에 `chat_history` 키가 포함되고, 그 길이가 2 (HumanMessage + AIMessage)인지.
- 신규: 반환된 `chat_history[0].content`가 state["messages"]의 마지막 HumanMessage와 동일한지.
- 신규: 반환된 `chat_history[1].content`가 새로 만든 AIMessage 본문과 동일한지.
- 신규: `state["messages"]`에 HumanMessage가 없는 경우 반환 dict에서 `chat_history` 키가 **생략**되는지 (`"chat_history" not in result`).

### main.py
- 시나리오 E 추가: 멀티턴 데모.
  - 1차 invoke: 단일 턴 질의로 결과 + chat_history 획득.
  - 2차 invoke: 1차의 chat_history를 입력에 포함하여, "이거 …" 형태의 맥락 의존 질의가 정상 리라이팅되는지 로그로 확인.

## 에러 처리 / 엣지 케이스

- `chat_history` 키가 입력에 없으면 `state.get("chat_history", [])`로 안전하게 빈 리스트로 처리.
- 리라이터가 변경하지 않았을 때 (`rewritten == original`) `state["messages"]`의 마지막 HumanMessage는 호출자가 넣은 원본이 됨 → response_generator는 그것을 그대로 chat_history에 적재. 의미상 "리라이팅 결과"로 본다 (no-op이면 원본 == 리라이팅 결과).
- response_generator 실행 시점에 `state["messages"]`에 HumanMessage가 전혀 없는 경우 (그래프 오용) → chat_history 업데이트 skip.
- chat_history가 매우 길어질 때의 토큰 한계 → 호출자 책임 (out of scope).

## 영향 분석

- 변경 대상 파일: `src/state.py`, `src/query_rewriter/rewriter.py`, `src/query_rewriter/prompt.py` (문구만), `src/response_generator/*.py`, `src/main.py`, `tests/test_query_rewriter.py`, `tests/test_response_generator.py`.
- 변경 없음: `src/router/*`, `src/registry.py`, 각 서브에이전트(`src/math_agent`, `src/translate_agent`, `src/sql_agent`).
- 외부 인터페이스 영향: `app.invoke(...)` 호출자는 `chat_history` 필드를 입력에 포함시켜야 한다 (없으면 빈 리스트로 동작). 기존 단일 턴 호출은 동작 그대로.
