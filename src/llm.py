"""프로젝트 전체에서 사용하는 LLM 클라이언트를 한 곳에서 생성한다.

모든 에이전트/Judge는 이 팩토리를 통해 ChatOpenAI를 얻는다. 모델 교체나
공통 파라미터 조정이 필요하면 이 파일만 수정하면 된다.
"""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.0


def _get_api_key() -> str:
    """.env를 로드한 뒤 OPENAI_API_KEY를 반환한다.

    엔트리포인트(main.py 등)에서 load_dotenv()를 호출하지 않은 경로(테스트,
    스크립트, 직접 import)에서도 키가 적용되도록 이 팩토리에서 직접 로드한다.

    Returns:
        OPENAI_API_KEY 값.

    Raises:
        RuntimeError: 환경 변수와 .env 어디에도 키가 없을 때.
    """
    load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY가 설정되지 않았습니다. "
            ".env 파일에 OPENAI_API_KEY를 추가하세요 (.env.example 참고)."
        )
    return api_key


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
        api_key=_get_api_key(),
    )
