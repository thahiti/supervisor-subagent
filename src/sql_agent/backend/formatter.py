"""쿼리 결과를 사람/LLM이 읽기 쉬운 Markdown 표로 포매팅한다."""

from __future__ import annotations

from typing import Any


def to_markdown_table(
    columns: list[str],
    rows: list[tuple[Any, ...]],
    *,
    max_cell_width: int = 60,
) -> str:
    """쿼리 결과를 Markdown 표 문자열로 변환한다.

    Args:
        columns: 컬럼명 리스트.
        rows: 행 튜플 리스트.
        max_cell_width: 셀당 최대 표시 너비. 초과 시 말줄임표 처리.

    Returns:
        Markdown 형식의 표. 결과가 비어 있으면 안내 메시지.
    """
    if not columns:
        return "(결과 없음)"
    if not rows:
        return f"(0개 행 반환)\n\n| {' | '.join(columns)} |"

    formatted_rows = [
        [_format_cell(cell, max_cell_width) for cell in row] for row in rows
    ]

    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = "\n".join(
        "| " + " | ".join(cells) + " |" for cells in formatted_rows
    )
    summary = f"({len(rows)}개 행)"
    return f"{summary}\n{header}\n{separator}\n{body}"


def _format_cell(value: Any, max_width: int) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    if len(text) > max_width:
        return text[: max_width - 1] + "…"
    return text.replace("|", "\\|").replace("\n", " ")
