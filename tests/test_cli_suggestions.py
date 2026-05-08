from pathlib import Path

import pytest

from src.cli.suggestions import flatten, load_suggestions


def test_load_suggestions_basic(tmp_path: Path) -> None:
    f = tmp_path / "suggestions.yaml"
    f.write_text(
        "math:\n"
        "  - \"3+7에 5 곱하기\"\n"
        "  - \"100을 3으로 나눠줘\"\n"
        "translate:\n"
        "  - \"Hello를 한국어로\"\n",
        encoding="utf-8",
    )

    result = load_suggestions(f)

    assert result == {
        "math": ["3+7에 5 곱하기", "100을 3으로 나눠줘"],
        "translate": ["Hello를 한국어로"],
    }


def test_load_suggestions_missing_file(tmp_path: Path) -> None:
    result = load_suggestions(tmp_path / "does_not_exist.yaml")
    assert result == {}


def test_load_suggestions_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.yaml"
    f.write_text("", encoding="utf-8")
    assert load_suggestions(f) == {}


def test_load_suggestions_invalid_root_type(tmp_path: Path) -> None:
    f = tmp_path / "bad.yaml"
    f.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dict"):
        load_suggestions(f)


def test_flatten_preserves_order_and_meta() -> None:
    src = {
        "math": ["a", "b"],
        "translate": ["c"],
    }
    flat, meta = flatten(src)
    assert flat == ["a", "b", "c"]
    assert meta == {"a": "math", "b": "math", "c": "translate"}


def test_load_suggestions_skips_non_list_category(tmp_path: Path, caplog) -> None:
    f = tmp_path / "mixed.yaml"
    f.write_text(
        "math:\n"
        "  - \"3+5\"\n"
        "broken: not_a_list\n",
        encoding="utf-8",
    )

    with caplog.at_level("WARNING", logger="supervisor_subagent.cli.suggestions"):
        result = load_suggestions(f)

    assert result == {"math": ["3+5"]}
    assert any("broken" in rec.message for rec in caplog.records)
