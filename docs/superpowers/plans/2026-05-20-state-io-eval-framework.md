# State-IO Workflows and Shared Eval Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the two CLI workflow functions (`rewrite`, `route_trace`) to a uniform state-IO shape (`CliState -> CliState`), and refactor both smokes to share one declarative eval framework (`scripts/eval.py`) — cases are pure data, the runner handles execution and assertions.

**Architecture:** `scripts/cli/_common.py` gains a `CliState(State)` TypedDict subtype with `NotRequired` fields (`rewritten`, `next_node`). Each CLI module owns its workflow function in state-IO form (strict isolation — no cross-CLI imports). A new `scripts/eval.py` provides `EvalCase` + `run_eval(cases, workflow, *, now, max_retries)`; both smokes shrink to inline `CASES` data and a single `run_eval(...)` call. The spec at `docs/superpowers/specs/2026-05-20-state-io-eval-framework-design.md` is the source of truth for component shapes and op inference rules.

**Tech Stack:** Python 3.11+, `typing.NotRequired`/`TypedDict`, langchain-core messages, langgraph `add_messages`, `unittest.mock`, pytest. No new dependencies.

---

## File Structure

- **Modify `scripts/cli/_common.py`** — add `CliState(State)` with `rewritten`/`next_node` `NotRequired[str]` fields. One responsibility: CLI-tier shared types and utilities.
- **Modify `scripts/cli/query_rewriter.py`** — change `rewrite(query, chat_history) -> str` to `rewrite(state: CliState) -> CliState`. Update `main()` to construct initial state and unpack the result. Owns the rewrite workflow.
- **Modify `scripts/cli/query_rewriter_router.py`** — change `route_trace(query, chat_history) -> tuple[str, str]` to `route_trace(state: CliState) -> CliState`. Update `main()`. Owns the route+trace workflow; rewrite step stays inline (strict isolation).
- **Modify `tests/test_route_eval.py`** — update existing tests (`TestRewrite`, `TestRouteTrace`, CLI tests) for the new state-IO signatures. Add new test classes for `scripts/eval.py` (`TestRunEval`, `TestAssertion`) in Task 2.
- **Modify `scripts/smoke_query_rewriter.py`** — interim (Task 1): inline state construction; final (Task 3): `CASES: list[EvalCase]` + `run_eval(CASES, rewrite, now=..., max_retries=3)`.
- **Modify `scripts/smoke_query_rewriter_router.py`** — interim (Task 1): inline state construction; final (Task 3): `CASES: list[EvalCase]` + `run_eval(CASES, route_trace)`.
- **Create `scripts/eval.py`** (Task 2) — owns `EvalCase` TypedDict, `run_eval`, op-inference logic, and the per-case output formatter. Imports nothing from workflows — workflow-agnostic by design.

Three atomic commits (the spec proposed two; we split the eval phase into "framework" + "smoke refactor" so each commit stays under ~200 lines and is independently reviewable):

1. Task 1 → `refactor(cli-state): state-IO workflows + CliState`
2. Task 2 → `feat(scripts/eval): add shared eval framework`
3. Task 3 → `refactor(route-smoke): use run_eval framework`

---

### Task 1: Convert workflows to state-IO with `CliState`

**Files:**
- Modify: `scripts/cli/_common.py`
- Modify: `scripts/cli/query_rewriter.py`
- Modify: `scripts/cli/query_rewriter_router.py`
- Modify: `tests/test_route_eval.py`
- Modify: `scripts/smoke_query_rewriter.py`
- Modify: `scripts/smoke_query_rewriter_router.py`

- [ ] **Step 1: Update `tests/test_route_eval.py` for state-IO (failing tests)**

Replace the `TestRewrite`, `TestRouteTrace`, `TestQueryRewriterCli`, `TestQueryRewriterRouterCli` classes with the versions below. Keep `TestToMessages` and `TestCliCommon` unchanged.

