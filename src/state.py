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
