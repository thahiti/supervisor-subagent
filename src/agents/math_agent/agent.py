from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from src.state import State, WorkerState


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


MATH_TOOLS = [add, multiply, divide]


def build_math_agent() -> CompiledStateGraph:
    """수학 계산 에이전트 서브그래프를 빌드한다."""

    def math_agent_node(state: WorkerState) -> dict:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        llm_with_tools = llm.bind_tools(MATH_TOOLS)

        system_msg = SystemMessage(content=(
            "당신은 수학 계산 전문 에이전트입니다.\n"
            "사용자의 요청에 따라 add, multiply, divide 도구를 사용하여 계산하세요.\n"
            "계산 결과를 명확하게 한국어로 설명하세요."
        ))

        messages = [system_msg] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: WorkerState) -> str:
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
        return END

    graph = StateGraph(WorkerState)
    tool_node = ToolNode(MATH_TOOLS)

    graph.add_node("agent", math_agent_node)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")

    return graph.compile()


math_subgraph = build_math_agent()


def math_wrapper(state: State) -> dict:
    """수학 에이전트 서브그래프를 실행하고 completed_agents를 업데이트한다."""
    print(f"\n{'─'*40}")
    print("[MATH] 수학 계산 에이전트 시작")
    print(f"{'─'*40}")

    result = math_subgraph.invoke({"messages": state["messages"]})

    last_message = result["messages"][-1]
    completed = list(state.get("completed_agents", []))
    completed.append("math")

    print(f"[MATH] 완료. 결과: {last_message.content[:100]}...")

    return {
        "messages": [AIMessage(content=f"[수학 계산 결과]\n{last_message.content}")],
        "completed_agents": completed,
    }