```python
# Replace the existing TestRewrite class with:
class TestRewrite:
    @patch("scripts.cli.query_rewriter.query_rewriter_node")
    def test_returns_state_with_rewritten_field(self, mock_rw: MagicMock) -> None:
        mock_rw.return_value = {"messages": [HumanMessage(content="확장된 질의")]}
        state: CliState = {
            "messages": [HumanMessage(content="원본")],
            "next_agent": "",
            "chat_history": [],
        }
        result = rewrite(state)
        assert result["rewritten"] == "확장된 질의"
        # 원본 messages + 리라이팅 메시지가 모두 누적
        contents = [m.content for m in result["messages"] if isinstance(m, HumanMessage)]
        assert "원본" in contents and "확장된 질의" in contents

    @patch("scripts.cli.query_rewriter.query_rewriter_node")
    def test_falls_back_to_original_when_no_change(self, mock_rw: MagicMock) -> None:
        mock_rw.return_value = {"messages": []}
        state: CliState = {
            "messages": [HumanMessage(content="원본")],
            "next_agent": "",
            "chat_history": [],
        }
        result = rewrite(state)
        assert result["rewritten"] == "원본"


# Replace the existing TestRouteTrace class with:
class TestRouteTrace:
    @patch("scripts.cli.query_rewriter_router.router_conditional")
    @patch("scripts.cli.query_rewriter_router.router_node")
    @patch("scripts.cli.query_rewriter_router.query_rewriter_node")
    def test_returns_state_with_rewritten_and_next_node(
        self, mock_rw: MagicMock, mock_router: MagicMock, mock_cond: MagicMock
    ) -> None:
        mock_rw.return_value = {"messages": [HumanMessage(content="확장된 질의")]}
        mock_router.return_value = {
            "messages": [AIMessage(content='{"next": "math"}')],
            "next_agent": "math",
        }
        mock_cond.return_value = "math_agent"

        state: CliState = {
            "messages": [HumanMessage(content="3 더하기 4")],
            "next_agent": "",
            "chat_history": [AIMessage(content="prev")],
        }
        result = route_trace(state)

        assert result["rewritten"] == "확장된 질의"
        assert result["next_agent"] == "math"
        assert result["next_node"] == "math_agent"
        # router_node가 받은 state에는 원본+리라이팅 메시지가 둘 다 누적되어 있어야 함
        router_state = mock_router.call_args[0][0]
        contents = [m.content for m in router_state["messages"] if isinstance(m, HumanMessage)]
        assert "3 더하기 4" in contents and "확장된 질의" in contents
        assert mock_cond.call_args[0][0]["next_agent"] == "math"


# Replace the existing TestQueryRewriterCli class with:
class TestQueryRewriterCli:
    @patch("scripts.cli.query_rewriter.rewrite")
    def test_prints_query_and_rewritten(
        self, mock_rw: MagicMock, capsys, monkeypatch
    ) -> None:
        import scripts.cli.query_rewriter as cli

        mock_rw.return_value = {
            "messages": [HumanMessage(content="지난주(2026-04-20~2026-04-26) 매출 알려줘")],
            "next_agent": "",
            "chat_history": [],
            "rewritten": "지난주(2026-04-20~2026-04-26) 매출 알려줘",
        }
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "지난주", "매출", "알려줘", "--now", "2026-04-29T14:30"],
        )
        try:
            cli.main()
        except SystemExit as e:
            assert e.code == 0
        out = capsys.readouterr().out
        assert "query    : 지난주 매출 알려줘" in out
        assert "rewritten: 지난주(2026-04-20~2026-04-26) 매출 알려줘" in out


# Replace the existing TestQueryRewriterRouterCli class with:
class TestQueryRewriterRouterCli:
    @patch("scripts.cli.query_rewriter_router.route_trace")
    def test_prints_query_rewritten_destination(
        self, mock_rt: MagicMock, capsys, monkeypatch
    ) -> None:
        import scripts.cli.query_rewriter_router as cli

        mock_rt.return_value = {
            "messages": [HumanMessage(content="공장2의 제품 재고를 조사해줘")],
            "next_agent": "tool_call",
            "chat_history": [],
            "rewritten": "공장2의 제품 재고를 조사해줘",
            "next_node": "tool_call_agent",
        }
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "공장2",
                "--history",
                '[{"role":"human","content":"재고 조사"},'
                '{"role":"ai","content":"어떤 브랜치?"}]',
            ],
        )
        try:
            cli.main()
        except SystemExit as e:
            assert e.code == 0
        out = capsys.readouterr().out
        assert "query      : 공장2" in out
        assert "rewritten  : 공장2의 제품 재고를 조사해줘" in out
        assert "destination: tool_call_agent" in out
```

Also update the top-of-file imports to add `CliState`:

```python
# Replace the existing imports near the top with:
from scripts.cli._common import (
    CliState,
    add_common_args,
    parse_history,
    patched_now,
    to_messages,
)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_route_eval.py -v`
Expected: FAIL with `ImportError: cannot import name 'CliState' from 'scripts.cli._common'` (and follow-on failures on the new tests).

- [ ] **Step 3: Add `CliState` to `scripts/cli/_common.py`**

Add this near the top of the file (after the `from langchain_core.messages import ...` line, before `Role = Literal["human", "ai"]`):

```python
from typing import NotRequired

from src.state import State


class CliState(State):
    """CLI 워크플로우(rewrite, route_trace)의 state-IO 타입.

    프로덕션 ``src.state.State``를 확장한다. 입력 단계에는 ``rewritten``과
    ``next_node``가 없을 수 있고, 워크플로우가 출력 state를 만들 때
    채워진다.
    """

    rewritten: NotRequired[str]
    next_node: NotRequired[str]
```

Also adjust the file's existing `from typing import Iterator, Literal, cast` import to remove the redundant import or merge — the simplest is to leave the existing import alone and add the new line `from typing import NotRequired` (Python tolerates two `from typing import …` lines fine).

- [ ] **Step 4: Convert `rewrite()` to state-IO in `scripts/cli/query_rewriter.py`**

Replace the existing `rewrite` function and update `main()` to match. The full new file content:

