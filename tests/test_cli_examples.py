"""CLI example helper 단위 테스트.

``scripts.cli._common.resolve_example`` / ``print_examples``의 동작을
검증한다. 데이터(``_examples.py``) 자체가 아니라 헬퍼 로직을 본다.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from scripts.cli._common import print_examples, resolve_example, to_messages
from scripts.eval import EvalCase


FIXTURES: list[EvalCase] = [
    {
        "id": "alpha",
        "description": "alpha case",
        "input": {"messages": [HumanMessage(content="alpha query")]},
        "expected": {},
    },
    {
        "id": "beta:with-history",
        "description": "beta with history",
        "input": {
            "messages": [HumanMessage(content="beta query")],
            "chat_history": to_messages([
                ("human", "earlier user"),
                ("ai", "earlier ai"),
            ]),
        },
        "expected": {},
    },
]


class TestResolveExample:
    def test_resolve_by_id(self) -> None:
        assert resolve_example(FIXTURES, "alpha") is FIXTURES[0]

    def test_resolve_by_integer_string(self) -> None:
        assert resolve_example(FIXTURES, "1") is FIXTURES[1]

    def test_resolve_by_negative_index_rejected(self) -> None:
        with pytest.raises(SystemExit):
            resolve_example(FIXTURES, "-1")

    def test_resolve_out_of_range_index(self) -> None:
        with pytest.raises(SystemExit):
            resolve_example(FIXTURES, "9")

    def test_resolve_unknown_id_exits_with_available_ids(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            resolve_example(FIXTURES, "nonexistent")
        err = capsys.readouterr().err
        assert "nonexistent" in err
        assert "alpha" in err
        assert "beta:with-history" in err

    def test_resolve_id_that_looks_like_int_prefers_id(self) -> None:
        examples: list[EvalCase] = [
            {"id": "0", "description": "zero", "input": {"messages": []}, "expected": {}},
            {"id": "other", "description": "other", "input": {"messages": []}, "expected": {}},
        ]
        # "0"은 id로 등록된 경우 id 매칭이 우선 (혼동 방지)
        assert resolve_example(examples, "0") is examples[0]


class TestPrintExamples:
    def test_print_lists_index_id_description(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_examples(FIXTURES)
        out = capsys.readouterr().out
        assert "[00]" in out
        assert "[01]" in out
        assert "alpha" in out
        assert "alpha case" in out
        assert "beta:with-history" in out

    def test_print_includes_query_for_each(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_examples(FIXTURES)
        out = capsys.readouterr().out
        assert "alpha query" in out
        assert "beta query" in out

    def test_print_includes_history_when_present(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_examples(FIXTURES)
        out = capsys.readouterr().out
        assert "earlier user" in out
        assert "earlier ai" in out

    def test_print_omits_history_line_when_absent(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        only_first: list[EvalCase] = [FIXTURES[0]]
        print_examples(only_first)
        out = capsys.readouterr().out
        assert "history" not in out.lower()
