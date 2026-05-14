"""tool_call 에이전트: 함수형 도구 ReAct 서브그래프."""

from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.registry import registry
from src.state import State, WorkerState
from src.tool_call_agent.prompt import SYSTEM_PROMPT
from src.tool_call_agent.tools import TOOLS, TOOLS_BY_NAME

logger = get_logger("agent.tool_call")
router_logger = get_logger("router.tool_call")


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def build_tool_call_agent() -> CompiledStateGraph:
    """ReAct 서브그래프(agent ↔ tools 루프)를 빌드한다."""

    @log_node("tool_call_agent_internal")
    def agent_node(state: WorkerState) -> dict:
        llm = get_chat_model().bind_tools(TOOLS)
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]

        logger.info("LLM 호출 시작 (tools=%d)", len(TOOLS))
        try:
            response = llm.invoke(messages)
        except Exception:
            logger.error("LLM 호출 실패", exc_info=True)
            raise

        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls:
            logger.info(
                "LLM tool_calls: %s",
                [(tc["name"], _truncate(str(tc["args"]))) for tc in tool_calls],
            )
        else:
            logger.info("LLM 최종 응답: %s", _truncate(str(response.content), 200))

        return {"messages": [response]}

    @log_node("tool_call_tool_executor")
    def tool_executor_node(state: WorkerState) -> dict:
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", []) or []

        results: list[ToolMessage] = []
        for tc in tool_calls:
            fn = TOOLS_BY_NAME.get(tc["name"])
            if fn is None:
                logger.error("알 수 없는 tool: %s", tc["name"])
                results.append(ToolMessage(
                    content=f"ERROR: 알 수 없는 tool '{tc['name']}'",
                    tool_call_id=tc["id"],
                ))
                continue

            logger.info("tool 실행: %s(%s)", tc["name"], _truncate(str(tc["args"])))
            try:
                out = fn.invoke(tc["args"])
                results.append(ToolMessage(content=str(out), tool_call_id=tc["id"]))
            except Exception as exc:
                logger.error("tool 실행 실패: %s", tc["name"], exc_info=True)
                results.append(ToolMessage(
                    content=f"ERROR: {tc['name']} 실행 중 예외: {exc}",
                    tool_call_id=tc["id"],
                ))
        return {"messages": results}

    def should_continue(state: WorkerState) -> str:
        last = state["messages"][-1]
        has_tool_calls = bool(getattr(last, "tool_calls", None))
        decision = "tools" if has_tool_calls else END
        router_logger.info(
            "should_continue: tool_calls=%s → %s", has_tool_calls, decision,
        )
        return decision

    graph = StateGraph(WorkerState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_executor_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()


tool_call_subgraph = build_tool_call_agent()


@registry.agent("tool_call")
@log_node("tool_call")
def tool_call_wrapper(state: State) -> dict:
    """제조업 브랜치(공장)별 머신 정보 조회를 처리합니다.

    처리 가능한 질의 유형:
    - 등록된 브랜치(공장) 목록 조회 (예: "어떤 브랜치가 있어?", "공장 목록 보여줘")
    - 특정 브랜치의 머신(설비) 목록 조회 (예: "아산 1공장의 머신 목록", "F-A 브랜치의 설비")
    - 특정 머신의 현재 상태/가동률 조회 (예: "아산 1공장 M-001 머신 상태", "F-B의 압출기 가동률")
    - 브랜치를 모르고 질문한 경우 사용자에게 어느 브랜치인지 되묻고, 사용자가 동의하면 브랜치 목록을 제공

    데이터 구조:
    - 본사 메타DB에 브랜치 코드/이름/지역/DB 경로가 등록되어 있음
    - 각 브랜치마다 별도의 DB 파일이 존재하며, 머신 정보는 해당 브랜치 DB에서만 조회 가능
    - 따라서 브랜치 정보가 명시되지 않은 머신 질의는 먼저 브랜치를 확정해야 함

    실행 방식:
    - 사전 정의된 함수형 도구들(브랜치 목록 조회, 브랜치 DB 경로 조회, 머신 목록 조회, 머신 상태 조회)을 ReAct 루프로 순차/조합 호출
    - 도구 실행에 필요한 파라미터(브랜치 코드, 머신 id 등)가 부족하면 사용자에게 자연어로 되묻고 그 턴을 종료. 다음 턴에서 사용자가 정보를 보충하면 이어서 실행

    라우팅 가이드:
    - 브랜치/공장/머신/설비/가동률/라인 같은 제조 도메인 키워드가 등장하면 이 에이전트
    - 직원/부서/고객/제품/주문 등 ecommerce 도메인은 이 에이전트가 아님 (sql 또는 templated_sql)
    - 자유형 임의 SQL이 필요한 분석성 질의는 이 에이전트가 아님 (sql)
    """
    try:
        result = tool_call_subgraph.invoke({"messages": state["messages"]})
    except Exception:
        logger.error("서브그래프 실행 실패", exc_info=True)
        raise

    last = result["messages"][-1]
    return {"messages": [AIMessage(content=f"[조회 결과]\n{last.content}")]}