```python
"""query_rewriter 단독 실행 CLI.

이 모듈은 리라이팅 워크플로우(`rewrite`)를 직접 소유한다. 스모크 등
다른 호출자는 `from scripts.cli.query_rewriter import rewrite`로
in-process로 호출해 결과 state를 검증할 수 있다.

실행:
    uv run python -m scripts.cli.query_rewriter 지난주 매출 알려줘 --now 2026-04-29T14:30
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph.message import add_messages

from scripts.cli._common import (
    CliState,
    add_common_args,
    last_human_text,
    parse_history,
    patched_now,
)
from src.query_rewriter.rewriter import query_rewriter_node


def rewrite(state: CliState) -> CliState:
    """query_rewriter_node를 실행하고 리라이팅 텍스트를 채운 새 state를 반환한다.

    ``state["messages"]``의 마지막 HumanMessage를 현재 query로 보고,
    리라이팅 결과 메시지를 messages에 누적한 뒤 ``rewritten`` 필드에
    리라이팅 텍스트를 채워 반환한다. 리라이팅이 일어나지 않으면
    원본 query 텍스트가 그대로 담긴다.

    Args:
        state: 입력 ``CliState``. ``messages``에 적어도 하나의 HumanMessage가
            있어야 한다 (없으면 ``rewritten`` = "").

    Returns:
        ``messages``가 누적되고 ``rewritten``이 채워진 새 ``CliState``.
    """
    rw = query_rewriter_node(state)
    merged = add_messages(state["messages"], rw["messages"])
    rewritten_text = last_human_text(merged, "")
    return {**state, "messages": merged, "rewritten": rewritten_text}


def main() -> None:
    """리라이터를 1회 실행하고 결과를 출력한다."""
    load_dotenv()

    parser = argparse.ArgumentParser(description="query_rewriter 단독 실행")
    add_common_args(parser)
    args = parser.parse_args()

    query = " ".join(args.query)
    history = parse_history(args.history)

    initial: CliState = {
        "messages": [HumanMessage(content=query)],
        "next_agent": "",
        "chat_history": history,
    }

    with patched_now(args.now):
        result = rewrite(initial)

    print(f"query    : {query}")
    print(f"rewritten: {result.get('rewritten', '')}")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Convert `route_trace()` to state-IO in `scripts/cli/query_rewriter_router.py`**

Replace the existing `route_trace` and update `main()`. The full new file content:

```python
"""query_rewriter + router 실행 CLI.

이 모듈은 라우팅 워크플로우(`route_trace`)를 직접 소유한다.
리라이팅 단계는 `scripts.cli.query_rewriter`에 의존하지 않고 이 모듈
안에서 독립적으로 수행한다 (cross-CLI import 없음).

스모크 등 다른 호출자는 `from scripts.cli.query_rewriter_router import
route_trace`로 in-process 호출해 결과 state를 직접 검증할 수 있다.

실행:
    uv run python -m scripts.cli.query_rewriter_router 3 곱하기 7
    uv run python -m scripts.cli.query_rewriter_router 공장2 \\
        --history '[{"role":"human","content":"재고 조사"},{"role":"ai","content":"어떤 브랜치?"}]'
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph.message import add_messages

import src  # noqa: F401  registry 등록 (router_conditional이 의존)
from scripts.cli._common import (
    CliState,
    add_common_args,
    last_human_text,
    parse_history,
    patched_now,
)
from src.query_rewriter.rewriter import query_rewriter_node
from src.router import router_conditional, router_node


def route_trace(state: CliState) -> CliState:
    """query_rewriter → router를 연쇄 실행하고 모든 결과 필드를 채운 새
    ``CliState``를 반환한다.

    리라이팅 단계는 query_rewriter 모듈에 의존하지 않고 이 함수 안에서
    독립적으로 수행한다 (strict isolation; cross-CLI import 없음).
    결과 state에는 ``rewritten``, ``next_agent``, ``next_node``가 모두
    채워진다.

    Args:
        state: 입력 ``CliState``.

    Returns:
        ``messages``가 누적되고 ``rewritten``/``next_agent``/``next_node``가
        모두 채워진 새 ``CliState``.
    """
    rw = query_rewriter_node(state)
    msgs_after_rewrite = add_messages(state["messages"], rw["messages"])
    rewritten_text = last_human_text(msgs_after_rewrite, "")

    state_for_router: CliState = {**state, "messages": msgs_after_rewrite}
    rt = router_node(state_for_router)
    msgs_after_router = add_messages(msgs_after_rewrite, rt["messages"])

    after_router: CliState = {
        **state,
        "messages": msgs_after_router,
        "next_agent": rt["next_agent"],
        "rewritten": rewritten_text,
    }
    return {**after_router, "next_node": router_conditional(after_router)}


def main() -> None:
    """리라이터 → 라우터를 연쇄 실행하고 결과를 출력한다."""
    load_dotenv()

    parser = argparse.ArgumentParser(description="query_rewriter + router 실행")
    add_common_args(parser)
    args = parser.parse_args()

    query = " ".join(args.query)
    history = parse_history(args.history)

    initial: CliState = {
        "messages": [HumanMessage(content=query)],
        "next_agent": "",
        "chat_history": history,
    }

    with patched_now(args.now):
        result = route_trace(initial)

    print(f"query      : {query}")
    print(f"rewritten  : {result.get('rewritten', '')}")
    print(f"destination: {result.get('next_node', '')}")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Update both smokes to inline state-IO (interim, no eval framework yet)**

For `scripts/smoke_query_rewriter.py`, change the inner loop so each case constructs a `CliState`, calls `rewrite(state)`, and reads `result["rewritten"]`. Full new content of `run()`:

```python
def run() -> int:
    """모든 케이스를 in-process로 실행하고 PASS/FAIL을 출력한다."""
    from langchain_core.messages import HumanMessage

    print(f"기준 시각 (FIXED_NOW): {FIXED_NOW}")
    print(f"테스트 케이스: {len(CASES)}건\n")

    pass_count = 0
    for idx, case in enumerate(CASES, start=1):
        history = to_messages(list(case.get("history", [])))
        initial: CliState = {
            "messages": [HumanMessage(content=case["input"])],
            "next_agent": "",
            "chat_history": history,
        }

        rewritten = ""
        missing: list[str] = []
        passed = False
        error: str | None = None
        attempts = 0
        for attempt in range(1, MAX_RETRIES + 1):
            attempts = attempt
            try:
                with patched_now(FIXED_NOW):
                    result = rewrite(initial)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                break
            rewritten = result.get("rewritten", "")
            missing = [
                p for p in case["expected_patterns"] if not re.search(p, rewritten)
            ]
            passed = not missing
            if passed:
                break

        if passed:
            pass_count += 1
        status = "PASS" if passed else "FAIL"
        note = f" (attempts={attempts})" if attempts > 1 else ""
        print(f"[{idx:02d}] [{status}] {case['category']}{note}")
        print(f"     입력  : {case['input']}")
        print(f"     출력  : {rewritten}")
        print(f"     기대  : {case['expected_patterns']}")
        if missing:
            print(f"     누락  : {missing}")
        if error is not None:
            print(f"     에러  : {error}")
        print()

    total = len(CASES)
    print(f"결과: {pass_count}/{total} 통과")
    return 0 if pass_count == total else 1
```

Update the imports near the top of `scripts/smoke_query_rewriter.py`:

```python
from scripts.cli._common import CliState, Role, patched_now, to_messages  # noqa: E402
from scripts.cli.query_rewriter import rewrite  # noqa: E402
```

For `scripts/smoke_query_rewriter_router.py`, change `run()` similarly:

```python
def run() -> int:
    """모든 케이스를 in-process로 실행하고 PASS/FAIL을 출력한다."""
    from langchain_core.messages import HumanMessage

    pass_count = 0
    for idx, case in enumerate(CASES, start=1):
        history = to_messages(case["history"])
        initial: CliState = {
            "messages": [HumanMessage(content=case["query"])],
            "next_agent": "",
            "chat_history": history,
        }

        rewritten = ""
        actual = ""
        error: str | None = None
        try:
            result = route_trace(initial)
            rewritten = result.get("rewritten", "")
            actual = result.get("next_node", "")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        passed = error is None and actual == case["expected"]
        if passed:
            pass_count += 1

        status = "PASS" if passed else "FAIL"
        print(f"[{idx:02d}] [{status}] {case['id']}")
        print(f"     query    : {case['query']}")
        print(f"     rewritten: {rewritten}")
        print(f"     expected : {case['expected']}")
        print(f"     actual   : {actual}")
        if error is not None:
            print(f"     error    : {error}")
        print()

    total = len(CASES)
    print(f"결과: {pass_count}/{total} 통과")
    return 0 if pass_count == total else 1
```

Update the imports near the top of `scripts/smoke_query_rewriter_router.py`:

```python
from scripts.cli._common import CliState, Role, to_messages  # noqa: E402
from scripts.cli.query_rewriter_router import route_trace  # noqa: E402
```

- [ ] **Step 7: Run tests to verify pass**

Run: `uv run pytest tests/test_route_eval.py -v`
Expected: PASS (12 tests; same as before — `TestRewrite` x2, `TestRouteTrace` x1, `TestToMessages` x2, `TestCliCommon` x5, `TestQueryRewriterCli` x1, `TestQueryRewriterRouterCli` x1).

Then run the full suite: `uv run pytest -q`
Expected: 211 passed.

- [ ] **Step 8: Commit**

```bash
git add scripts/cli/_common.py scripts/cli/query_rewriter.py scripts/cli/query_rewriter_router.py \
        scripts/smoke_query_rewriter.py scripts/smoke_query_rewriter_router.py \
        tests/test_route_eval.py
git commit -m "refactor(cli-state): convert workflows to state-IO with CliState

scripts/cli/_common.py에 CliState(State) 추가 (rewritten, next_node 필드).
rewrite와 route_trace를 (CliState) -> CliState 시그니쳐로 변환하고
CLI main()과 두 스모크의 inline 로직을 새 state-IO 인터페이스에 맞춰
조정한다. 다음 커밋의 공통 평가 프레임워크 도입을 위한 준비.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Add shared eval framework (`scripts/eval.py`)

**Files:**
- Create: `scripts/eval.py`
- Modify: `tests/test_route_eval.py` (append new test classes)

- [ ] **Step 1: Write failing tests for `EvalCase` + `run_eval`**

Append the following imports and test classes at the end of `tests/test_route_eval.py`:

```python
import re

from scripts.eval import EvalCase, run_eval


class TestRunEvalAssertions:
    """op 추론 (str=eq, Pattern=regex, list[Pattern]=AND) 검증."""

    @staticmethod
    def _id_workflow(state: CliState) -> CliState:
        """입력 state를 그대로 반환하는 항등 워크플로우 (어션만 검증할 때 사용)."""
        return state

    def test_eq_match_passes(self, capsys) -> None:
        cases: list[EvalCase] = [
            {
                "id": "eq-pass",
                "description": "eq pass",
                "input": {"next_agent": "math"},
                "expected": {"next_agent": "math"},
            }
        ]
        assert run_eval(cases, self._id_workflow) == 0
        assert "1/1 통과" in capsys.readouterr().out

    def test_eq_mismatch_fails(self, capsys) -> None:
        cases: list[EvalCase] = [
            {
                "id": "eq-fail",
                "description": "eq fail",
                "input": {"next_agent": "math"},
                "expected": {"next_agent": "sql"},
            }
        ]
        assert run_eval(cases, self._id_workflow) == 1
        out = capsys.readouterr().out
        assert "FAIL" in out and "0/1 통과" in out

    def test_regex_pattern_matches(self, capsys) -> None:
        cases: list[EvalCase] = [
            {
                "id": "regex-pass",
                "description": "regex pass",
                "input": {"rewritten": "2026-04-29 매출 알려줘"},
                "expected": {"rewritten": re.compile(r"2026-04-29")},
            }
        ]
        assert run_eval(cases, self._id_workflow) == 0

    def test_list_of_patterns_requires_all(self, capsys) -> None:
        # 둘 다 매치 → PASS
        ok: list[EvalCase] = [
            {
                "id": "and-pass",
                "description": "and pass",
                "input": {"rewritten": "2026-04-20부터 2026-04-26"},
                "expected": {
                    "rewritten": [re.compile(r"2026-04-20"), re.compile(r"2026-04-26")],
                },
            }
        ]
        assert run_eval(ok, self._id_workflow) == 0
        capsys.readouterr()  # drain

        # 둘 중 하나라도 빠지면 FAIL
        fail: list[EvalCase] = [
            {
                "id": "and-fail",
                "description": "and fail",
                "input": {"rewritten": "2026-04-20만 있음"},
                "expected": {
                    "rewritten": [re.compile(r"2026-04-20"), re.compile(r"2026-04-26")],
                },
            }
        ]
        assert run_eval(fail, self._id_workflow) == 1

    def test_missing_field_fails(self, capsys) -> None:
        cases: list[EvalCase] = [
            {
                "id": "missing",
                "description": "missing",
                "input": {},
                "expected": {"next_node": "math_agent"},
            }
        ]
        assert run_eval(cases, self._id_workflow) == 1
        assert "<missing>" in capsys.readouterr().out


class TestRunEvalRetry:
    def test_retry_succeeds_on_second_attempt(self, capsys) -> None:
        attempt_count = {"n": 0}

        def flaky(state: CliState) -> CliState:
            attempt_count["n"] += 1
            return {**state, "rewritten": "ok" if attempt_count["n"] >= 2 else "no"}

        cases: list[EvalCase] = [
            {
                "id": "flaky",
                "description": "flaky",
                "input": {},
                "expected": {"rewritten": "ok"},
            }
        ]
        assert run_eval(cases, flaky, max_retries=3) == 0
        out = capsys.readouterr().out
        assert "PASS" in out and "attempts=2" in out

    def test_exception_does_not_retry(self, capsys) -> None:
        attempt_count = {"n": 0}

        def boom(state: CliState) -> CliState:
            attempt_count["n"] += 1
            raise RuntimeError("boom")

        cases: list[EvalCase] = [
            {
                "id": "boom",
                "description": "boom",
                "input": {},
                "expected": {"rewritten": "ok"},
            }
        ]
        assert run_eval(cases, boom, max_retries=3) == 1
        assert attempt_count["n"] == 1
        out = capsys.readouterr().out
        assert "error" in out and "RuntimeError: boom" in out


class TestRunEvalNow:
    @staticmethod
    def _check_now_workflow(state: CliState) -> CliState:
        from datetime import datetime
        import src.query_rewriter.rewriter as rw_mod

        return {**state, "rewritten": rw_mod.datetime.now().isoformat()}

    def test_now_kwarg_applies_patched_now(self) -> None:
        cases: list[EvalCase] = [
            {
                "id": "now",
                "description": "now",
                "input": {},
                "expected": {"rewritten": "2026-04-29T14:30:00"},
            }
        ]
        assert run_eval(cases, self._check_now_workflow, now="2026-04-29T14:30") == 0


class TestRunEvalInputMerge:
    @staticmethod
    def _echo_workflow(state: CliState) -> CliState:
        return state

    def test_baseline_state_provides_empty_defaults(self) -> None:
        # input에 messages/chat_history 미설정 → baseline empty가 사용됨
        cases: list[EvalCase] = [
            {
                "id": "baseline",
                "description": "baseline",
                "input": {"next_agent": "sql"},
                "expected": {"next_agent": "sql"},
            }
        ]
        assert run_eval(cases, self._echo_workflow) == 0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_route_eval.py -v -k "RunEval"`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.eval'`.

- [ ] **Step 3: Implement `scripts/eval.py`**

Create the file with the following content:

```python
"""공통 평가 프레임워크 — 스모크들이 공유하는 케이스 실행·검증·출력.

