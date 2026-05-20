"""load_examples (YAML 로더) 단위 테스트.

YAML → list[EvalCase] 변환 로직만 본다. run_eval/CLI 통합은 별도.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from scripts.eval import load_examples


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "examples.yml"
    path.write_text(body, encoding="utf-8")
    return path


class TestQueryAndHistory:
    def test_query_only(self, tmp_path: Path) -> None:
        path = _write(tmp_path, """
- id: alpha
  description: alpha case
  input:
    query: 오늘 매출 알려줘
  expected:
    next_node: math_agent
""")
        cases = load_examples(path)
        assert len(cases) == 1
        assert cases[0]["id"] == "alpha"
        assert cases[0]["description"] == "alpha case"
        assert cases[0]["input"]["query"] == "오늘 매출 알려줘"
        assert "chat_history" not in cases[0]["input"]

    def test_chat_history_converts_to_basemessage(self, tmp_path: Path) -> None:
        path = _write(tmp_path, """
- id: beta
  description: with history
  input:
    query: 이거 일본어로도
    chat_history:
      - role: human
        content: Hello를 한국어로 번역
      - role: ai
        content: 안녕하세요
  expected:
    next_node: translate_agent
""")
        cases = load_examples(path)
        history = cases[0]["input"]["chat_history"]
        assert len(history) == 2
        assert isinstance(history[0], HumanMessage)
        assert history[0].content == "Hello를 한국어로 번역"
        assert isinstance(history[1], AIMessage)
        assert history[1].content == "안녕하세요"

    def test_unknown_role_raises(self, tmp_path: Path) -> None:
        path = _write(tmp_path, """
- id: bad
  description: bad role
  input:
    query: x
    chat_history:
      - role: system
        content: not supported
  expected: {}
""")
        with pytest.raises(ValueError, match="role"):
            load_examples(path)


class TestRegexTags:
    def test_regex_tag_produces_pattern(self, tmp_path: Path) -> None:
        path = _write(tmp_path, """
- id: r1
  description: regex single
  input:
    query: x
  expected:
    rewritten: !regex "2026-04-29"
""")
        expected = load_examples(tmp_path / "examples.yml")[0]["expected"]
        rewritten = expected["rewritten"]
        assert isinstance(rewritten, re.Pattern)
        assert rewritten.search("오늘은 2026-04-29입니다") is not None

    def test_regex_all_tag_produces_pattern_list(self, tmp_path: Path) -> None:
        path = _write(tmp_path, """
- id: r2
  description: regex AND
  input:
    query: x
  expected:
    rewritten: !regex_all ["2026-04-20", "2026-04-26"]
""")
        expected = load_examples(path)[0]["expected"]
        patterns = expected["rewritten"]
        assert isinstance(patterns, list)
        assert all(isinstance(p, re.Pattern) for p in patterns)
        assert len(patterns) == 2

    def test_plain_scalar_is_equality(self, tmp_path: Path) -> None:
        path = _write(tmp_path, """
- id: eq
  description: equality
  input:
    query: x
  expected:
    next_node: math_agent
""")
        expected = load_examples(path)[0]["expected"]
        assert expected["next_node"] == "math_agent"
        assert not isinstance(expected["next_node"], re.Pattern)


class TestFileHandling:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_examples(tmp_path / "nonexistent.yml")

    def test_empty_file_returns_empty_list(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "")
        assert load_examples(path) == []
