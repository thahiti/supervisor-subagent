from langchain_core.messages import AIMessage, HumanMessage

from src.cli.commands import handle_command, is_command


SAMPLE = {
    "math": ["3+7에 5 곱하기"],
    "sql": ["직원 수를 알려줘", "이번 달 매출은?"],
}


def test_is_command_recognizes_slash() -> None:
    assert is_command("/exit")
    assert is_command("/list math")
    assert not is_command("normal query")
    assert not is_command("")
    assert not is_command(" /not-actually")


def test_exit_sets_should_exit() -> None:
    result = handle_command("/exit", [], SAMPLE)
    assert result.get("should_exit") is True


def test_quit_alias() -> None:
    result = handle_command("/quit", [], SAMPLE)
    assert result.get("should_exit") is True


def test_reset_clears_chat_history() -> None:
    history = [HumanMessage(content="prev"), AIMessage(content="ans")]
    result = handle_command("/reset", history, SAMPLE)
    assert result.get("chat_history") == []
    assert "reset" in result.get("output", "").lower() or result.get("output")


def test_list_all_categories() -> None:
    result = handle_command("/list", [], SAMPLE)
    out = result.get("output", "")
    assert "math" in out
    assert "sql" in out
    assert "직원 수를 알려줘" in out


def test_list_specific_category() -> None:
    result = handle_command("/list sql", [], SAMPLE)
    out = result.get("output", "")
    assert "직원 수를 알려줘" in out
    assert "3+7에 5 곱하기" not in out


def test_list_unknown_category() -> None:
    result = handle_command("/list unknown", [], SAMPLE)
    assert "unknown" in result.get("output", "").lower()


def test_help_lists_commands() -> None:
    result = handle_command("/help", [], SAMPLE)
    out = result.get("output", "")
    for cmd in ("/exit", "/reset", "/list", "/help"):
        assert cmd in out


def test_unknown_command_returns_hint() -> None:
    result = handle_command("/nope", [], SAMPLE)
    assert "/help" in result.get("output", "")
    assert result.get("should_exit") is None or result.get("should_exit") is False