`EvalCase` 데이터를 받아 워크플로우(`(CliState) -> CliState`)를 호출하고,
선언적 `expected` dict로 결과 state를 검증한다. 워크플로우 자체에 대해
아무것도 모른다 — 호출자가 워크플로우를 인자로 넘긴다.

op 추론 규칙:
- ``str``/``int``/``bool`` 등 plain → ``actual == value`` (정확히 같음)
- ``re.Pattern`` → ``value.search(str(actual))`` (정규식 매칭)
- ``list[re.Pattern]`` → 모든 패턴이 매치 (정규식 AND)
"""

from __future__ import annotations

import re
from typing import Any, Callable, NotRequired, TypedDict

from scripts.cli._common import CliState, patched_now


class EvalCase(TypedDict):
    """선언적 평가 케이스. 케이스는 입력 데이터와 기대 검증값만 가진다.
    실행 정책(고정 시각, 재시도 횟수)은 ``run_eval`` 인자로 받는다.
    """

    id: str
    description: str
    input: dict[str, Any]
    expected: dict[str, Any]


def _check(expected_value: Any, actual: Any) -> bool:
    """op를 ``expected_value``의 타입으로 추론하여 어션을 평가한다."""
    if isinstance(expected_value, re.Pattern):
        return expected_value.search(str(actual)) is not None
    if isinstance(expected_value, list) and all(
        isinstance(p, re.Pattern) for p in expected_value
    ):
        return all(p.search(str(actual)) is not None for p in expected_value)
    return actual == expected_value


def _build_initial_state(overrides: dict[str, Any]) -> CliState:
    """베이스라인 CliState에 ``overrides``를 머지하여 입력 state를 만든다."""
    baseline: CliState = {
        "messages": [],
        "next_agent": "",
        "chat_history": [],
    }
    return {**baseline, **overrides}


def _check_case(
    expected: dict[str, Any], result: CliState
) -> tuple[bool, dict[str, tuple[Any, Any]]]:
    """결과 state의 각 expected 필드를 검증한다.

    Returns:
        (모두 통과 여부, 실패한 필드별 (expected, actual) 매핑).
    """
    failures: dict[str, tuple[Any, Any]] = {}
    for field, expected_value in expected.items():
        actual: Any = result.get(field, _MISSING)  # type: ignore[arg-type]
        if not _check(expected_value, actual):
            failures[field] = (expected_value, actual)
    return (not failures, failures)


_MISSING = "<missing>"


def _print_case(
    idx: int,
    total: int,
    case: EvalCase,
    *,
    passed: bool,
    result: CliState | None,
    failures: dict[str, tuple[Any, Any]],
    attempts: int,
    error: str | None,
) -> None:
    """한 케이스의 결과를 출력한다."""
    status = "PASS" if passed else "FAIL"
    note = f" (attempts={attempts})" if attempts > 1 else ""
    print(f"[{idx:02d}/{total:02d}] [{status}] {case['id']} — {case['description']}{note}")
    print(f"     input    : {case['input']}")
    print(f"     expected : {case['expected']}")
    if result is not None:
        # expected에 등장한 필드만 발췌 출력
        actuals = {k: result.get(k, _MISSING) for k in case["expected"]}
        print(f"     actual   : {actuals}")
    if failures:
        print(f"     failed   : {failures}")
    if error is not None:
        print(f"     error    : {error}")
    print()


def run_eval(
    cases: list[EvalCase],
    workflow: Callable[[CliState], CliState],
    *,
    now: str = "",
    max_retries: int = 1,
) -> int:
    """각 케이스를 워크플로우에 통과시키고 expected 어션을 검증한다.

    Args:
        cases: 실행할 케이스들.
        workflow: ``(CliState) -> CliState`` 함수.
        now: 비어있지 않으면 ``patched_now(now)``로 전체 실행을 감싼다.
        max_retries: 어션 FAIL 시 케이스당 재시도 횟수 (기본 1 = 재시도 없음).
            예외는 재시도하지 않고 즉시 FAIL.

    Returns:
        모두 통과면 0, 하나라도 실패면 1.
    """
    total = len(cases)
    pass_count = 0

    with patched_now(now):
        for idx, case in enumerate(cases, start=1):
            result: CliState | None = None
            failures: dict[str, tuple[Any, Any]] = {}
            passed = False
            error: str | None = None
            attempts = 0

            for attempt in range(1, max_retries + 1):
                attempts = attempt
                try:
                    result = workflow(_build_initial_state(case["input"]))
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    break
                passed, failures = _check_case(case["expected"], result)
                if passed:
                    break

            if passed:
                pass_count += 1
            _print_case(
                idx,
                total,
                case,
                passed=passed,
                result=result,
                failures=failures,
                attempts=attempts,
                error=error,
            )

    print(f"결과: {pass_count}/{total} 통과")
    return 0 if pass_count == total else 1
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_route_eval.py -v -k "RunEval"`
Expected: PASS (9 tests across `TestRunEvalAssertions` x5, `TestRunEvalRetry` x2, `TestRunEvalNow` x1, `TestRunEvalInputMerge` x1).

Then full file: `uv run pytest tests/test_route_eval.py -v`
Expected: 21 passed (12 from Task 1 + 9 new).

Then full suite: `uv run pytest -q`
Expected: 220 passed (211 baseline + 9 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/eval.py tests/test_route_eval.py
git commit -m "feat(scripts/eval): add shared eval framework

scripts/eval.py에 EvalCase TypedDict와 run_eval(cases, workflow,
*, now, max_retries) 추가. op 추론(str=eq, Pattern=regex,
list[Pattern]=AND), 누락 필드 처리, 재시도 정책(예외는 즉시 FAIL)을
포함한다. 워크플로우-무지(workflow-agnostic) 설계로 호출자가
워크플로우를 인자로 넘긴다. 다음 커밋에서 두 스모크가 이를 사용하도록
리팩터한다.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Refactor smokes to use `run_eval`

**Files:**
- Modify: `scripts/smoke_query_rewriter.py`
- Modify: `scripts/smoke_query_rewriter_router.py`

(No new pytest tests — verified by running pytest for no regression + running smokes against real LLM.)

- [ ] **Step 1: Refactor `scripts/smoke_query_rewriter.py`**

Replace the entire file content with:

```python
"""query_rewriter 워크플로우 스모크.

