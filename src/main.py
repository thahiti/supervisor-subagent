"""Supervisor-Subagent 패턴 데모.

핵심 아이디어:
- Supervisor가 사용자 요청을 분석하고 적절한 Subagent에게 작업을 위임한다.
- Math Agent: 수학 계산 tool(add, multiply, divide)을 사용하는 ReAct 에이전트
- Translate Agent: LLM 직접 호출로 영한 번역을 수행하는 에이전트

실행 방법:
    uv run python -m src.main

실행 흐름:
    [START] → [supervisor] → (라우터) → [math_agent]      → [supervisor] → ...
                                       → [translate_agent] → [supervisor]
                                       → END (FINISH)
"""

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from src.agents import math_wrapper, translate_wrapper
from src.logging import get_logger, setup_logging
from src.logging.diff import format_state_pretty
from src.state import State
from src.supervisor import supervisor_node, supervisor_router

logger = get_logger("main")


def build_graph():
    """Supervisor-Subagent 메인 그래프를 빌드한다."""
    graph = StateGraph(State)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("math_agent", math_wrapper)
    graph.add_node("translate_agent", translate_wrapper)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        supervisor_router,
        ["math_agent", "translate_agent", END],
    )
    graph.add_edge("math_agent", "supervisor")
    graph.add_edge("translate_agent", "supervisor")

    return graph.compile()


def run_scenario(app, name: str, description: str, user_message: str) -> None:
    """데모 시나리오를 실행하고 결과를 출력한다."""
    logger.info("시나리오 %s: %s", name, description)
    logger.info("입력: %s", user_message)

    result = app.invoke({
        "messages": [HumanMessage(content=user_message)],
        "next_agent": "",
        "plan": "",
        "completed_agents": [],
    })

    logger.info(
        "\n%s\n"
        "  [SCENARIO %s] Finished\n"
        "%s\n"
        "  Final State:\n%s\n"
        "%s",
        "=" * 60, name, "=" * 60,
        format_state_pretty(result),
        "=" * 60,
    )


def main():
    setup_logging()
    logger.info("Supervisor-Subagent 패턴 데모 시작")

    app = build_graph()

    run_scenario(
        app, "A", "수학 계산만",
        "3과 7을 더하고, 그 결과에 5를 곱해주세요",
    )

    run_scenario(
        app, "B", "번역만",
        "Hello, how are you?를 한국어로 번역해주세요",
    )

    run_scenario(
        app, "C", "복합 요청 (수학 + 번역)",
        "123 곱하기 456을 계산하고, 그 결과를 영어 문장으로 설명해주세요",
    )


if __name__ == "__main__":
    main()
