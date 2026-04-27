from langchain_core.messages import AIMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.registry import registry
from src.llm import get_chat_model
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
MATH_TOOLS_BY_NAME = {t.name: t for t in MATH_TOOLS}


def build_math_agent() -> CompiledStateGraph:
    """수학 계산 에이전트 서브그래프를 빌드한다."""

    @log_node("math_agent_internal")
    def math_agent_node(state: WorkerState) -> dict:
        llm = get_chat_model()
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
            logger.info("LLM 최종 응답: %s", response.content)

        return {"messages": [response]}

    @log_node("math_tool_executor")
    def tool_executor_node(state: WorkerState) -> dict:
        """tool_calls를 실행하고 결과를 ToolMessage로 반환한다."""
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", [])

        results: list[ToolMessage] = []
        for tc in tool_calls:
            tool_fn = MATH_TOOLS_BY_NAME.get(tc["name"])
            if tool_fn is None:
                logger.error("알 수 없는 tool: %s", tc["name"])
                results.append(ToolMessage(
                    content=f"오류: 알 수 없는 tool '{tc['name']}'",
                    tool_call_id=tc["id"],
                ))
                continue

            logger.info("tool 실행: %s(%s)", tc["name"], tc["args"])
            try:
                result = tool_fn.invoke(tc["args"])
                logger.info("tool 결과: %s → %s", tc["name"], result)
                results.append(ToolMessage(
                    content=str(result),
                    tool_call_id=tc["id"],
                ))
            except Exception:
                logger.error("tool 실행 실패: %s", tc["name"], exc_info=True)
                results.append(ToolMessage(
                    content=f"오류: {tc['name']} 실행 중 예외 발생",
                    tool_call_id=tc["id"],
                ))

        return {"messages": results}

    def should_continue(state: WorkerState) -> str:
        last_message = state["messages"][-1]
        has_tool_calls = bool(getattr(last_message, "tool_calls", None))
        decision = "tools" if has_tool_calls else END
        router_logger.info(
            "should_continue: tool_calls=%s → %s", has_tool_calls, decision,
        )
        return decision

    graph = StateGraph(WorkerState)

    graph.add_node("agent", math_agent_node)
    graph.add_node("tools", tool_executor_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")

    return graph.compile()


math_subgraph = build_math_agent()


@registry.agent("math")
def math_wrapper(state: State) -> dict:
    """수학 계산을 수행합니다. 덧셈, 곱셈, 나눗셈 등의 계산이 필요할 때 사용합니다."""
    try:
        result = math_subgraph.invoke({"messages": state["messages"]})
    except Exception:
        logger.error("서브그래프 실행 실패", exc_info=True)
        raise

    last_message = result["messages"][-1]

    return {
        "messages": [AIMessage(content=f"[수학 계산 결과]\n{last_message.content}")],
    }
