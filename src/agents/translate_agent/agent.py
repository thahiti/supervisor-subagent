from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.logging import get_logger, log_node
from src.state import State, WorkerState

logger = get_logger("agent.translate")

TRANSLATE_SYSTEM_PROMPT = """당신은 전문 번역가입니다.
주어진 텍스트를 정확하고 자연스럽게 번역하세요.

규칙:
1. 한국어 텍스트는 영어로 번역합니다.
2. 영어 텍스트는 한국어로 번역합니다.
3. 번역 결과만 깔끔하게 출력하세요.
4. 원문의 뉘앙스와 톤을 유지하세요."""


@log_node("translate_agent_internal")
def translate_agent_node(state: WorkerState) -> dict:
    """번역 에이전트: LLM 직접 호출로 번역을 수행한다."""
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    messages = [SystemMessage(content=TRANSLATE_SYSTEM_PROMPT)] + state["messages"]

    logger.info("LLM 호출 시작 (model=gpt-4o-mini)")
    try:
        response = llm.invoke(messages)
    except Exception:
        logger.error("LLM 호출 실패", exc_info=True)
        raise

    logger.info("LLM 응답: %s", str(response.content)[:200])
    return {"messages": [response]}


@log_node("translate_wrapper")
def translate_wrapper(state: State) -> dict:
    """번역 에이전트를 실행하고 completed_agents를 업데이트한다."""
    logger.info("번역 에이전트 실행 시작")
    result = translate_agent_node({"messages": state["messages"]})

    last_message = result["messages"][-1]
    completed = list(state.get("completed_agents", []))
    completed.append("translate")

    logger.info("번역 완료. 결과: %s", str(last_message.content)[:200])

    return {
        "messages": [AIMessage(content=f"[번역 결과]\n{last_message.content}")],
        "completed_agents": completed,
    }
