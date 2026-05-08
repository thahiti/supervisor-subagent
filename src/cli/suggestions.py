"""추천 질문 YAML 로더 + 평면 리스트 변환."""

from pathlib import Path

import yaml

from src.logging import get_logger

logger = get_logger("cli.suggestions")


def load_suggestions(path: Path) -> dict[str, list[str]]:
    """카테고리별 추천 질문 dict를 로드한다.

    파일이 없거나 비어 있으면 빈 dict를 반환한다.
    최상위 구조가 dict가 아니면 ValueError를 발생시킨다.
    """
    if not path.exists():
        logger.warning("suggestions 파일을 찾을 수 없음: %s", path)
        return {}

    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}

    parsed = yaml.safe_load(raw)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ValueError(
            f"suggestions 최상위는 dict여야 합니다 (got {type(parsed).__name__}): {path}"
        )

    result: dict[str, list[str]] = {}
    for category, items in parsed.items():
        if not isinstance(items, list):
            logger.warning("카테고리 %s는 list가 아님 → 무시", category)
            continue
        result[str(category)] = [str(x) for x in items]
    return result


def flatten(suggestions: dict[str, list[str]]) -> tuple[list[str], dict[str, str]]:
    """평면 리스트와 {질문: 카테고리} 메타 dict를 반환한다.

    카테고리 등록 순서, 카테고리 내부 순서를 모두 보존한다.
    """
    flat: list[str] = []
    meta: dict[str, str] = {}
    for category, items in suggestions.items():
        for text in items:
            flat.append(text)
            meta[text] = category
    return flat, meta
