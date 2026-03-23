from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from src.logging import get_logger, log_node
from src.state import State, WorkerState

logger = get_logger("agent.math")
router_logger = get_logger("router.math")


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
        logger.warning("0으로 나누기 시도: a=%s, b=%s", a, b)
        return "오류: 0으로 나눌 수 없습니다."
    return str(a / b)


MATH_TOOLS = [add, multiply, divide]


def build_math_agent() -> CompiledStateGraph:
    """수학 계산 에이전트 서브그래프를 빌드한다."""

    @log_node("math_agent_internal")
    def math_agent_node(state: WorkerState) -> dict:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        llm_with_tools = llm.bind_tools(MATH_TOOLS)

        system_msg = SystemMessage(content=(
            "당신은 수학 계산 전문 에이전트입니다.\n"
            "사용자의 요청에 따라 add, multiply, divide 도구를 사용하여 계산하세요.\n"
            "계산 결과를 명확하게 한국어로 설명하세요."
        ))

        messages = [system_msg] + state["messages"]

        logger.info("LLM 호출 시작 (model=gpt-4o-mini, tools=%d)", len(MATH_TOOLS))
        try:
            response = llm_with_tools.invoke(messages)
        except Exception:
            logger.error("LLM 호출 실패", exc_info=True)
            raise

        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls:
            logger.info(
                "LLM tool_calls: %s",
                [(tc["name"], tc["args"]) for tc in tool_calls],
            )
        else:
            logger.info("LLM 최종 응답: %s", str(response.content)[:200])

        return {"messages": [response]}

    def should_continue(state: WorkerState) -> str:
        last_message = state["messages"][-1]
        has_tool_calls = bool(getattr(last_message, "tool_calls", None))
        decision = "tools" if has_tool_calls else END
        router_logger.info(
            "should_continue: tool_calls=%s → %s", has_tool_calls, decision,
        )
        return decision

    graph = StateGraph(WorkerState)
    tool_node = ToolNode(MATH_TOOLS)

    graph.add_node("agent", math_agent_node)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")

    return graph.compile()


math_subgraph = build_math_agent()


@log_node("math_wrapper")
def math_wrapper(state: State) -> dict:
    """수학 에이전트 서브그래프를 실행하고 completed_agents를 업데이트한다."""
    logger.info("서브그래프 실행 시작")
    try:
        result = math_subgraph.invoke({"messages": state["messages"]})
    except Exception:
        logger.error("서브그래프 실행 실패", exc_info=True)
        raise

    last_message = result["messages"][-1]
    completed = list(state.get("completed_agents", []))
    completed.append("math")

    logger.info("서브그래프 완료. 결과: %s", str(last_message.content)[:200])

    return {
        "messages": [AIMessage(content=f"[수학 계산 결과]\n{last_message.content}")],
        "completed_agents": completed,
    }
