from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class State(TypedDict):
    """Router-Subagent 시스템의 공유 상태.

    Attributes:
        messages: 전체 대화 이력 (add_messages 리듀서로 자동 병합)
        next_agent: 라우터가 결정한 다음 워커 (registry 이름 또는 "FINISH")
    """

    messages: Annotated[list[BaseMessage], add_messages]
    next_agent: str


class WorkerState(TypedDict):
    """워커 서브그래프의 내부 상태."""

    messages: Annotated[list[BaseMessage], add_messages]
