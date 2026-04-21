"""자연어에서 코드형 토큰을 추출하고 딕셔너리 정의로 치환한다."""

import re

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
