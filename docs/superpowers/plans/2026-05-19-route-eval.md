# Route CLI + Smoke (query_rewriter + router) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a CLI that runs `query_rewriter` + `router` (and a rewriter-only CLI), plus subprocess smoke scripts that exercise those CLIs over inline cases and deterministically verify routing/rewrite output.

**Architecture:** One importable pipeline core in `evals/route_eval.py` (`to_messages`, `rewrite`, `route_trace`). Two thin CLIs under `scripts/cli/` wrap the core: query is the first positional arg (`nargs="+"`, space-joined), with `--history` (JSON) and `--now` (ISO, deterministic dates) options. Two smoke scripts under `scripts/` invoke the CLIs as subprocesses and assert on parsed stdout. Pipeline calls the real LLM (smoke = real, run deliberately); the core's composition logic has fast pytest unit tests with the LLM mocked.

**Tech Stack:** Python 3.11+, argparse, subprocess, langchain-core messages, langgraph `add_messages`, pytest (core/CLI unit tests only), python-dotenv.

---

## File Structure

- **Create `evals/route_eval.py`** — pipeline core only (no `main`): `Role`, `to_messages`, `_last_human_text`, `rewrite`, `route_trace`. One responsibility: compose the two real nodes and expose rewrite text + routing destination.
- **Create `tests/test_route_eval.py`** — pytest unit tests for the core, LLM mocked. Mirrors `tests/test_query_rewriter.py` conventions (Korean docstring stating no real LLM, typed, class-grouped).
- **Create `scripts/__init__.py`, `scripts/cli/__init__.py`** — empty package markers so `scripts.cli._common` imports cleanly.
- **Create `scripts/cli/_common.py`** — shared CLI args/parsing: `add_common_args`, `parse_history`, `patched_now`.
- **Create `scripts/cli/query_rewriter.py`** — rewriter-only CLI; prints `query` + `rewritten`.
- **Create `scripts/cli/query_rewriter_router.py`** — rewrite+route CLI; prints `query` + `rewritten` + `destination`.
- **Create `scripts/smoke_query_rewriter.py`** — subprocess smoke over ported date/coref cases; replaces `scripts/Test_query_rewriter.py`.
- **Delete `scripts/Test_query_rewriter.py`** — superseded by the CLI + smoke split.
- **Create `scripts/smoke_query_rewriter_router.py`** — subprocess smoke over inline `(history, query, expected destination)` cases.
- **Modify `Evaluation.md`** — document the CLIs and smoke scripts.
- **`tests/test_query_rewriter.py`** — UNCHANGED (pytest unit, mocked); kept per requirement.

Verified code facts:
- `src/query_rewriter/rewriter.py:38` `query_rewriter_node(state) -> dict` returns `{"messages":[HumanMessage(rewritten)]}` or `{"messages":[]}`. Uses `datetime.now()` at module ref `src.query_rewriter.rewriter.datetime` (patchable for `--now`, same as the old `scripts/Test_query_rewriter.py`).
- `src/router/router.py:69` `router_node(state) -> dict` → `{"messages":[AIMessage], "next_agent": str}`.
- `src/router/router.py:104` `router_conditional(state) -> str` → agent node name or `"response_generator"`.
- `src/router/__init__.py` exports `router_node`, `router_conditional`. `query_rewriter_node` import path: `src.query_rewriter.rewriter`.
- `src/state.py` `State` keys: `messages`, `next_agent`, `chat_history`.
- `add_messages`: `from langgraph.graph.message import add_messages`.
- Registry populated via `import src` (see `evals/run.py`).
- Existing scripts run via `uv run python -m scripts.<name>`.

---

### Task 1: Pipeline core (`evals/route_eval.py`)

