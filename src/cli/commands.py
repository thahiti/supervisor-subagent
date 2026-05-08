"""슬래시 명령 dispatcher."""

from typing import TypedDict

from langchain_core.messages import BaseMessage


class CommandResult(TypedDict, total=False):
    output: str
    chat_history: list[BaseMessage]
    should_exit: bool


def is_command(text: str) -> bool:
    """입력이 슬래시 명령인지 판정한다 (선행 공백 허용 안 함)."""
    return bool(text) and text.startswith("/")


def handle_command(
    text: str,
    chat_history: list[BaseMessage],
    suggestions: dict[str, list[str]],
) -> CommandResult:
    """슬래시 명령을 처리하고 결과를 반환한다.

    인식하지 못하는 명령은 안내 문구를 output에 담아 반환한다.
    """
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0]
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("/exit", "/quit"):
        return {"should_exit": True, "output": "Bye."}

    if cmd == "/reset":
        return {
            "chat_history": [],
            "output": "Chat history reset.",
        }

    if cmd == "/list":
        return {"output": _format_list(suggestions, arg)}

    if cmd == "/help":
        return {"output": _HELP_TEXT}

    return {"output": f"Unknown command: {cmd} (try /help)"}


_HELP_TEXT = (
    "Commands:\n"
    "  /exit, /quit       세션 종료\n"
    "  /reset             chat_history 초기화\n"
    "  /list              모든 추천 질문 표시\n"
    "  /list <agent>      특정 카테고리만 표시\n"
    "  /help              이 도움말 표시"
)


def _format_list(suggestions: dict[str, list[str]], arg: str) -> str:
    if not suggestions:
        return "(추천 질문이 없습니다)"

    if arg:
        items = suggestions.get(arg)
        if items is None:
            available = ", ".join(suggestions.keys()) or "(없음)"
            return f"Unknown category: {arg} (available: {available})"
        return _format_category(arg, items)

    sections = [_format_category(cat, items) for cat, items in suggestions.items()]
    return "\n\n".join(sections)


def _format_category(category: str, items: list[str]) -> str:
    lines = [f"[{category}]"]
    for i, text in enumerate(items, 1):
        lines.append(f"  {i}) {text}")
    return "\n".join(lines)
