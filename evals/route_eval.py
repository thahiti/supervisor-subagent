"""query_rewriter / router 파이프라인 코어 (CLI·스모크 공용).

단위 테스트(tests/test_route_eval.py)는 LLM을 목으로 대체해 조립 로직만
검증한다. 실제 LLM을 호출하는 검증은 scripts/ 스모크 스크립트가 CLI를
subprocess로 실행해 수행한다 (LLM-as-Judge 아님).
"""

from __future__ import annotations

from typing import Literal, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph.message import add_messages

from src.query_rewriter.rewriter import query_rewriter_node
from src.router import router_conditional, router_node
from src.state import State

Role = Literal["human", "ai"]


def to_messages(pairs: list[tuple[Role, str]]) -> list[BaseMessage]:
    """(role, content) 쌍 리스트를 BaseMessage 리스트로 변환한다."""
    out: list[BaseMessage] = []
    for role, content in pairs:
        if role == "human":
            out.append(HumanMessage(content=content))
        else:
            out.append(AIMessage(content=content))
    return out


def _last_human_text(messages: list[BaseMessage], default: str) -> str:
    """messages에서 마지막 HumanMessage 본문을 반환한다 (없으면 default)."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return cast(str, msg.content)
    return default


def rewrite(query: str, chat_history: list[BaseMessage]) -> str:
    """query_rewriter_node를 실행하고 리라이팅된 질의 텍스트를 반환한다.

    리라이팅이 없으면 원본 query를 그대로 반환한다.
    """
    state: State = {
        "messages": [HumanMessage(content=query)],
        "next_agent": "",
        "chat_history": chat_history,
    }
    rw = query_rewriter_node(state)
    merged = add_messages(state["messages"], rw["messages"])
    return _last_human_text(merged, query)


def route_trace(
    query: str, chat_history: list[BaseMessage]
) -> tuple[str, str]:
    """query_rewriter → router를 실제 LLM으로 연쇄 실행하고
    (리라이팅된 질의, 라우팅된 목적지 노드명)을 반환한다.
    """
    state: State = {
        "messages": [HumanMessage(content=query)],
        "next_agent": "",
        "chat_history": chat_history,
    }

    rw = query_rewriter_node(state)
    state["messages"] = add_messages(state["messages"], rw["messages"])
    rewritten = _last_human_text(state["messages"], query)

    rt = router_node(state)
    state["messages"] = add_messages(state["messages"], rt["messages"])
    state["next_agent"] = rt["next_agent"]

    return rewritten, router_conditional(state)