`scripts.cli.query_rewriter.rewrite`를 공통 평가 프레임워크
(`scripts.eval.run_eval`)로 호출한다. FIXED_NOW로 상대 날짜 변환은
결정적이며, MAX_RETRIES로 LLM 표현 편차를 흡수한다. 실제 LLM을
호출하므로 비결정적·유료이며 의도적으로 실행한다.

실행:
    uv run python -m scripts.smoke_query_rewriter
"""

from __future__ import annotations

import re
import sys

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import HumanMessage  # noqa: E402

from scripts.cli._common import to_messages  # noqa: E402
from scripts.cli.query_rewriter import rewrite  # noqa: E402
from scripts.eval import EvalCase, run_eval  # noqa: E402

FIXED_NOW = "2026-04-29T14:30"
MAX_RETRIES = 3


CASES: list[EvalCase] = [
    {
        "id": "일:오늘",
        "description": "일:오늘",
        "input": {"messages": [HumanMessage(content="오늘 매출 알려줘")]},
        "expected": {"rewritten": re.compile(r"2026-04-29")},
    },
    {
        "id": "일:어제",
        "description": "일:어제",
        "input": {"messages": [HumanMessage(content="어제 매출 알려줘")]},
        "expected": {"rewritten": re.compile(r"2026-04-28")},
    },
    {
        "id": "주:지난주",
        "description": "주:지난주",
        "input": {"messages": [HumanMessage(content="지난주 매출 알려줘")]},
        "expected": {
            "rewritten": [re.compile(r"2026-04-20"), re.compile(r"2026-04-26")],
        },
    },
    {
        "id": "월:지난달",
        "description": "월:지난달",
        "input": {"messages": [HumanMessage(content="지난달 매출 알려줘")]},
        "expected": {
            "rewritten": [re.compile(r"2026-03-01"), re.compile(r"2026-03-31")],
        },
    },
    {
        "id": "최근:N일",
        "description": "최근:N일",
        "input": {"messages": [HumanMessage(content="최근 7일 매출 알려줘")]},
        "expected": {
            "rewritten": [re.compile(r"2026-04-22"), re.compile(r"2026-04-29")],
        },
    },
    {
        "id": "년:작년",
        "description": "년:작년",
        "input": {"messages": [HumanMessage(content="작년 매출")]},
        "expected": {
            "rewritten": [re.compile(r"2025-01-01"), re.compile(r"2025-12-31")],
        },
    },
    {
        "id": "분기:1분기",
        "description": "분기:1분기",
        "input": {"messages": [HumanMessage(content="1분기 매출")]},
        "expected": {
            "rewritten": [re.compile(r"2026-01-01"), re.compile(r"2026-03-31")],
        },
    },
    {
        "id": "자연어:N월 N일",
        "description": "자연어:N월 N일",
        "input": {"messages": [HumanMessage(content="4월 17일 매출")]},
        "expected": {"rewritten": re.compile(r"2026-04-17")},
    },
    {
        "id": "coref:번역 결과 → 이거",
        "description": "이거 → 직전 번역 결과 복원",
        "input": {
            "messages": [HumanMessage(content="이거 일본어로도 번역해줘")],
            "chat_history": to_messages([
                ("human", "Hello, how are you?를 한국어로 번역해줘"),
                ("ai", "안녕하세요, 어떻게 지내세요?"),
            ]),
        },
        "expected": {"rewritten": re.compile(r"안녕하세요|Hello")},
    },
    {
        "id": "ellipsis:동사 재사용",
        "description": "오늘은? → 직전 동사(매출) 복원 + 오늘 날짜",
        "input": {
            "messages": [HumanMessage(content="오늘은?")],
            "chat_history": to_messages([
                ("human", "어제 매출 알려줘"),
                ("ai", "2026-04-28 매출은 1억원입니다."),
            ]),
        },
        "expected": {
            "rewritten": [re.compile(r"2026-04-29"), re.compile(r"매출")],
        },
    },
    {
        "id": "독립:번역 → 수학 (오염 없음)",
        "description": "독립 질문은 chat_history 무시",
        "input": {
            "messages": [HumanMessage(content="3과 7을 더해줘")],
            "chat_history": to_messages([
                ("human", "Hello를 한국어로 번역해줘"),
                ("ai", "안녕하세요"),
            ]),
        },
        "expected": {
            "rewritten": [
                re.compile(r"3.{0,5}7|7.{0,5}3"),
                re.compile(r"더해|더하|덧셈|합"),
            ],
        },
    },
]


if __name__ == "__main__":
    sys.exit(run_eval(CASES, rewrite, now=FIXED_NOW, max_retries=MAX_RETRIES))
```

- [ ] **Step 2: Refactor `scripts/smoke_query_rewriter_router.py`**

Replace the entire file content with:

```python
"""query_rewriter + router 워크플로우 스모크.

