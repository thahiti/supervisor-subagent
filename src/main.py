"""Router-Subagent 패턴 데모.

핵심 아이디어:
- Router가 사용자 요청을 분석하고 가장 적합한 단일 Subagent에게 작업을 위임한다.
- 선택된 Subagent 실행 후 곧바로 response_generator로 이동한다.
- Math Agent: 수학 계산 tool(add, multiply, divide)을 사용하는 ReAct 에이전트
- Translate Agent: LLM 직접 호출로 영한 번역을 수행하는 에이전트
- SQL Agent: ecommerce DB를 자연어로 질의하는 ReAct 에이전트

실행 방법:
    uv run python -m src.main

실행 흐름:
    [START] → [query_rewriter] → [router] → [선택된 subagent] → [response_generator] → END
                                         └→ [response_generator] (FINISH) ─────────→ END
"""

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from src.registry import registry
from src.query_rewriter import query_rewriter_node
from src.response_generator import response_generator_node
from src.router import router_conditional, router_node
from src.logging import get_logger, setup_logging
from src.logging.diff import format_state_pretty
from src.state import State

logger = get_logger("main")


def build_graph():
    """Router-Subagent 메인 그래프를 빌드한다."""
    graph = StateGraph(State)

    graph.add_node("query_rewriter", query_rewriter_node)
    graph.add_node("router", router_node)
    graph.add_node("response_generator", response_generator_node)

    node_names: list[str] = []
    for entry in registry.entries:
        graph.add_node(entry.node_name, entry.wrapper)
        graph.add_edge(entry.node_name, "response_generator")
        node_names.append(entry.node_name)

    graph.add_edge(START, "query_rewriter")
    graph.add_edge("query_rewriter", "router")
    graph.add_conditional_edges(
        "router",
        router_conditional,
        [*node_names, "response_generator"],
    )
    graph.add_edge("response_generator", END)

    return graph.compile()


def run_scenario(app, name: str, description: str, user_message: str) -> None:
    """데모 시나리오를 실행하고 결과를 출력한다."""
    logger.info("시나리오 %s: %s", name, description)
    logger.info("입력: %s", user_message)

    result = app.invoke({
        "messages": [HumanMessage(content=user_message)],
        "next_agent": "",
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
    logger.info("Router-Subagent 패턴 데모 시작")

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

    run_scenario(
        app, "D", "SQL 조회",
        "연봉이 5천만원 이상인 직원은 몇 명인가요?",
    )


if __name__ == "__main__":
    main()
