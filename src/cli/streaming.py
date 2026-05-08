"""LangGraph stream chunk를 터미널 라인 이벤트로 렌더링한다."""

from __future__ import annotations

import sys
import time
from typing import Callable, TextIO

from langchain_core.messages import HumanMessage


def format_query_rewriter(delta: dict) -> list[str]:
    """변경된 query가 있으면 'rewritten: ...', 없으면 'no change'."""
    msgs = delta.get("messages") or []
    for msg in reversed(msgs):
        if isinstance(msg, HumanMessage):
            return [f"rewritten: {msg.content}"]
    return ["no change"]


def format_router(delta: dict) -> list[str]:
    next_agent = delta.get("next_agent") or ""
    if not next_agent:
        return []
    return [f"next_agent: {next_agent}"]


def format_agent(delta: dict) -> list[str]:
    """*_agent 노드는 노드명/경과시간만으로 충분 → 추가 라인 없음."""
    return []


def format_response_generator(delta: dict) -> list[str]:
    """최종 답변은 별도 render_final_answer로 출력하므로 추가 라인 없음."""
    return []


DEFAULT_FORMATTERS: dict[str, Callable[[dict], list[str]]] = {
    "query_rewriter": format_query_rewriter,
    "router": format_router,
    "math_agent": format_agent,
    "translate_agent": format_agent,
    "sql_agent": format_agent,
    "response_generator": format_response_generator,
}


SEPARATOR = "─" * 60


class NodeRenderer:
    """노드 단위 이벤트를 한 줄씩 터미널에 출력한다.

    경과 시간은 직전 노드 종료부터의 wall-clock 시간으로 측정한다
    (LangGraph stream_mode='updates'는 노드 완료 시점만 yield하므로
    노드별 정확한 시작 시간을 알 수 없다).
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        formatters: dict[str, Callable[[dict], list[str]]] | None = None,
    ) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._formatters = formatters or DEFAULT_FORMATTERS
        self._last_tick: float | None = None

    def turn_start(self) -> None:
        self._last_tick = time.monotonic()

    def on_node_update(self, node_name: str, delta: dict) -> None:
        now = time.monotonic()
        elapsed = (now - self._last_tick) if self._last_tick is not None else 0.0
        self._last_tick = now

        self._stream.write(f"▸ {node_name} … done ({elapsed:.2f}s)\n")
        formatter = self._formatters.get(node_name)
        extra = formatter(delta) if formatter else []
        for line in extra:
            self._stream.write(f"    {line}\n")
        self._stream.flush()

    def render_final_answer(self, content: str) -> None:
        self._stream.write("\n" + SEPARATOR + "\n")
        self._stream.write(content + "\n")
        self._stream.write(SEPARATOR + "\n\n")
        self._stream.flush()
