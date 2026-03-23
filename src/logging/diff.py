from typing import Any

from langchain_core.messages import BaseMessage


def _summarize_message(msg: BaseMessage, max_len: int = 100) -> str:
    """메시지를 요약 문자열로 변환한다."""
    content = str(msg.content)[:max_len]
    msg_type = type(msg).__name__
    tool_calls = getattr(msg, "tool_calls", None)
    suffix = f", tool_calls={len(tool_calls)}" if tool_calls else ""
    return f"{msg_type}: '{content}'{suffix}"


def _format_value(value: Any, max_len: int = 100) -> str:
    """값을 로그용 문자열로 포맷한다."""
    if isinstance(value, list):
        if value and isinstance(value[0], BaseMessage):
            return f"{len(value)} messages"
        return repr(value)
    if isinstance(value, str) and len(value) > max_len:
        return f"'{value[:max_len]}...'"
    return repr(value)


def format_state(state: dict) -> str:
    """상태를 로그용 문자열로 포맷한다."""
    lines: list[str] = []
    for key, value in state.items():
        lines.append(f"  {key}: {_format_value(value)}")
    return "\n".join(lines)


def compute_diff(before: dict, after: dict) -> str:
    """두 상태의 차이를 계산하여 문자열로 반환한다.

    Args:
        before: 노드 실행 전 상태
        after: 노드가 반환한 업데이트

    Returns:
        변경 사항을 설명하는 문자열
    """
    lines: list[str] = []
    for key, new_value in after.items():
        old_value = before.get(key)

        # messages 필드: 추가된 메시지 요약
        if key == "messages" and isinstance(new_value, list):
            added = [m for m in new_value if isinstance(m, BaseMessage)]
            summaries = [_summarize_message(m) for m in added]
            lines.append(f"  messages: +{len(added)} ({', '.join(summaries)})")
            continue

        # list 필드: 추가/제거 항목 표시
        if isinstance(new_value, list) and isinstance(old_value, list):
            added = [item for item in new_value if item not in old_value]
            removed = [item for item in old_value if item not in new_value]
            if added or removed:
                parts: list[str] = []
                if added:
                    parts.append(f"+{added}")
                if removed:
                    parts.append(f"-{removed}")
                lines.append(f"  {key}: {', '.join(parts)}")
            continue

        # 일반 필드: 값 변경
        if old_value != new_value:
            lines.append(
                f"  {key}: {_format_value(old_value)} → {_format_value(new_value)}"
            )

    if not lines:
        return "  (no changes)"
    return "\n".join(lines)
