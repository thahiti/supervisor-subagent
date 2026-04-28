"""최종 답변 생성 노드: 페르소나를 적용하여 사용자에게 전달할 답변을 생성한다."""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src.response_generator.prompt import RESPONSE_GENERATOR_SYSTEM_PROMPT
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.state import State

logger = get_logger("response_generator")


def _find_last_human_message(messages: list[BaseMessage]) -> HumanMessage | None:
    """메시지 리스트에서 마지막 HumanMessage를 찾는다."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg
    return None


@log_node("response_generator")
def response_generator_node(state: State) -> dict:
    """서브에이전트 결과를 종합하여 페르소나가 적용된 최종 답변을 생성하고
    chat_history에 한 턴분(리라이팅된 사용자 질의 + 최종 출력)을 append한다.
    """
    llm = get_chat_model()

    messages = [
        SystemMessage(content=RESPONSE_GENERATOR_SYSTEM_PROMPT),
    ] + list(state["messages"])

    logger.info("최종 답변 생성 LLM 호출 시작")
    response = llm.invoke(messages)

    content: str = response.content  # type: ignore[assignment]
    logger.info("최종 답변: %s", content)

    final_ai = AIMessage(content=content)
    update: dict = {"messages": [final_ai]}

    last_human = _find_last_human_message(state["messages"])
    if last_human is not None:
        update["chat_history"] = [
            HumanMessage(content=last_human.content),
            AIMessage(content=content),
        ]

    return update