**Files:**
- Create: `evals/route_eval.py`
- Test: `tests/test_route_eval.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_eval.py
"""route_eval 코어 단위 테스트.

LLM 호출 없이 노드 조립 로직만 검증한다. 실제 LLM 검증은
scripts/ 스모크 스크립트가 CLI를 subprocess로 실행해 수행한다.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from evals.route_eval import rewrite, route_trace, to_messages


class TestToMessages:
    def test_builds_in_order(self) -> None:
        msgs = to_messages([("human", "q1"), ("ai", "a1")])
        assert [type(m).__name__ for m in msgs] == ["HumanMessage", "AIMessage"]
        assert [m.content for m in msgs] == ["q1", "a1"]

    def test_empty(self) -> None:
        assert to_messages([]) == []


class TestRewrite:
    @patch("evals.route_eval.query_rewriter_node")
    def test_returns_rewritten_text(self, mock_rw: MagicMock) -> None:
        mock_rw.return_value = {"messages": [HumanMessage(content="확장된 질의")]}
        assert rewrite("원본", []) == "확장된 질의"

    @patch("evals.route_eval.query_rewriter_node")
    def test_falls_back_to_original_when_no_change(self, mock_rw: MagicMock) -> None:
        mock_rw.return_value = {"messages": []}
        assert rewrite("원본", []) == "원본"


class TestRouteTrace:
    @patch("evals.route_eval.router_conditional")
    @patch("evals.route_eval.router_node")
    @patch("evals.route_eval.query_rewriter_node")
    def test_returns_rewritten_and_destination(
        self, mock_rw: MagicMock, mock_router: MagicMock, mock_cond: MagicMock
    ) -> None:
        mock_rw.return_value = {"messages": [HumanMessage(content="확장된 질의")]}
        mock_router.return_value = {
            "messages": [AIMessage(content='{"next": "math"}')],
            "next_agent": "math",
        }
        mock_cond.return_value = "math"

        rewritten, dest = route_trace("3 더하기 4", [AIMessage(content="prev")])

        assert rewritten == "확장된 질의"
        assert dest == "math"
        router_state = mock_router.call_args[0][0]
        contents = [m.content for m in router_state["messages"]]
        assert "3 더하기 4" in contents and "확장된 질의" in contents
        assert mock_cond.call_args[0][0]["next_agent"] == "math"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_route_eval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.route_eval'`

- [ ] **Step 3: Write minimal implementation**

```python
# evals/route_eval.py
"""query_rewriter / router 파이프라인 코어 (CLI·스모크 공용).

단위 테스트(tests/test_route_eval.py)는 LLM을 목으로 대체해 조립 로직만
검증한다. 실제 LLM을 호출하는 검증은 scripts/ 스모크 스크립트가 CLI를
subprocess로 실행해 수행한다 (LLM-as-Judge 아님).
"""

from __future__ import annotations

from typing import Literal, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph.message import add_messages

from src.query_rewriter.rewriter import query_rewriter_node
from src.router import router_conditional, router_node
from src.state import State

Role = Literal["human", "ai"]


def to_messages(pairs: list[tuple[Role, str]]) -> list[BaseMessage]:
    """(role, content) 쌍 리스트를 BaseMessage 리스트로 변환한다."""
    out: list[BaseMessage] = []
    for role, content in pairs:
        if role == "human":
            out.append(HumanMessage(content=content))
        else:
            out.append(AIMessage(content=content))
    return out


def _last_human_text(messages: list[BaseMessage], default: str) -> str:
    """messages에서 마지막 HumanMessage 본문을 반환한다 (없으면 default)."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return cast(str, msg.content)
    return default


def rewrite(query: str, chat_history: list[BaseMessage]) -> str:
    """query_rewriter_node를 실행하고 리라이팅된 질의 텍스트를 반환한다.

    리라이팅이 없으면 원본 query를 그대로 반환한다.
    """
    state: State = {
        "messages": [HumanMessage(content=query)],
        "next_agent": "",
        "chat_history": chat_history,
    }
    rw = query_rewriter_node(state)
    merged = add_messages(state["messages"], rw["messages"])
    return _last_human_text(merged, query)


def route_trace(
    query: str, chat_history: list[BaseMessage]
) -> tuple[str, str]:
    """query_rewriter → router를 실제 LLM으로 연쇄 실행하고
    (리라이팅된 질의, 라우팅된 목적지 노드명)을 반환한다.
    """
    state: State = {
        "messages": [HumanMessage(content=query)],
        "next_agent": "",
        "chat_history": chat_history,
    }

    rw = query_rewriter_node(state)
    state["messages"] = add_messages(state["messages"], rw["messages"])
    rewritten = _last_human_text(state["messages"], query)

    rt = router_node(state)
    state["messages"] = add_messages(state["messages"], rt["messages"])
    state["next_agent"] = rt["next_agent"]

    return rewritten, router_conditional(state)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_route_eval.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add evals/route_eval.py tests/test_route_eval.py
git commit -m "feat(route-eval): add query_rewriter+router pipeline core

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Shared CLI helpers (`scripts/cli/_common.py`)

**Files:**
- Create: `scripts/__init__.py`, `scripts/cli/__init__.py`, `scripts/cli/_common.py`
- Test: `tests/test_route_eval.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_route_eval.py`:

```python
import argparse

