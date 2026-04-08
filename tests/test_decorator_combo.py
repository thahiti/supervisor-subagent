"""registry.agent()과 log_node() 데코레이터 조합 테스트.

@registry.agent는 반드시 outermost 데코레이터로 사용해야 한다.
"""

import logging

import pytest

from src.agents.registry import AgentRegistry
from src.logging.decorator import log_node
from src.state import State


@pytest.fixture
def fresh_registry() -> AgentRegistry:
    return AgentRegistry()


def test_agent_only(fresh_registry: AgentRegistry) -> None:
    """@registry.agent만 사용 — 기본 동작 확인."""
    @fresh_registry.agent("echo")
    def echo_wrapper(state: State) -> dict:
        """에코 에이전트: 입력을 그대로 반환합니다."""
        return {"messages": state["messages"]}

    entry = fresh_registry.get("echo")
    assert entry is not None
    assert entry.description == "에코 에이전트: 입력을 그대로 반환합니다."

    state: State = {"messages": [], "next_agent": "", "plan": "", "completed_agents": []}
    result = echo_wrapper(state)
    assert result == {"messages": []}


def test_log_node_only() -> None:
    """@log_node만 사용 — 기본 동작 확인."""
    @log_node("echo")
    def echo_node(state: dict) -> dict:
        """에코 노드."""
        return {"messages": state["messages"]}

    result = echo_node({"messages": []})
    assert result == {"messages": []}


def test_agent_outer_log_node_inner(fresh_registry: AgentRegistry) -> None:
    """@registry.agent (outer) + @log_node (inner) — 두 기능 모두 동작해야 한다."""
    @fresh_registry.agent("echo")
    @log_node("echo_wrapper")
    def echo_wrapper(state: State) -> dict:
        """에코 에이전트: 입력을 그대로 반환합니다."""
        return {"messages": state["messages"]}

    entry = fresh_registry.get("echo")
    assert entry is not None
    assert entry.description == "에코 에이전트: 입력을 그대로 반환합니다."

    state: State = {"messages": [], "next_agent": "", "plan": "", "completed_agents": []}

    result = entry.wrapper(state)
    assert result == {"messages": []}

    result2 = echo_wrapper(state)
    assert result2 == {"messages": []}


def test_agent_outer_log_node_inner_logging(
    fresh_registry: AgentRegistry, caplog: pytest.LogCaptureFixture,
) -> None:
    """@registry.agent (outer) + @log_node (inner) — registry 경유 호출 시 로깅이 발생해야 한다."""
    @fresh_registry.agent("echo")
    @log_node("echo_wrapper")
    def echo_wrapper(state: State) -> dict:
        """에코 에이전트: 입력을 그대로 반환합니다."""
        return {"messages": state["messages"]}

    entry = fresh_registry.get("echo")
    assert entry is not None

    state: State = {"messages": [], "next_agent": "", "plan": "", "completed_agents": []}

    with caplog.at_level(logging.INFO):
        entry.wrapper(state)

    assert any("ECHO_WRAPPER" in record.message for record in caplog.records), \
        "registry 경유 호출 시 log_node 로깅이 발생하지 않음"
