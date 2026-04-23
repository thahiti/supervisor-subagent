"""Text-to-SQL 프론트엔드 에이전트 (ReAct 서브그래프).

도메인 인식 레이어. 시스템 프롬프트에 스키마 + few-shot을 주입하고,
Backend를 감싼 tools를 LLM에 바인딩해 자연어 → SQL → 실행 → 설명의
루프를 수행한다.
"""

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.registry import registry
from src.agents.sql_agent.frontend.prompt import build_system_prompt
from src.agents.sql_agent.tools import SQL_TOOLS, SQL_TOOLS_BY_NAME
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.state import State, WorkerState

logger = get_logger("agent.sql")
router_logger = get_logger("router.sql")


def build_sql_agent() -> CompiledStateGraph:
    """SQL 에이전트 ReAct 서브그래프를 빌드한다."""

    system_prompt = build_system_prompt()

    @log_node("sql_agent_internal")
    def sql_agent_node(state: WorkerState) -> dict:
        llm = get_chat_model()
        llm_with_tools = llm.bind_tools(SQL_TOOLS)

        messages = [SystemMessage(content=system_prompt)] + state["messages"]

        logger.info("LLM 호출 시작 (tools=%d)", len(SQL_TOOLS))
        try:
            response = llm_with_tools.invoke(messages)
        except Exception:
            logger.error("LLM 호출 실패", exc_info=True)
            raise

        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls:
            logger.info(
                "LLM tool_calls: %s",
                [(tc["name"], _truncate_args(tc["args"])) for tc in tool_calls],
            )
        else:
            logger.info("LLM 최종 응답: %s", str(response.content)[:200])

        return {"messages": [response]}

    @log_node("sql_tool_executor")
    def tool_executor_node(state: WorkerState) -> dict:
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", [])

        results: list[ToolMessage] = []
        for tc in tool_calls:
            tool_fn = SQL_TOOLS_BY_NAME.get(tc["name"])
            if tool_fn is None:
                logger.error("알 수 없는 tool: %s", tc["name"])
                results.append(ToolMessage(
                    content=f"오류: 알 수 없는 tool '{tc['name']}'",
                    tool_call_id=tc["id"],
                ))
                continue

            logger.info("tool 실행: %s(%s)", tc["name"], _truncate_args(tc["args"]))
            try:
                result = tool_fn.invoke(tc["args"])
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
    graph.add_node("agent", sql_agent_node)
    graph.add_node("tools", tool_executor_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()


def _truncate_args(args: object, limit: int = 120) -> str:
    text = str(args)
    return text if len(text) <= limit else text[:limit] + "…"


sql_subgraph = build_sql_agent()


@registry.agent("sql")
def sql_wrapper(state: State) -> dict:
    """자연어로 ecommerce 데이터베이스(직원/부서/고객/제품/주문)를 질의합니다. SQL 쿼리가 필요한 데이터 조회, 집계, 분석에 사용합니다."""
    try:
        result = sql_subgraph.invoke({"messages": state["messages"]})
    except Exception:
        logger.error("서브그래프 실행 실패", exc_info=True)
        raise

    last_message = result["messages"][-1]

    return {
        "messages": [AIMessage(content=f"[SQL 조회 결과]\n{last_message.content}")],
    }