`scripts.cli.query_rewriter_router.route_trace`를 공통 평가
프레임워크(`scripts.eval.run_eval`)로 호출한다. 실제 LLM을 호출하므로
비결정적·유료이며 의도적으로 실행한다.

실행:
    uv run python -m scripts.smoke_query_rewriter_router
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import HumanMessage  # noqa: E402

from scripts.cli._common import to_messages  # noqa: E402
from scripts.cli.query_rewriter_router import route_trace  # noqa: E402
from scripts.eval import EvalCase, run_eval  # noqa: E402


CASES: list[EvalCase] = [
    {
        "id": "single-math",
        "description": "단일턴 수학 → math_agent",
        "input": {"messages": [HumanMessage(content="3 곱하기 7은 얼마야?")]},
        "expected": {"next_node": "math_agent"},
    },
    {
        "id": "single-translate",
        "description": "단일턴 번역 → translate_agent",
        "input": {"messages": [HumanMessage(content="'안녕하세요'를 영어로 번역해줘")]},
        "expected": {"next_node": "translate_agent"},
    },
    {
        "id": "single-sql",
        "description": "단일턴 SQL → sql_agent",
        "input": {
            "messages": [HumanMessage(content="연봉이 5천만원 이상인 직원은 몇 명이야?")],
        },
        "expected": {"next_node": "sql_agent"},
    },
    {
        "id": "multiturn-toolcall",
        "description": "공장2 단답 복원 → tool_call_agent",
        "input": {
            "messages": [HumanMessage(content="공장2")],
            "chat_history": to_messages([
                ("human", "브랜치에서 제품 재고 조사해줘"),
                ("ai", "어떤 브랜치에서 재고를 조사할까요?"),
            ]),
        },
        "expected": {"next_node": "tool_call_agent"},
    },
    {
        "id": "multiturn-translate-referent",
        "description": "이거 다시 일본어로 → translate_agent",
        "input": {
            "messages": [HumanMessage(content="이거 다시 일본어로")],
            "chat_history": to_messages([
                ("human", "'좋은 아침입니다'를 영어로 번역해줘"),
                ("ai", "Good morning."),
            ]),
        },
        "expected": {"next_node": "translate_agent"},
    },
]


