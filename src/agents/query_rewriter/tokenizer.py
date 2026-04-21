"""자연어에서 코드형 토큰을 추출하고 딕셔너리 정의로 치환한다."""

import re

from src.agents.query_rewriter.dictionary_client import DictionaryClient

_TOKEN_PATTERN = re.compile(r"([A-Z][A-Z0-9_&-]{2,})(?![A-Za-z0-9_&-])")


def extract_tokens(text: str) -> list[str]:
    """자연어에서 코드형 토큰을 추출하여 중복 없는 리스트로 반환한다.

    Args:
        text: 토큰을 추출할 자연어 문자열.

    Returns:
        추출된 토큰의 중복 제거 리스트 (등장 순서 유지).
    """
    matches = _TOKEN_PATTERN.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for token in matches:
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result


def tokenize(text: str, client: DictionaryClient) -> str:
    """자연어에서 토큰을 추출, 딕셔너리에서 정의를 조회하고, 원문을 치환한다.

    치환 형식: TOKEN → TOKEN(정의)
    조회 실패(빈 문자열)한 토큰은 치환하지 않는다.

    Args:
        text: 치환 대상 자연어 문자열.
        client: 토큰 정의를 조회할 딕셔너리 클라이언트.

    Returns:
        토큰이 정의로 치환된 문자열.
    """
    tokens = extract_tokens(text)
    if not tokens:
        return text

    definitions = client.lookup(tokens)

    result = text
    for token, definition in definitions.items():
        if definition:
            result = result.replace(token, f"{token}({definition})")

    return result
