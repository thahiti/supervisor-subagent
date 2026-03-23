import json
import textwrap
from typing import Any

from langchain_core.messages import BaseMessage


def _try_parse_json(text: str) -> str | None:
    """텍스트에서 JSON을 추출하여 정렬된 형태로 반환한다."""
    clean = text.strip()
    if clean.startswith("```"):
        first_newline = clean.find("\n")
        if first_newline == -1:
            return None
        end = clean.rfind("```")
        if end <= first_newline:
            return None
        clean = clean[first_newline + 1:end].strip()

    try:
        parsed = json.loads(clean)
        # dict/list만 JSON으로 포맷 (숫자, 문자열 등 스칼라는 무시)
        if not isinstance(parsed, (dict, list)):
            return None
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, ValueError):
        return None


def _format_content(content: str, indent: str) -> str:
    """메시지 content를 그대로 출력한다.

    JSON이면 파싱하여 들여쓰기, 아니면 원문 그대로 출력.
    여러 줄이거나 긴 텍스트는 줄바꿈 후 들여쓰기한다.
    """
    json_str = _try_parse_json(content)
    if json_str:
        return "\n" + textwrap.indent(json_str, indent)

    if "\n" in content:
        return "\n" + textwrap.indent(content, indent)

    return content


def _format_message(msg: BaseMessage, indent: str = "        ") -> str:
    """메시지를 구조화된 문자열로 변환한다."""
    msg_type = type(msg).__name__
    tool_calls = getattr(msg, "tool_calls", None)

    parts: list[str] = [f"type: {msg_type}"]

    if tool_calls:
        calls_json = json.dumps(tool_calls, ensure_ascii=False, indent=2)
        parts.append(f"tool_calls:\n{textwrap.indent(calls_json, indent)}")

    content = str(msg.content)
    if content:
        formatted_content = _format_content(content, indent)
        parts.append(f"content: {formatted_content}")

    return ", ".join(parts)


def _type_name(value: Any) -> str:
    """값의 타입명을 반환한다."""
    if isinstance(value, list):
        if value:
            elem_type = type(value[0]).__name__
            return f"list[{elem_type}]"
        return "list"
    return type(value).__name__


def _format_value(value: Any) -> str:
    """값을 (type) value 형태로 포맷한다."""
    type_str = _type_name(value)
    if isinstance(value, list):
        if value and isinstance(value[0], BaseMessage):
            return f"({type_str}) {len(value)} messages"
        return f"({type_str}) {repr(value)}"
    return f"({type_str}) {repr(value)}"


def _prefix_lines(text: str, marker: str) -> str:
    """여러 줄 텍스트의 각 줄 선두에 marker를 삽입한다.

    기존 들여쓰기를 유지하면서 marker를 선두 공백 자리에 끼워넣는다.
    예: marker="+" 이면 "    foo" → "+   foo"
    """
    result: list[str] = []
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        indent_len = len(line) - len(stripped)
        if indent_len >= len(marker):
            new_line = marker + " " * (indent_len - len(marker)) + stripped
        else:
            new_line = marker + stripped
        result.append(new_line)
    return "\n".join(result)


def format_state_diff(before: dict, after: dict) -> str:
    """before 상태와 after 업데이트를 git diff 스타일로 출력한다.

    - 변경 없는 필드: 공백 prefix (  )
    - 추가된 값: + prefix
    - 제거된 값: - prefix
    - 변경된 값: - (이전) / + (이후)

    Args:
        before: 노드 실행 전 상태
        after: 노드가 반환한 업데이트

    Returns:
        git diff 스타일 문자열
    """
    merged = {**before, **after}
    lines: list[str] = []

    for key in merged:
        old_value = before.get(key)
        new_value = after.get(key)
        is_changed = key in after and old_value != new_value

        # messages 필드
        if key == "messages":
            old_msgs = old_value if isinstance(old_value, list) else []
            new_msgs = new_value if isinstance(new_value, list) else []
            added = [m for m in (new_msgs or []) if isinstance(m, BaseMessage)]

            if added:
                total = len(old_msgs) + len(added)
                lines.append(f"  {key}: (list[BaseMessage]) {total} messages")
                for i, msg in enumerate(old_msgs):
                    if isinstance(msg, BaseMessage):
                        lines.append(f"    [{i}] {_format_message(msg)}")
                for j, msg in enumerate(added):
                    idx = len(old_msgs) + j
                    msg_str = _format_message(msg)
                    lines.append(_prefix_lines(f"    [{idx}] {msg_str}", "+"))
            else:
                lines.append(f"  {key}: (list[BaseMessage]) {len(old_msgs)} messages")
                for i, msg in enumerate(old_msgs):
                    if isinstance(msg, BaseMessage):
                        lines.append(f"    [{i}] {_format_message(msg)}")
            continue

        # list 필드
        if isinstance(old_value, list) and isinstance(new_value, list):
            type_str = _type_name(new_value)
            if old_value != new_value:
                added = [x for x in new_value if x not in old_value]
                removed = [x for x in old_value if x not in new_value]
                if removed or added:
                    lines.append(f"  {key}: ({type_str})")
                    for item in removed:
                        lines.append(f"-     {repr(item)}")
                    for item in old_value:
                        if item not in removed:
                            lines.append(f"      {repr(item)}")
                    for item in added:
                        lines.append(f"+     {repr(item)}")
                else:
                    lines.append(f"  {key}: ({type_str}) {repr(new_value)}")
            else:
                lines.append(f"  {key}: ({type_str}) {repr(old_value)}")
            continue

        # 일반 필드
        if is_changed:
            lines.append(f"-   {key}: {_format_value(old_value)}")
            lines.append(f"+   {key}: {_format_value(new_value)}")
        else:
            value = new_value if new_value is not None else old_value
            lines.append(f"  {key}: {_format_value(value)}")

    return "\n".join(lines)


def format_state_pretty(state: dict) -> str:
    """상태를 구조화된 포맷으로 출력한다 (diff 없이).

    Args:
        state: 출력할 상태 dict

    Returns:
        구조화된 문자열
    """
    lines: list[str] = []
    for key, value in state.items():
        if key == "messages" and isinstance(value, list):
            lines.append(f"  {key}: (list[BaseMessage]) {len(value)} messages")
            for i, msg in enumerate(value):
                if isinstance(msg, BaseMessage):
                    lines.append(f"    [{i}] {_format_message(msg)}")
                else:
                    lines.append(f"    [{i}] {repr(msg)}")
        elif isinstance(value, list):
            lines.append(f"  {key}: {repr(value)}")
        else:
            lines.append(f"  {key}: {_format_value(value)}")
    return "\n".join(lines)