if __name__ == "__main__":
    sys.exit(run_eval(CASES, route_trace))
```

- [ ] **Step 3: Run pytest for regression**

Run: `uv run pytest -q`
Expected: 220 passed (no regression).

- [ ] **Step 4: Run both smokes against real LLM (manual verification)**

Run: `uv run python -m scripts.smoke_query_rewriter_router`
Expected: 5/5 pass (single-turn + both multi-turn cases; same as the prior subprocess smoke).

Run: `uv run python -m scripts.smoke_query_rewriter`
Expected: pass rate similar to the prior smoke run (date cases deterministic via `now=`; coref/ellipsis variable). Document the actual rate honestly; LLM-quality failures are data, not a task failure.

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_query_rewriter.py scripts/smoke_query_rewriter_router.py
git commit -m "refactor(route-smoke): use shared run_eval framework

두 스모크가 inline 호출 대신 scripts.eval.run_eval을 사용하도록 변환.
스모크 파일은 이제 EvalCase 데이터(CASES)와 한 줄짜리 run_eval 호출만
가지며, 실행·검증·출력 메커니즘은 scripts/eval.py에서 관리된다.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- 균일한 워크플로우 시그니쳐(`(CliState) -> CliState`) → Task 1 Steps 4-5 ✓
- `CliState(State)` with `rewritten`/`next_node` NotRequired → Task 1 Step 3 ✓
- 두 CLI strict isolation 유지 (route_trace가 rewrite 함수를 import하지 않고 인라인) → Task 1 Step 5 ✓
- `EvalCase` 4-field TypedDict (id/description/input/expected) → Task 2 Step 3 ✓
- `run_eval(cases, workflow, *, now, max_retries)` kwarg execution policy → Task 2 Step 3 ✓
- op 추론(str=eq, Pattern=regex, list[Pattern]=AND) → Task 2 Step 3 `_check` ✓
- 누락 필드 → FAIL + `<missing>` → Task 2 Step 3 `_check_case` + `_print_case` ✓
- 예외 → 즉시 FAIL, 재시도 없음 → Task 2 Step 3 (try/except 후 `break`) ✓
- patched_now가 전체 실행을 한 번 감쌈 → Task 2 Step 3 (`with patched_now(now):` 루프 바깥) ✓
- 단위 테스트 (op 추론, 누락, 예외, 재시도, now, baseline merge) → Task 2 Step 1 ✓
- 스모크가 데이터 + 한 줄 호출만 갖는 형태 → Task 3 Steps 1-2 ✓
- LLM-as-Judge `evals/run.py` 미터치 → 모든 Task가 손대지 않음 ✓
- 케이스별 now/max_retries override 미도입 → `EvalCase`에 그 필드 없음 ✓

**Placeholder scan:** 모든 Step에 구체 코드/명령/기대 출력 명시. TBD/TODO 없음.

**Type consistency:**
- `CliState` 정의는 Task 1 Step 3에서 한 곳, 이후 모든 사용처(`rewrite`, `route_trace`, smokes, `scripts/eval.py`, tests)에서 동일 이름과 필드(`rewritten`, `next_node`)로 사용. ✓
- `EvalCase` 4 필드는 Task 2 Step 3에서 정의되고 Task 2 Step 1 테스트와 Task 3 CASES에서 동일하게 사용. ✓
- `run_eval` 시그니쳐(cases, workflow, *, now, max_retries)는 Task 2 정의와 Task 3 호출 시 일치. ✓
- 출력 라벨(`PASS`/`FAIL`, `결과: N/M 통과`, `attempts=`, `<missing>`)은 Task 2 구현과 Task 2 단위 테스트의 stdout 단언이 일치. ✓
