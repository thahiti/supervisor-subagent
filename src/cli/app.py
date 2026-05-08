"""인터랙티브 CLI 진입점: REPL 루프 + chat_history 인계."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from prompt_toolkit import PromptSession

load_dotenv()

from src.cli.commands import handle_command, is_command
from src.cli.prompt import build_prompt_session, render_header
from src.cli.streaming import NodeRenderer
from src.cli.suggestions import load_suggestions
from src.logging import setup_logging
from src.main import build_graph


DEFAULT_SUGGESTIONS_PATH = Path(__file__).resolve().parents[2] / "res" / "suggestions.yaml"


def run_turn(
    app,
    user_input: str,
    chat_history: list[BaseMessage],
    renderer: NodeRenderer,
) -> tuple[list[BaseMessage], BaseMessage | None]:
    """1턴을 실행하고 (새 chat_history, 마지막 AI 메시지)를 반환한다.

    response_generator의 delta에 chat_history가 포함되어 있으면 누적하여 반환한다.
    그렇지 않으면 입력 chat_history를 그대로 반환한다.
    """
    state = {
        "messages": [HumanMessage(content=user_input)],
        "next_agent": "",
        "chat_history": chat_history,
    }

    new_history: list[BaseMessage] = list(chat_history)
    final_ai: BaseMessage | None = None

    renderer.turn_start()
    for chunk in app.stream(state, stream_mode="updates"):
        for node_name, delta in chunk.items():
            renderer.on_node_update(node_name, delta or {})
            if not delta:
                continue
            ch = delta.get("chat_history")
            if ch:
                new_history = new_history + list(ch)
            if node_name == "response_generator":
                msgs = delta.get("messages") or []
                if msgs:
                    final_ai = msgs[-1]

    if isinstance(final_ai, AIMessage):
        renderer.render_final_answer(final_ai.content)

    return new_history, final_ai


def run(
    suggestions_path: Path | None = None,
    verbose: bool = False,
) -> None:
    """REPL 진입점."""
    setup_logging(level=logging.INFO if verbose else logging.WARNING)

    suggestions = load_suggestions(suggestions_path or DEFAULT_SUGGESTIONS_PATH)
    render_header(suggestions)

    session: PromptSession = build_prompt_session(suggestions)
    graph = build_graph()
    renderer = NodeRenderer()

    chat_history: list[BaseMessage] = []
    while True:
        try:
            user_input = session.prompt("질문> ")
        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            print()
            break

        text = user_input.strip()
        if not text:
            continue

        if is_command(text):
            result = handle_command(text, chat_history, suggestions)
            if result.get("output"):
                print(result["output"])
            if "chat_history" in result:
                chat_history = result["chat_history"]
            if result.get("should_exit"):
                break
            continue

        try:
            chat_history, _ = run_turn(graph, text, chat_history, renderer)
        except KeyboardInterrupt:
            print("\n(turn interrupted; chat_history preserved)")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="src.cli", description="Interactive CLI")
    parser.add_argument("--verbose", action="store_true", help="INFO 로그 노출")
    parser.add_argument(
        "--suggestions",
        type=Path,
        default=None,
        help=f"추천 질문 YAML 경로 (기본: {DEFAULT_SUGGESTIONS_PATH})",
    )
    args = parser.parse_args(argv)
    run(suggestions_path=args.suggestions, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
