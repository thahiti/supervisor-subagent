import json
import textwrap
from typing import Any

from langchain_core.messages import BaseMessage


def _try_parse_json(text: str) -> str | None:
    """텍스트에서 JSON을 추출하여 정렬된 형태로 반환한다."""
    clean = text.strip()
    # ```json ... ``` 블록 제거
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
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, ValueError):
        return None


def _format_content(content: str, indent: str = "      ") -> str:
    """메시지 content를 읽기 좋게 포맷한다.

    JSON이면 파싱하여 들여쓰기, 아니면 줄바꿈 기준으로 들여쓰기.
    """
    json_str = _try_parse_json(content)
    if json_str:
        indented = textwrap.indent(json_str, indent)
        return f"\n{indented}"

    # 일반 텍스트: 길면 줄바꿈 후 들여쓰기
    if len(content) > 80 or "\n" in content:
        indented = textwrap.indent(content, indent)
        return f"\n{indented}"

    return content


def _summarize_message(msg: BaseMessage) -> str:
    """메시지를 구조화된 문자열로 변환한다."""
    msg_type = type(msg).__name__
    tool_calls = getattr(msg, "tool_calls", None)

    parts: list[str] = [f"type: {msg_type}"]
    if tool_calls:
        parts.append(f"tool_calls: {len(tool_calls)}")

    content = str(msg.content)
    formatted_content = _format_content(content)
    parts.append(f"content: {formatted_content}")

    return ", ".join(parts)


def _format_value(value: Any, max_len: int = 150) -> str:
    """값을 로그용 문자열로 포맷한다."""
    if isinstance(value, list):
        if value and isinstance(value[0], BaseMessage):
            return f"{len(value)} messages"
        return repr(value)
    if isinstance(value, str) and len(value) > max_len:
        return f"'{value[:max_len]}...'"
    return repr(value)


def _format_messages_detail(messages: list, indent: str = "    ") -> str:
    """메시지 리스트를 상세 포맷으로 변환한다."""
    if not messages:
        return f"{indent}(empty)"
    lines: list[str] = []
    for i, msg in enumerate(messages):
        if isinstance(msg, BaseMessage):
            lines.append(f"{indent}[{i}] {_summarize_message(msg)}")
        else:
            lines.append(f"{indent}[{i}] {repr(msg)}")
    return "\n".join(lines)


def format_state_pretty(state: dict) -> str:
    """상태를 구조화된 포맷으로 출력한다.

    Args:
        state: 출력할 상태 dict

    Returns:
        구조화된 문자열
    """
    lines: list[str] = []
    for key, value in state.items():
        if key == "messages" and isinstance(value, list):
            lines.append(f"  {key}: {len(value)} messages")
            lines.append(_format_messages_detail(value))
        elif isinstance(value, list):
            lines.append(f"  {key}: {repr(value)}")
        else:
            lines.append(f"  {key}: {_format_value(value)}")
    return "\n".join(lines)


def format_changes(before: dict, after: dict) -> str:
    """두 상태를 비교하여 변경된 필드와 변경 내용을 구조적으로 출력한다.

    Args:
        before: 노드 실행 전 상태
        after: 노드가 반환한 업데이트

    Returns:
        변경 사항을 설명하는 구조화된 문자열
    """
    lines: list[str] = []
    changed_keys: list[str] = []

    for key, new_value in after.items():
        old_value = before.get(key)

        # messages 필드
        if key == "messages" and isinstance(new_value, list):
            added = [m for m in new_value if isinstance(m, BaseMessage)]
            if added:
                changed_keys.append(key)
                lines.append(f"  {key}:")
                for msg in added:
                    lines.append(f"    + {_summarize_message(msg)}")
            continue

        # list 필드
        if isinstance(new_value, list) and isinstance(old_value, list):
            added = [item for item in new_value if item not in old_value]
            removed = [item for item in old_value if item not in new_value]
            if added or removed:
                changed_keys.append(key)
                lines.append(f"  {key}:")
                lines.append(f"    was: {repr(old_value)}")
                lines.append(f"    now: {repr(new_value)}")
            continue

        # 일반 필드
        if old_value != new_value:
            changed_keys.append(key)
            lines.append(f"  {key}:")
            lines.append(f"    was: {_format_value(old_value)}")
            lines.append(f"    now: {_format_value(new_value)}")

    if not changed_keys:
        return "  (no changes)"

    header = f"  changed fields: [{', '.join(changed_keys)}]"
    return header + "\n" + "\n".join(lines)