from scripts.cli._common import add_common_args, parse_history, patched_now


class TestCliCommon:
    def test_query_is_positional_nargs_plus(self) -> None:
        parser = argparse.ArgumentParser()
        add_common_args(parser)
        args = parser.parse_args(["지난주", "매출", "알려줘"])
        assert " ".join(args.query) == "지난주 매출 알려줘"
        assert args.history == ""
        assert args.now == ""

    def test_parse_history_empty(self) -> None:
        assert parse_history("") == []
        assert parse_history("   ") == []

    def test_parse_history_json(self) -> None:
        raw = '[{"role":"human","content":"재고"},{"role":"ai","content":"어떤 브랜치?"}]'
        msgs = parse_history(raw)
        assert [type(m).__name__ for m in msgs] == ["HumanMessage", "AIMessage"]
        assert [m.content for m in msgs] == ["재고", "어떤 브랜치?"]

    def test_patched_now_noop_without_value(self) -> None:
        with patched_now(""):
            pass  # 예외 없이 통과하면 OK

    def test_patched_now_fixes_rewriter_datetime(self) -> None:
        from datetime import datetime

        with patched_now("2026-04-29T14:30"):
            import src.query_rewriter.rewriter as rw_mod

            assert rw_mod.datetime.now() == datetime(2026, 4, 29, 14, 30)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_route_eval.py::TestCliCommon -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.cli'`

- [ ] **Step 3: Write minimal implementation**

Create empty files:

```bash
: > scripts/__init__.py
mkdir -p scripts/cli
: > scripts/cli/__init__.py
```

```python
# scripts/cli/_common.py
"""query_rewriter 계열 CLI 공용 인자/파서.

첫 위치인자(query)는 nargs="+"로 받아 공백으로 이어 붙인다 →
따옴표 없이 여러 단어를 그대로 입력할 수 있다.
"""

from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, cast
from unittest.mock import patch

from langchain_core.messages import BaseMessage

from evals.route_eval import Role, to_messages


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """query 위치인자 + --history/--now 옵션을 parser에 추가한다."""
    parser.add_argument(
        "query",
        nargs="+",
        help="사용자 질의 (여러 단어는 공백으로 이어 붙임; 따옴표 불필요)",
    )
    parser.add_argument(
        "--history",
        default="",
        help=(
            'chat_history JSON. 예: '
            '\'[{"role":"human","content":"..."},'
            '{"role":"ai","content":"..."}]\''
        ),
    )
    parser.add_argument(
        "--now",
        default="",
        help="리라이터 기준 시각 ISO (예: 2026-04-29T14:30). "
        "지정 시 상대 날짜 변환이 결정적이 된다.",
    )


def parse_history(raw: str) -> list[BaseMessage]:
    """--history JSON 문자열을 BaseMessage 리스트로 변환한다."""
    if not raw.strip():
        return []
    data = json.loads(raw)
    pairs = [(cast(Role, d["role"]), str(d["content"])) for d in data]
    return to_messages(pairs)


@contextmanager
def patched_now(now_iso: str) -> Iterator[None]:
    """now_iso가 주어지면 rewriter의 datetime.now()를 고정한다."""
    if not now_iso:
        yield
        return
    fixed = datetime.fromisoformat(now_iso)
    with patch("src.query_rewriter.rewriter.datetime") as mock_dt:
        mock_dt.now.return_value = fixed
        yield
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_route_eval.py::TestCliCommon -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/__init__.py scripts/cli/__init__.py scripts/cli/_common.py tests/test_route_eval.py
git commit -m "feat(route-cli): add shared CLI args/history/now helpers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Rewriter-only CLI (`scripts/cli/query_rewriter.py`)

**Files:**
- Create: `scripts/cli/query_rewriter.py`
- Test: `tests/test_route_eval.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_route_eval.py`:

```python
class TestQueryRewriterCli:
    @patch("evals.route_eval.rewrite", return_value="지난주(2026-04-20~2026-04-26) 매출 알려줘")
    def test_prints_query_and_rewritten(
        self, _mock_rw: MagicMock, capsys, monkeypatch
    ) -> None:
        import scripts.cli.query_rewriter as cli

        monkeypatch.setattr(
            "sys.argv",
            ["prog", "지난주", "매출", "알려줘", "--now", "2026-04-29T14:30"],
        )
        with patch("scripts.cli.query_rewriter.SystemExit", SystemExit):
            try:
                cli.main()
            except SystemExit as e:
                assert e.code == 0
        out = capsys.readouterr().out
        assert "query    : 지난주 매출 알려줘" in out
        assert "rewritten: 지난주(2026-04-20~2026-04-26) 매출 알려줘" in out
