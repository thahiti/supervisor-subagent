"""최종 답변 생성 노드: 페르소나를 적용하여 사용자에게 전달할 답변을 생성한다."""

from langchain_core.messages import AIMessage, SystemMessage

from src.response_generator.prompt import RESPONSE_GENERATOR_SYSTEM_PROMPT
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.state import State

logger = get_logger("response_generator")


@log_node("response_generator")
def response_generator_node(state: State) -> dict:
    """서브에이전트 결과를 종합하여 페르소나가 적용된 최종 답변을 생성한다."""
    llm = get_chat_model()

    messages = [
        SystemMessage(content=RESPONSE_GENERATOR_SYSTEM_PROMPT),
    ] + list(state["messages"])

    logger.info("최종 답변 생성 LLM 호출 시작")
    response = llm.invoke(messages)

    content: str = response.content  # type: ignore[assignment]
    logger.info("최종 답변: %s", content)

    return {"messages": [AIMessage(content=content)]}
