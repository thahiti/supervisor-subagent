"""프로젝트 전체에서 사용하는 LLM 클라이언트를 한 곳에서 생성한다.

모든 에이전트/Judge는 이 팩토리를 통해 ChatOpenAI를 얻는다. 모델 교체나
공통 파라미터 조정이 필요하면 이 파일만 수정하면 된다.
"""

from langchain_openai import ChatOpenAI

DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.0


def get_chat_model(
    model: str | None = None,
    temperature: float | None = None,
) -> ChatOpenAI:
    """ChatOpenAI 인스턴스를 생성한다.

    Args:
        model: 사용할 모델명. 생략 시 DEFAULT_CHAT_MODEL을 사용한다.
        temperature: 샘플링 온도. 생략 시 DEFAULT_TEMPERATURE를 사용한다.

    Returns:
        설정이 적용된 ChatOpenAI 클라이언트.
    """
    return ChatOpenAI(
        model=model or DEFAULT_CHAT_MODEL,
        temperature=temperature if temperature is not None else DEFAULT_TEMPERATURE,
    )