```

(Note: `rewrite` is patched at its definition module `evals.route_eval`; the CLI imports it lazily inside `main`, so the patch is active when `main` runs.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_route_eval.py::TestQueryRewriterCli -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.cli.query_rewriter'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/cli/query_rewriter.py
"""query_rewriter 단독 실행 CLI.

첫 위치인자로 사용자 질의를 받아 리라이팅 결과를 stdout에 출력한다.

실행:
    uv run python -m scripts.cli.query_rewriter 지난주 매출 알려줘 --now 2026-04-29T14:30
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv


def main() -> None:
    """리라이터를 1회 실행하고 결과를 출력한다."""
    load_dotenv()
    import src  # noqa: F401  registry 등록

    from evals.route_eval import rewrite
    from scripts.cli._common import add_common_args, parse_history, patched_now

    parser = argparse.ArgumentParser(description="query_rewriter 단독 실행")
    add_common_args(parser)
    args = parser.parse_args()

    query = " ".join(args.query)
    history = parse_history(args.history)

    with patched_now(args.now):
        rewritten = rewrite(query, history)

    print(f"query    : {query}")
    print(f"rewritten: {rewritten}")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_route_eval.py::TestQueryRewriterCli -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add scripts/cli/query_rewriter.py tests/test_route_eval.py
git commit -m "feat(route-cli): add rewriter-only CLI

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Rewrite+route CLI (`scripts/cli/query_rewriter_router.py`)

**Files:**
- Create: `scripts/cli/query_rewriter_router.py`
- Test: `tests/test_route_eval.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_route_eval.py`:

```python
class TestQueryRewriterRouterCli:
    @patch("evals.route_eval.route_trace", return_value=("공장2의 제품 재고를 조사해줘", "tool_call"))
    def test_prints_query_rewritten_destination(
        self, _mock_rt: MagicMock, capsys, monkeypatch
    ) -> None:
        import scripts.cli.query_rewriter_router as cli

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
        assert "destination: tool_call" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_route_eval.py::TestQueryRewriterRouterCli -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.cli.query_rewriter_router'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/cli/query_rewriter_router.py
"""query_rewriter + router 실행 CLI.

첫 위치인자로 사용자 질의를 받아 리라이팅 후 라우팅하고,
리라이팅 결과와 라우팅 목적지를 stdout에 출력한다.

실행:
    uv run python -m scripts.cli.query_rewriter_router 3 곱하기 7
    uv run python -m scripts.cli.query_rewriter_router 공장2 \\
        --history '[{"role":"human","content":"재고 조사"},{"role":"ai","content":"어떤 브랜치?"}]'
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv


def main() -> None:
    """리라이터 → 라우터를 연쇄 실행하고 결과를 출력한다."""
    load_dotenv()
    import src  # noqa: F401  registry 등록

    from evals.route_eval import route_trace
    from scripts.cli._common import add_common_args, parse_history, patched_now

    parser = argparse.ArgumentParser(description="query_rewriter + router 실행")
    add_common_args(parser)
    args = parser.parse_args()

    query = " ".join(args.query)
    history = parse_history(args.history)

    with patched_now(args.now):
        rewritten, destination = route_trace(query, history)

    print(f"query      : {query}")
    print(f"rewritten  : {rewritten}")
    print(f"destination: {destination}")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_route_eval.py::TestQueryRewriterRouterCli -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add scripts/cli/query_rewriter_router.py tests/test_route_eval.py
git commit -m "feat(route-cli): add rewrite+route CLI

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Router smoke (`scripts/smoke_query_rewriter_router.py`)

**Files:**
- Create: `scripts/smoke_query_rewriter_router.py`

(No pytest unit test: this is a real-LLM subprocess smoke; verified by running it.)

- [ ] **Step 1: Write the smoke script**

```python
# scripts/smoke_query_rewriter_router.py
"""query_rewriter + router CLI subprocess 스모크.

