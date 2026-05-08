"""prompt_toolkit 기반 입력 세션과 fuzzy 자동완성 빌더."""

from __future__ import annotations

import sys
from typing import TextIO

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import FuzzyCompleter, WordCompleter

from src.cli.suggestions import flatten


HEADER_TEMPLATE = (
    "사용 가능한 추천 질문 (입력 중 자동 제안)\n"
    "{rows}\n\n"
    "명령: /list <agent>  /reset  /exit  /help\n"
)


def build_completer(suggestions: dict[str, list[str]]) -> FuzzyCompleter:
    """카테고리별 추천 질문을 평면화하여 fuzzy completer로 빌드한다.

    카테고리 라벨은 메뉴 우측 meta 컬럼에 표시된다.
    """
    flat, meta = flatten(suggestions)
    base = WordCompleter(
        flat,
        ignore_case=True,
        sentence=True,
        match_middle=True,
        meta_dict=meta,
    )
    return FuzzyCompleter(base)


def build_prompt_session(suggestions: dict[str, list[str]]) -> PromptSession:
    """fuzzy completer가 결합된 PromptSession을 생성한다."""
    return PromptSession(completer=build_completer(suggestions))


def render_header(
    suggestions: dict[str, list[str]],
    stream: TextIO | None = None,
    preview_per_category: int = 1,
) -> None:
    """REPL 시작 시 카테고리 미리보기 헤더를 출력한다."""
    out = stream if stream is not None else sys.stdout

    if not suggestions:
        out.write(
            "추천 질문이 비어 있습니다 (자유 입력만 가능)\n"
            "명령: /list <agent>  /reset  /exit  /help\n"
        )
        out.flush()
        return

    label_width = max(len(c) for c in suggestions)
    rows: list[str] = []
    for category, items in suggestions.items():
        for text in items[:preview_per_category]:
            rows.append(f"  {category.ljust(label_width)}  · {text}")

    out.write(HEADER_TEMPLATE.format(rows="\n".join(rows)))
    out.flush()
