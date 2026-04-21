"""쿼리 리라이터 노드: 사용자 쿼리를 명확하게 재작성한다."""

from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.query_rewriter.dictionary_client import DictionaryClient, MockDictionaryClient
from src.agents.query_rewriter.prompt import build_rewriter_system_prompt
from src.agents.query_rewriter.tokenizer import extract_tokens
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.state import State

logger = get_logger("query_rewriter")

_dictionary_client: DictionaryClient = MockDictionaryClient({
    "KPI_01": "월간 매출 성장률",
    "ACC_RCV": "미수금 잔액",
    "NET_PRF": "순이익(매출 - 비용)",
})


def set_dictionary_client(client: DictionaryClient) -> None:
    """딕셔너리 클라이언트를 교체한다 (테스트/프로덕션 전환용)."""
    global _dictionary_client
    _dictionary_client = client


def _find_last_human_message(state: State) -> HumanMessage | None:
    """메시지 리스트에서 마지막 HumanMessage를 찾는다."""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            return msg
    return None


@log_node("query_rewriter")
def query_rewriter_node(state: State) -> dict:
    """사용자 쿼리에 시간 해석, 맥락 보충, 용어 치환을 적용하여 재작성한다."""
    last_human = _find_last_human_message(state)
    if last_human is None:
        logger.warning("HumanMessage를 찾을 수 없음 → 건너뜀")
        return {"messages": []}

    original = last_human.content
    logger.info("원본 쿼리: %s", original)

    tokens = extract_tokens(original)
    dictionary: dict[str, str] = {}
    if tokens:
        lookup_result = _dictionary_client.lookup(tokens)
        dictionary = {k: v for k, v in lookup_result.items() if v}
        logger.info("토큰 조회: %s → %s", tokens, dictionary)

    system_prompt = build_rewriter_system_prompt(now=datetime.now(), dictionary=dictionary)
    llm = get_chat_model()

    response = llm.invoke(
        [SystemMessage(content=system_prompt)] + list(state["messages"]),
    )

    rewritten: str = response.content  # type: ignore[assignment]
    logger.info("리라이팅 결과: %s", rewritten)

    if rewritten.strip() == original.strip():
        logger.info("변경 없음 → 원본 유지")
        return {"messages": []}

    return {"messages": [HumanMessage(content=rewritten)]}