scripts.cli.query_rewriter_router 를 subprocess로 호출하고,
출력의 'destination:' 줄을 기대 라우팅 목적지와 결정적으로 비교한다.
파이프라인은 실제 LLM을 호출하므로 비결정적·유료이며 의도적으로 실행한다.

실행:
    uv run python -m scripts.smoke_query_rewriter_router
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TypedDict


class RouteCase(TypedDict):
    """라우팅 스모크 케이스."""

    id: str
    history: list[dict[str, str]]
    query: str
    expected: str


CASES: list[RouteCase] = [
    {"id": "single-math", "history": [], "query": "3 곱하기 7은 얼마야?", "expected": "math"},
    {
        "id": "single-translate",
        "history": [],
        "query": "'안녕하세요'를 영어로 번역해줘",
        "expected": "translate",
    },
    {
        "id": "single-sql",
        "history": [],
        "query": "연봉이 5천만원 이상인 직원은 몇 명이야?",
        "expected": "sql",
    },
    {
        "id": "multiturn-toolcall",
        "history": [
            {"role": "human", "content": "브랜치에서 제품 재고 조사해줘"},
            {"role": "ai", "content": "어떤 브랜치에서 재고를 조사할까요?"},
        ],
        "query": "공장2",
        "expected": "tool_call",
    },
    {
        "id": "multiturn-translate-referent",
        "history": [
            {"role": "human", "content": "'좋은 아침입니다'를 영어로 번역해줘"},
            {"role": "ai", "content": "Good morning."},
        ],
        "query": "이거 다시 일본어로",
        "expected": "translate",
    },
    {
        "id": "insufficient-no-context",
        "history": [],
        "query": "공장2",
        "expected": "response_generator",
    },
]


def _parse_destination(stdout: str) -> str:
    """CLI stdout에서 'destination:' 줄의 값을 추출한다."""
    for line in stdout.splitlines():
        if line.startswith("destination"):
            return line.split(":", 1)[1].strip()
    return "<no destination line>"


def run() -> int:
    """모든 케이스를 실행하고 PASS/FAIL을 출력한다."""
    pass_count = 0
    for idx, case in enumerate(CASES, start=1):
        cmd = [
            sys.executable,
            "-m",
            "scripts.cli.query_rewriter_router",
            case["query"],
        ]
        if case["history"]:
            cmd += ["--history", json.dumps(case["history"], ensure_ascii=False)]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        actual = _parse_destination(proc.stdout)
        passed = proc.returncode == 0 and actual == case["expected"]
        if passed:
            pass_count += 1

        status = "PASS" if passed else "FAIL"
        print(f"[{idx:02d}] [{status}] {case['id']}")
        print(f"     query   : {case['query']}")
        print(f"     expected: {case['expected']}")
        print(f"     actual  : {actual}")
        if proc.returncode != 0:
            print(f"     stderr  : {proc.stderr.strip()}")
        print()

    total = len(CASES)
    print(f"결과: {pass_count}/{total} 통과")
    return 0 if pass_count == total else 1


if __name__ == "__main__":
    sys.exit(run())
```

- [ ] **Step 2: Verify harness unit tests still pass (no real LLM)**

Run: `uv run pytest tests/test_route_eval.py -v`
Expected: PASS (all tests from Tasks 1-4)

- [ ] **Step 3: Run the router smoke (real LLM)**

Run: `uv run python -m scripts.smoke_query_rewriter_router`
Expected: per-case PASS/FAIL printed; single-turn cases PASS; multi-turn results recorded. Exit 0 iff all pass.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_query_rewriter_router.py
git commit -m "feat(route-smoke): add router CLI subprocess smoke

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Rewriter smoke + remove old script

**Files:**
- Create: `scripts/smoke_query_rewriter.py`
- Delete: `scripts/Test_query_rewriter.py`

(No pytest unit test: real-LLM subprocess smoke; verified by running it. `--now` makes date conversion deterministic; retries absorb residual LLM phrasing variance.)

- [ ] **Step 1: Write the smoke script (ports the date/coref cases)**

```python
# scripts/smoke_query_rewriter.py
"""query_rewriter CLI subprocess 스모크.

scripts.cli.query_rewriter 를 --now 고정 시각으로 subprocess 호출하고,
출력의 'rewritten:' 줄에서 기대 정규식 패턴이 모두 발견되는지 검사한다.
--now 로 상대 날짜 변환은 결정적이며, MAX_RETRIES 로 LLM 표현 편차를 흡수한다.

scripts/Test_query_rewriter.py 를 CLI + subprocess 형태로 대체한다.

실행:
    uv run python -m scripts.smoke_query_rewriter
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import NotRequired, TypedDict

FIXED_NOW = "2026-04-29T14:30"
MAX_RETRIES = 3


class Case(TypedDict):
    """리라이터 스모크 케이스."""

    category: str
    input: str
    expected_patterns: list[str]
    history: NotRequired[list[dict[str, str]]]


CASES: list[Case] = [
    {"category": "일:오늘", "input": "오늘 매출 알려줘", "expected_patterns": [r"2026-04-29"]},
    {"category": "일:어제", "input": "어제 매출 알려줘", "expected_patterns": [r"2026-04-28"]},
    {
        "category": "주:지난주",
        "input": "지난주 매출 알려줘",
        "expected_patterns": [r"2026-04-20", r"2026-04-26"],
    },
    {
        "category": "월:지난달",
        "input": "지난달 매출 알려줘",
        "expected_patterns": [r"2026-03-01", r"2026-03-31"],
    },
    {
        "category": "최근:N일",
        "input": "최근 7일 매출 알려줘",
        "expected_patterns": [r"2026-04-22", r"2026-04-29"],
    },
    {
        "category": "년:작년",
        "input": "작년 매출",
        "expected_patterns": [r"2025-01-01", r"2025-12-31"],
    },
    {
        "category": "분기:1분기",
        "input": "1분기 매출",
        "expected_patterns": [r"2026-01-01", r"2026-03-31"],
    },
    {
        "category": "자연어:N월 N일",
        "input": "4월 17일 매출",
        "expected_patterns": [r"2026-04-17"],
    },
    {
        "category": "coref:번역 결과 → 이거",
        "history": [
            {"role": "human", "content": "Hello, how are you?를 한국어로 번역해줘"},
            {"role": "ai", "content": "안녕하세요, 어떻게 지내세요?"},
        ],
        "input": "이거 일본어로도 번역해줘",
        "expected_patterns": [r"안녕하세요|Hello"],
    },
    {
        "category": "ellipsis:동사 재사용",
        "history": [
            {"role": "human", "content": "어제 매출 알려줘"},
            {"role": "ai", "content": "2026-04-28 매출은 1억원입니다."},
        ],
        "input": "오늘은?",
        "expected_patterns": [r"2026-04-29", r"매출"],
    },
    {
        "category": "독립:번역 → 수학 (오염 없음)",
        "history": [
            {"role": "human", "content": "Hello를 한국어로 번역해줘"},
            {"role": "ai", "content": "안녕하세요"},
        ],
        "input": "3과 7을 더해줘",
        "expected_patterns": [r"3.{0,5}7|7.{0,5}3", r"더해|더하|덧셈|합"],
    },
]


def _parse_rewritten(stdout: str) -> str:
    """CLI stdout에서 'rewritten:' 줄의 값을 추출한다."""
    for line in stdout.splitlines():
        if line.startswith("rewritten"):
            return line.split(":", 1)[1].strip()
    return ""


def run() -> int:
    """모든 케이스를 실행하고 PASS/FAIL을 출력한다."""
    print(f"기준 시각 (--now): {FIXED_NOW}")
    print(f"테스트 케이스: {len(CASES)}건\n")

    pass_count = 0
    for idx, case in enumerate(CASES, start=1):
        cmd = [
            sys.executable,
            "-m",
            "scripts.cli.query_rewriter",
            case["input"],
            "--now",
            FIXED_NOW,
        ]
        history = case.get("history")
        if history:
            cmd += ["--history", json.dumps(history, ensure_ascii=False)]

        rewritten = ""
        missing: list[str] = []
        passed = False
        attempts = 0
        for attempt in range(1, MAX_RETRIES + 1):
            attempts = attempt
            proc = subprocess.run(cmd, capture_output=True, text=True)
            rewritten = _parse_rewritten(proc.stdout)
            missing = [
                p for p in case["expected_patterns"] if not re.search(p, rewritten)
            ]
            passed = proc.returncode == 0 and not missing
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
        print()

    total = len(CASES)
    print(f"결과: {pass_count}/{total} 통과")
    return 0 if pass_count == total else 1


if __name__ == "__main__":
    sys.exit(run())
```

- [ ] **Step 2: Delete the superseded script**

Run: `git rm scripts/Test_query_rewriter.py`
Expected: file staged for deletion.

- [ ] **Step 3: Run the rewriter smoke (real LLM)**

Run: `uv run python -m scripts.smoke_query_rewriter`
Expected: per-case PASS/FAIL; deterministic date cases PASS (thanks to `--now`); coref/ellipsis recorded.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_query_rewriter.py
git commit -m "refactor(route-smoke): replace Test_query_rewriter.py with CLI smoke

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Document the CLIs and smoke scripts

**Files:**
- Modify: `Evaluation.md`

- [ ] **Step 1: Read the current doc**

Run: `sed -n '1,40p' Evaluation.md`
Expected: see existing eval description and heading style.

- [ ] **Step 2: Append a new section (match the file's heading level)**

```markdown
## query_rewriter / router CLI & Smoke

LLM-as-Judge와 별개로, `query_rewriter` + `router` 파이프라인을 직접
실행·검증하는 CLI와 스모크가 있다.

CLI (첫 위치인자 = 사용자 질의, 공백 분리 다단어 허용):

- `uv run python -m scripts.cli.query_rewriter 지난주 매출 알려줘 --now 2026-04-29T14:30`
  → 리라이팅 결과 출력
- `uv run python -m scripts.cli.query_rewriter_router 공장2 --history '[{"role":"human","content":"재고 조사"},{"role":"ai","content":"어떤 브랜치?"}]'`
  → 리라이팅 결과 + 라우팅 목적지 출력

옵션: `--history`(chat_history JSON), `--now`(리라이터 기준 시각 ISO,
지정 시 상대 날짜 변환이 결정적).

스모크 (CLI를 subprocess로 호출, 실제 LLM):

- `uv run python -m scripts.smoke_query_rewriter` — 상대 날짜/지시어 케이스
  (`--now` 고정으로 날짜는 결정적)
- `uv run python -m scripts.smoke_query_rewriter_router` — `(history, query)`
  입력에 대해 라우팅 목적지를 기대값과 결정적으로 비교

파이프라인 코어(`evals/route_eval.py`)의 조립 로직 단위 테스트(LLM 목)는
`tests/test_route_eval.py`에, 리라이터 노드 자체의 단위 테스트는
기존 `tests/test_query_rewriter.py`에 있다.
```

- [ ] **Step 3: Commit**

```bash
git add Evaluation.md
git commit -m "docs(route-cli): document query_rewriter/router CLI and smoke

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- "쿼리리라이트+라우팅 CLI를 scripts/cli/query_rewriter_router.py" → Task 4. ✓
- "이를 테스트하는 스크립트를 scripts 아래" (= CLI subprocess 스모크) → Task 5. ✓
- "기존 test_query_rewriter.py도 마찬가지 형태로 다시 구현" (pytest 유지 + scripts 스모크 추가) → `tests/test_query_rewriter.py` untouched; old `scripts/Test_query_rewriter.py` re-implemented as CLI (Task 3) + subprocess smoke (Task 6). ✓
- "첫번째 전달인자로 사용자 질의" → `add_common_args` positional `query` with `nargs="+"` (Task 2), space-joined in both CLIs (Tasks 3-4). ✓
- DRY: single pipeline core (Task 1) reused by both CLIs; single `_common` for args/history/now. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code; commands have expected output. ✓

**Type consistency:** `to_messages(list[tuple[Role,str]])`, `rewrite(query, chat_history)->str`, `route_trace(query, chat_history)->tuple[str,str]` defined in Task 1 and used identically in Tasks 2-4 tests and CLIs. `add_common_args`/`parse_history`/`patched_now` signatures from Task 2 used unchanged in Tasks 3-4. CLI stdout line prefixes (`query`/`rewritten`/`destination`) emitted in Tasks 3-4 and parsed by the exact same prefixes in Tasks 5-6. ✓
