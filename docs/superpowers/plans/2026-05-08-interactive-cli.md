# Interactive CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 `src/main.py`의 정해진 시나리오 실행 대신, 사용자가 자유 입력으로 멀티턴 대화하고 카테고리별 추천 질문을 fuzzy 매칭으로 선택·편집하며 노드별 처리 경과를 실시간으로 확인할 수 있는 신규 진입점 `python -m src.cli`를 구현한다.

**Architecture:** 기존 그래프(`src/main.py:build_graph`)는 그대로 재사용하고, 신규 `src/cli/` 패키지에 REPL/입력/스트리밍/명령/추천 모듈을 분리. LangGraph의 `stream(state, stream_mode="updates")`로 노드 단위 이벤트를 받아 터미널에 라인 단위로 렌더링한다. `chat_history`는 매 turn 결과의 delta를 누적하여 다음 turn 입력 state로 인계한다.

**Tech Stack:** Python 3.11, LangGraph, LangChain, prompt_toolkit (신규), pyyaml (기존), pytest.

**참고 사양:** `docs/superpowers/specs/2026-05-08-interactive-cli-design.md`

---

## File Structure

| 경로 | 책임 |
|------|------|
| `src/cli/__init__.py` | 패키지 마커 (빈 파일) |
| `src/cli/__main__.py` | `python -m src.cli` 진입점 → `app.run()` 호출 |
| `src/cli/suggestions.py` | `res/suggestions.yaml` 로딩, 평면 리스트 + 카테고리 메타 dict 반환 |
| `src/cli/commands.py` | 슬래시 명령 dispatcher (`/exit`, `/reset`, `/list`, `/help`) |
| `src/cli/streaming.py` | `NodeRenderer` — 노드 이벤트 → 터미널 라인. 노드별 포맷터 dict |
| `src/cli/prompt.py` | prompt_toolkit `PromptSession` + `FuzzyCompleter` 빌드, 헤더 출력 |
| `src/cli/app.py` | REPL 루프, `run_turn` (graph stream 소비 + chat_history 누적) |
| `res/suggestions.yaml` | 카테고리(에이전트명)별 추천 질문 시드 |
| `tests/test_cli_suggestions.py` | suggestions 로더 단위 테스트 |
| `tests/test_cli_commands.py` | 슬래시 명령 dispatcher 단위 테스트 |
| `tests/test_cli_streaming.py` | NodeRenderer 단위 테스트 (StringIO capture) |
| `tests/test_cli_app.py` | REPL 루프 통합 테스트 1개 (graph mock) |
| `pyproject.toml` | `prompt_toolkit>=3.0` 의존성 추가 |
| `README.md` | 인터랙티브 CLI 사용법 섹션 추가 |

기존 모듈(`src/main.py`, `src/state.py`, `src/registry.py`, 모든 노드/에이전트, `evals/`)은 변경하지 않는다.

### 사양과의 차이 (단순화)

사양 §스트리밍 §노드별 표시 정보 표에 `*_agent`의 "tools: list_tables, execute_sql" 표시가 명시돼 있으나, 현재 wrapper 구조상 서브그래프의 `tool_calls` 정보가 메인 그래프 stream으로 노출되지 않는다 (wrapper가 마지막 `AIMessage`만 반환). wrapper 변경은 본 plan의 scope를 넘어가므로, 본 구현에서는 `*_agent` 노드는 **노드명 + 경과 시간만** 표시하고 tool 정보 표시는 향후 개선 항목으로 유보한다. 사용자 의도("서브에이전트 처리 과정 스트리밍")는 노드명·라우팅 결정·rewriter 결과·최종 답변의 계단식 표시로 충족된다.

---

## Task 1: 의존성 추가 + cli 패키지 스켈레톤

**Files:**
- Modify: `pyproject.toml`
- Create: `src/cli/__init__.py`

- [ ] **Step 1: `prompt_toolkit` 의존성 추가**

`pyproject.toml`의 `dependencies`에 한 줄 추가.

```toml
[project]
name = "supervisor-subagent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "langgraph>=0.2.0",
    "langchain-openai>=0.1.0",
    "langchain-core>=0.2.0",
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0",
    "prompt_toolkit>=3.0",
]
```

- [ ] **Step 2: 의존성 동기화**

Run: `uv sync`
Expected: `prompt_toolkit` 다운로드/설치 후 정상 종료.

- [ ] **Step 3: 빈 패키지 마커 생성**

`src/cli/__init__.py`:

```python
```

(빈 파일)

- [ ] **Step 4: import smoke**

Run: `uv run python -c "import prompt_toolkit; import src.cli; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/cli/__init__.py
git commit -m "chore(cli): add prompt_toolkit dep and cli package skeleton"
```

---

## Task 2: Suggestions YAML 로더 (TDD)

**Files:**
- Create: `tests/test_cli_suggestions.py`
- Create: `src/cli/suggestions.py`

API 결정:

```python
def load_suggestions(path: Path) -> dict[str, list[str]]:
    """카테고리별 추천 질문 dict를 반환. 파일 없거나 빈 파일이면 {} 반환."""

def flatten(suggestions: dict[str, list[str]]) -> tuple[list[str], dict[str, str]]:
    """평면 리스트와 {질문: 카테고리} 메타 dict를 반환."""
```

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_cli_suggestions.py`:

```python
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
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `uv run pytest tests/test_cli_suggestions.py -v`
Expected: `ImportError` 또는 `ModuleNotFoundError: src.cli.suggestions` (5 errors)

- [ ] **Step 3: 최소 구현 작성**

`src/cli/suggestions.py`:

```python
"""추천 질문 YAML 로더 + 평면 리스트 변환."""

from pathlib import Path

import yaml

from src.logging import get_logger

logger = get_logger("cli.suggestions")


def load_suggestions(path: Path) -> dict[str, list[str]]:
    """카테고리별 추천 질문 dict를 로드한다.

    파일이 없거나 비어 있으면 빈 dict를 반환한다.
    최상위 구조가 dict가 아니면 ValueError를 발생시킨다.
    """
    if not path.exists():
        logger.warning("suggestions 파일을 찾을 수 없음: %s", path)
        return {}

    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}

    parsed = yaml.safe_load(raw)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ValueError(
            f"suggestions 최상위는 dict여야 합니다 (got {type(parsed).__name__}): {path}"
        )

    result: dict[str, list[str]] = {}
    for category, items in parsed.items():
        if not isinstance(items, list):
            logger.warning("카테고리 %s는 list가 아님 → 무시", category)
            continue
        result[str(category)] = [str(x) for x in items]
    return result


def flatten(suggestions: dict[str, list[str]]) -> tuple[list[str], dict[str, str]]:
    """평면 리스트와 {질문: 카테고리} 메타 dict를 반환한다.

    카테고리 등록 순서, 카테고리 내부 순서를 모두 보존한다.
    """
    flat: list[str] = []
    meta: dict[str, str] = {}
    for category, items in suggestions.items():
        for text in items:
            flat.append(text)
            meta[text] = category
    return flat, meta
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `uv run pytest tests/test_cli_suggestions.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/cli/suggestions.py tests/test_cli_suggestions.py
git commit -m "feat(cli): add suggestions YAML loader and flatten helper"
```

---

## Task 3: 슬래시 명령 dispatcher (TDD)

**Files:**
- Create: `tests/test_cli_commands.py`
- Create: `src/cli/commands.py`

API 결정:

```python
class CommandResult(TypedDict, total=False):
    output: str                       # 표시할 텍스트 (없으면 표시 안 함)
    chat_history: list[BaseMessage]   # 새 chat_history (변경 없으면 키 생략)
    should_exit: bool                 # True면 REPL 종료

def is_command(text: str) -> bool: ...
def handle_command(
    text: str,
    chat_history: list[BaseMessage],
    suggestions: dict[str, list[str]],
) -> CommandResult: ...
```

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_cli_commands.py`:

```python
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
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `uv run pytest tests/test_cli_commands.py -v`
Expected: `ModuleNotFoundError: src.cli.commands`

- [ ] **Step 3: 최소 구현 작성**

`src/cli/commands.py`:

```python
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
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `uv run pytest tests/test_cli_commands.py -v`
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add src/cli/commands.py tests/test_cli_commands.py
git commit -m "feat(cli): add slash command dispatcher (/exit /reset /list /help)"
```

---

## Task 4: 노드 이벤트 스트리밍 렌더러 (TDD)

**Files:**
- Create: `tests/test_cli_streaming.py`
- Create: `src/cli/streaming.py`

API 결정:

```python
class NodeRenderer:
    def __init__(self, stream: TextIO = sys.stdout, formatters: dict | None = None): ...
    def turn_start(self) -> None: ...
    def on_node_update(self, node_name: str, delta: dict) -> None: ...
    def render_final_answer(self, content: str) -> None: ...

# 노드별 포맷터 — delta dict를 받아 추가 표시 라인 리스트를 반환
def format_query_rewriter(delta: dict) -> list[str]: ...
def format_router(delta: dict) -> list[str]: ...
def format_agent(delta: dict) -> list[str]: ...
def format_response_generator(delta: dict) -> list[str]: ...

DEFAULT_FORMATTERS: dict[str, Callable[[dict], list[str]]]
```

ANSI 컬러는 직접 추가하지 않고 일반 텍스트로만 출력한다 (테스트 단순성). 추후 옵션으로 색을 추가할 수 있도록 확장 여지만 둔다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_cli_streaming.py`:

```python
import io
import re

from langchain_core.messages import AIMessage, HumanMessage

from src.cli.streaming import (
    NodeRenderer,
    format_agent,
    format_query_rewriter,
    format_response_generator,
    format_router,
)


def _strip_timing(text: str) -> str:
    """렌더러 출력에서 가변적인 (X.XXs) 부분을 마스킹한다."""
    return re.sub(r"\(\d+\.\d{2}s\)", "(T.TTs)", text)


def test_format_query_rewriter_with_change() -> None:
    delta = {"messages": [HumanMessage(content="rewritten query")]}
    assert format_query_rewriter(delta) == ["rewritten: rewritten query"]


def test_format_query_rewriter_no_change() -> None:
    assert format_query_rewriter({"messages": []}) == ["no change"]
    assert format_query_rewriter({}) == ["no change"]


def test_format_router_emits_next_agent() -> None:
    assert format_router({"next_agent": "sql"}) == ["next_agent: sql"]


def test_format_router_skips_when_empty() -> None:
    assert format_router({"next_agent": ""}) == []
    assert format_router({}) == []


def test_format_agent_emits_no_extra_lines() -> None:
    delta = {"messages": [AIMessage(content="[수학 계산 결과]\n12")]}
    assert format_agent(delta) == []


def test_format_response_generator_emits_no_extra_lines() -> None:
    delta = {"messages": [AIMessage(content="최종 답변")]}
    assert format_response_generator(delta) == []


def test_renderer_outputs_node_line_with_delta() -> None:
    buf = io.StringIO()
    renderer = NodeRenderer(stream=buf)
    renderer.turn_start()
    renderer.on_node_update("router", {"next_agent": "sql"})

    out = _strip_timing(buf.getvalue())
    assert "router" in out
    assert "done" in out
    assert "next_agent: sql" in out


def test_renderer_unknown_node_falls_back_to_node_name_only() -> None:
    buf = io.StringIO()
    renderer = NodeRenderer(stream=buf)
    renderer.turn_start()
    renderer.on_node_update("future_node", {"foo": "bar"})

    out = _strip_timing(buf.getvalue())
    assert "future_node" in out
    assert "done" in out
    # delta에서 임의 키를 끌어와 출력하지 않는다
    assert "foo: bar" not in out


def test_renderer_render_final_answer_wraps_with_separator() -> None:
    buf = io.StringIO()
    renderer = NodeRenderer(stream=buf)
    renderer.render_final_answer("최종 답변입니다.")

    out = buf.getvalue()
    assert "최종 답변입니다." in out
    assert out.count("─") >= 2 or out.count("-") >= 2  # 구분선 2개
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `uv run pytest tests/test_cli_streaming.py -v`
Expected: `ModuleNotFoundError: src.cli.streaming`

- [ ] **Step 3: 최소 구현 작성**

`src/cli/streaming.py`:

```python
"""LangGraph stream chunk를 터미널 라인 이벤트로 렌더링한다."""

from __future__ import annotations

import sys
import time
from typing import Callable, TextIO

from langchain_core.messages import HumanMessage


def format_query_rewriter(delta: dict) -> list[str]:
    """변경된 query가 있으면 'rewritten: ...', 없으면 'no change'."""
    msgs = delta.get("messages") or []
    for msg in reversed(msgs):
        if isinstance(msg, HumanMessage):
            return [f"rewritten: {msg.content}"]
    return ["no change"]


def format_router(delta: dict) -> list[str]:
    next_agent = delta.get("next_agent") or ""
    if not next_agent:
        return []
    return [f"next_agent: {next_agent}"]


def format_agent(delta: dict) -> list[str]:
    """*_agent 노드는 노드명/경과시간만으로 충분 → 추가 라인 없음."""
    return []


def format_response_generator(delta: dict) -> list[str]:
    """최종 답변은 별도 render_final_answer로 출력하므로 추가 라인 없음."""
    return []


DEFAULT_FORMATTERS: dict[str, Callable[[dict], list[str]]] = {
    "query_rewriter": format_query_rewriter,
    "router": format_router,
    "math_agent": format_agent,
    "translate_agent": format_agent,
    "sql_agent": format_agent,
    "response_generator": format_response_generator,
}


SEPARATOR = "─" * 60


class NodeRenderer:
    """노드 단위 이벤트를 한 줄씩 터미널에 출력한다.

    경과 시간은 직전 노드 종료부터의 wall-clock 시간으로 측정한다
    (LangGraph stream_mode='updates'는 노드 완료 시점만 yield하므로
    노드별 정확한 시작 시간을 알 수 없다).
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        formatters: dict[str, Callable[[dict], list[str]]] | None = None,
    ) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._formatters = formatters or DEFAULT_FORMATTERS
        self._last_tick: float | None = None

    def turn_start(self) -> None:
        self._last_tick = time.monotonic()

    def on_node_update(self, node_name: str, delta: dict) -> None:
        now = time.monotonic()
        elapsed = (now - self._last_tick) if self._last_tick is not None else 0.0
        self._last_tick = now

        self._stream.write(f"▸ {node_name} … done ({elapsed:.2f}s)\n")
        formatter = self._formatters.get(node_name)
        extra = formatter(delta) if formatter else []
        for line in extra:
            self._stream.write(f"    {line}\n")
        self._stream.flush()

    def render_final_answer(self, content: str) -> None:
        self._stream.write("\n" + SEPARATOR + "\n")
        self._stream.write(content + "\n")
        self._stream.write(SEPARATOR + "\n\n")
        self._stream.flush()
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `uv run pytest tests/test_cli_streaming.py -v`
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add src/cli/streaming.py tests/test_cli_streaming.py
git commit -m "feat(cli): add node-event streaming renderer with per-node formatters"
```

---

## Task 5: prompt_toolkit 세션 + Fuzzy Completer

**Files:**
- Create: `src/cli/prompt.py`

자동 테스트는 prompt_toolkit Application 통합 비용 대비 효용이 낮아 제외한다 (사양 §테스트 전략에 따라). 빌더 함수는 인자/반환만 검증하는 import smoke로 대체한다.

- [ ] **Step 1: 구현 작성**

`src/cli/prompt.py`:

```python
"""prompt_toolkit 기반 입력 세션과 fuzzy 자동완성 빌더."""

from __future__ import annotations

import sys
from typing import TextIO

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import FuzzyCompleter, WordCompleter

from src.cli.suggestions import flatten


HEADER_TEMPLATE = (
    "사용 가능한 추천 질문 (입력 중 자동 제안)\n"
    "{rows}\n\n"
    "명령: /list <agent>  /reset  /exit  /help\n"
)


def build_completer(suggestions: dict[str, list[str]]) -> FuzzyCompleter:
    """카테고리별 추천 질문을 평면화하여 fuzzy completer로 빌드한다.

    카테고리 라벨은 메뉴 우측 meta 컬럼에 표시된다.
    """
    flat, meta = flatten(suggestions)
    base = WordCompleter(
        flat,
        ignore_case=True,
        sentence=True,
        match_middle=True,
        meta_dict=meta,
    )
    return FuzzyCompleter(base)


def build_prompt_session(suggestions: dict[str, list[str]]) -> PromptSession:
    """fuzzy completer가 결합된 PromptSession을 생성한다."""
    return PromptSession(completer=build_completer(suggestions))


def render_header(
    suggestions: dict[str, list[str]],
    stream: TextIO | None = None,
    preview_per_category: int = 1,
) -> None:
    """REPL 시작 시 카테고리 미리보기 헤더를 출력한다."""
    out = stream if stream is not None else sys.stdout

    if not suggestions:
        out.write(
            "추천 질문이 비어 있습니다 (자유 입력만 가능)\n"
            "명령: /list <agent>  /reset  /exit  /help\n"
        )
        out.flush()
        return

    label_width = max(len(c) for c in suggestions)
    rows: list[str] = []
    for category, items in suggestions.items():
        for text in items[:preview_per_category]:
            rows.append(f"  {category.ljust(label_width)}  · {text}")

    out.write(HEADER_TEMPLATE.format(rows="\n".join(rows)))
    out.flush()
```

- [ ] **Step 2: import smoke**

Run:
```bash
uv run python -c "
from src.cli.prompt import build_completer, build_prompt_session, render_header
sugg = {'math': ['a', 'b'], 'sql': ['c']}
print(type(build_completer(sugg)).__name__)
print(type(build_prompt_session(sugg)).__name__)
import io
buf = io.StringIO(); render_header(sugg, stream=buf); print(buf.getvalue())
"
```
Expected:
```
FuzzyCompleter
PromptSession
사용 가능한 추천 질문 (입력 중 자동 제안)
  math  · a
  sql   · c

명령: /list <agent>  /reset  /exit  /help
```

- [ ] **Step 3: Commit**

```bash
git add src/cli/prompt.py
git commit -m "feat(cli): add prompt_toolkit session with fuzzy completer and header"
```

---

## Task 6: REPL 루프 + chat_history 인계 (통합 테스트)

**Files:**
- Create: `tests/test_cli_app.py`
- Create: `src/cli/app.py`
- Create: `src/cli/__main__.py`

API 결정:

```python
def run_turn(
    app,                                 # CompiledStateGraph
    user_input: str,
    chat_history: list[BaseMessage],
    renderer: NodeRenderer,
) -> tuple[list[BaseMessage], BaseMessage | None]:
    """1턴 실행. (새 chat_history, 마지막 AI 메시지) 반환."""

def run(
    suggestions_path: Path | None = None,
    verbose: bool = False,
) -> None:
    """REPL 진입점. /exit, EOF, KeyboardInterrupt(빈 입력)로 종료."""
```

- [ ] **Step 1: 실패하는 통합 테스트 작성**

`tests/test_cli_app.py`:

```python
import io
from typing import Iterator

from langchain_core.messages import AIMessage, HumanMessage

from src.cli.app import run_turn
from src.cli.streaming import NodeRenderer


class FakeGraph:
    """LangGraph CompiledStateGraph의 stream API를 흉내내는 더블."""

    def __init__(self, scripted_chunks: list[dict]) -> None:
        self._chunks = scripted_chunks
        self.last_state: dict | None = None

    def stream(self, state: dict, stream_mode: str) -> Iterator[dict]:
        assert stream_mode == "updates"
        self.last_state = state
        for chunk in self._chunks:
            yield chunk


def test_run_turn_accumulates_chat_history_from_response_generator() -> None:
    """response_generator delta의 chat_history가 누적되어 다음 turn으로 전달된다."""
    final_ai = AIMessage(content="이번 달 매출은 1,234만원입니다.")
    final_human = HumanMessage(content="이번 달 매출 합계는?")

    fake_chunks = [
        {"query_rewriter": {"messages": [final_human]}},
        {"router": {"next_agent": "sql"}},
        {"sql_agent": {"messages": [AIMessage(content="[SQL 조회 결과]\n…")]}},
        {
            "response_generator": {
                "messages": [final_ai],
                "chat_history": [final_human, final_ai],
            }
        },
    ]
    graph = FakeGraph(fake_chunks)

    buf = io.StringIO()
    renderer = NodeRenderer(stream=buf)

    new_history, last_ai = run_turn(
        graph,
        user_input="매출 알려줘",
        chat_history=[],
        renderer=renderer,
    )

    assert graph.last_state is not None
    assert graph.last_state["messages"][0].content == "매출 알려줘"
    assert graph.last_state["chat_history"] == []

    assert new_history == [final_human, final_ai]
    assert last_ai is final_ai

    out = buf.getvalue()
    assert "query_rewriter" in out
    assert "router" in out
    assert "next_agent: sql" in out
    assert "sql_agent" in out
    assert "이번 달 매출은 1,234만원입니다." in out


def test_run_turn_preserves_existing_history_when_no_response_generator_chunk() -> None:
    """response_generator chunk가 없으면 기존 history를 유지한다."""
    fake_chunks = [
        {"query_rewriter": {"messages": []}},
        {"router": {"next_agent": "FINISH"}},
    ]
    graph = FakeGraph(fake_chunks)
    renderer = NodeRenderer(stream=io.StringIO())

    prior = [HumanMessage(content="prev"), AIMessage(content="ans")]

    new_history, last_ai = run_turn(graph, "hi", prior, renderer)

    assert new_history == prior
    assert last_ai is None
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `uv run pytest tests/test_cli_app.py -v`
Expected: `ModuleNotFoundError: src.cli.app`

- [ ] **Step 3: REPL 모듈 구현**

`src/cli/app.py`:

```python
"""인터랙티브 CLI 진입점: REPL 루프 + chat_history 인계."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from prompt_toolkit import PromptSession

load_dotenv()

from src.cli.commands import handle_command, is_command
from src.cli.prompt import build_prompt_session, render_header
from src.cli.streaming import NodeRenderer
from src.cli.suggestions import load_suggestions
from src.logging import setup_logging
from src.main import build_graph


DEFAULT_SUGGESTIONS_PATH = Path(__file__).resolve().parents[2] / "res" / "suggestions.yaml"


def run_turn(
    app,
    user_input: str,
    chat_history: list[BaseMessage],
    renderer: NodeRenderer,
) -> tuple[list[BaseMessage], BaseMessage | None]:
    """1턴을 실행하고 (새 chat_history, 마지막 AI 메시지)를 반환한다.

    response_generator의 delta에 chat_history가 포함되어 있으면 누적하여 반환한다.
    그렇지 않으면 입력 chat_history를 그대로 반환한다.
    """
    state = {
        "messages": [HumanMessage(content=user_input)],
        "next_agent": "",
        "chat_history": chat_history,
    }

    new_history: list[BaseMessage] = list(chat_history)
    final_ai: BaseMessage | None = None

    renderer.turn_start()
    for chunk in app.stream(state, stream_mode="updates"):
        for node_name, delta in chunk.items():
            renderer.on_node_update(node_name, delta or {})
            if not delta:
                continue
            ch = delta.get("chat_history")
            if ch:
                new_history = new_history + list(ch)
            if node_name == "response_generator":
                msgs = delta.get("messages") or []
                if msgs:
                    final_ai = msgs[-1]

    if isinstance(final_ai, AIMessage):
        renderer.render_final_answer(final_ai.content)

    return new_history, final_ai


def run(
    suggestions_path: Path | None = None,
    verbose: bool = False,
) -> None:
    """REPL 진입점."""
    setup_logging(level=logging.INFO if verbose else logging.WARNING)

    suggestions = load_suggestions(suggestions_path or DEFAULT_SUGGESTIONS_PATH)
    render_header(suggestions)

    session: PromptSession = build_prompt_session(suggestions)
    graph = build_graph()
    renderer = NodeRenderer()

    chat_history: list[BaseMessage] = []
    while True:
        try:
            user_input = session.prompt("질문> ")
        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            print()
            break

        text = user_input.strip()
        if not text:
            continue

        if is_command(text):
            result = handle_command(text, chat_history, suggestions)
            if result.get("output"):
                print(result["output"])
            if "chat_history" in result:
                chat_history = result["chat_history"]
            if result.get("should_exit"):
                break
            continue

        try:
            chat_history, _ = run_turn(graph, text, chat_history, renderer)
        except KeyboardInterrupt:
            print("\n(turn interrupted; chat_history preserved)")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="src.cli", description="Interactive CLI")
    parser.add_argument("--verbose", action="store_true", help="INFO 로그 노출")
    parser.add_argument(
        "--suggestions",
        type=Path,
        default=None,
        help=f"추천 질문 YAML 경로 (기본: {DEFAULT_SUGGESTIONS_PATH})",
    )
    args = parser.parse_args(argv)
    run(suggestions_path=args.suggestions, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: `python -m src.cli` 진입점 추가**

`src/cli/__main__.py`:

```python
from src.cli.app import main

raise SystemExit(main())
```

- [ ] **Step 5: 테스트 실행해서 통과 확인**

Run: `uv run pytest tests/test_cli_app.py -v`
Expected: `2 passed`

- [ ] **Step 6: 전체 테스트 실행 (회귀 확인)**

Run: `uv run pytest -v`
Expected: 기존 테스트 + 신규 테스트 모두 통과 (no regressions).

- [ ] **Step 7: Commit**

```bash
git add src/cli/app.py src/cli/__main__.py tests/test_cli_app.py
git commit -m "feat(cli): add REPL loop with chat_history continuation and python -m src.cli entry"
```

---

## Task 7: 추천 질문 시드 데이터

**Files:**
- Create: `res/suggestions.yaml`

- [ ] **Step 1: 시드 YAML 작성**

`res/suggestions.yaml`:

```yaml
math:
  - "3과 7을 더하고 그 결과에 5를 곱해주세요"
  - "100을 3으로 나눈 결과를 알려주세요"
  - "12 곱하기 25는?"
translate:
  - "Hello, how are you?를 한국어로 번역해주세요"
  - "안녕하세요를 영어로 번역해주세요"
  - "감사합니다를 영어로 자연스럽게 표현해주세요"
sql:
  - "직원 수를 알려주세요"
  - "연봉이 5천만원 이상인 직원은 몇 명인가요?"
  - "이번 달 매출 합계는 얼마인가요?"
  - "지난주 주문 건수를 알려주세요"
  - "부서별 평균 연봉을 알려주세요"
```

- [ ] **Step 2: 로딩 smoke 확인**

Run:
```bash
uv run python -c "
from pathlib import Path
from src.cli.suggestions import load_suggestions, flatten
sugg = load_suggestions(Path('res/suggestions.yaml'))
flat, meta = flatten(sugg)
print(len(flat), 'suggestions in', list(sugg.keys()))
"
```
Expected: `11 suggestions in ['math', 'translate', 'sql']`

- [ ] **Step 3: Commit**

```bash
git add res/suggestions.yaml
git commit -m "chore(cli): seed res/suggestions.yaml with sample queries"
```

---

## Task 8: README에 인터랙티브 CLI 사용법 추가

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Quick Start 섹션 갱신**

`README.md`의 Quick Start 코드 블록을 다음으로 교체.

```markdown
## Quick Start

\`\`\`bash
cp .env.example .env              # OPENAI_API_KEY 설정
uv sync                           # 의존성 설치
uv run python -m src.cli          # 인터랙티브 CLI 실행 (멀티턴 + 추천)
uv run python -m src.main         # 5개 데모 시나리오 일괄 실행
uv run python -m evals.run        # LLM-as-Judge 평가 실행
\`\`\`
```

(README의 기존 데모 시나리오 단락은 그대로 유지)

- [ ] **Step 2: Interactive CLI 섹션 추가**

`README.md`의 `## Documentation` 섹션 직전에 다음 섹션을 삽입.

```markdown
## Interactive CLI

`python -m src.cli`로 멀티턴 대화 REPL을 실행한다.

- **추천 질문 자동 제안** — 시작 시 카테고리별 미리보기를 표시하고, 입력 중 fuzzy 매칭으로 후보를 메뉴에 노출한다. ↑/↓ 또는 Tab으로 채워넣고 편집 후 Enter로 전송.
- **노드 이벤트 스트리밍** — 그래프의 각 노드가 끝날 때마다 한 줄씩 진행 상황을 출력한다.
- **멀티턴 컨텍스트** — `chat_history`가 자동 누적되어 "이거 다시 영어로" 같은 후속 지시어를 해석할 수 있다.

### 슬래시 명령

| 명령 | 동작 |
|------|------|
| `/exit`, `/quit` | 세션 종료 |
| `/reset` | `chat_history` 초기화 |
| `/list` | 모든 카테고리의 추천 질문 출력 |
| `/list <agent>` | 특정 카테고리만 출력 |
| `/help` | 명령 일람 |

### 추천 질문 추가

`res/suggestions.yaml`의 카테고리별 리스트에 항목을 추가한다. 카테고리 키는 `registry.agent_names`(예: `math`, `translate`, `sql`)와 일치시키면 된다. 미스매치 키는 WARNING 로그만 남기고 그대로 사용된다.

### 옵션

\`\`\`bash
uv run python -m src.cli --verbose                 # INFO 로그 노출
uv run python -m src.cli --suggestions path.yaml   # 다른 추천 파일 사용
\`\`\`
```

- [ ] **Step 3: 의존성 섹션 갱신**

`README.md`의 `## Dependencies` 리스트에서 `prompt_toolkit` 한 줄 추가.

```markdown
- `prompt_toolkit` — 인터랙티브 CLI 입력, fuzzy 자동완성
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document interactive CLI usage in README"
```

---

## Self-Review

**1. Spec coverage**

| Spec 요구사항 | Plan 대응 |
|---------------|-----------|
| 사용자 입력 멀티턴 + chat_history 누적 | Task 6 (`run_turn`이 response_generator delta의 chat_history 누적) |
| 카테고리별 YAML 추천 질문 | Task 2 (`load_suggestions`), Task 7 (시드 데이터) |
| 입력 중 fuzzy 자동 제안 + Tab 채움/편집 | Task 5 (`FuzzyCompleter` + `WordCompleter(meta_dict, sentence, match_middle)`) |
| 노드 이벤트 단위 스트리밍 | Task 4 (`NodeRenderer`, `format_*`), Task 6 (`stream(stream_mode="updates")`) |
| 슬래시 명령 (`/exit`, `/reset`, `/list`, `/help`) | Task 3 |
| 시작 헤더 카테고리 미리보기 | Task 5 (`render_header`) |
| 종료 처리 (Ctrl+D, /exit, Ctrl+C) | Task 6 (`run` 루프) |
| 로깅 충돌 회피 (`--verbose`) | Task 6 (`setup_logging(level=WARNING)`) |
| 기존 코드 무변경 | 모든 Task가 신규 파일만 생성/수정 |
| 의도적 단순화 (tool 표시 미반영) | File Structure §사양과의 차이에 명시 |

**2. Placeholder scan**: TBD/TODO/모호 표현 없음. 모든 step에 실제 코드/명령 포함.

**3. Type consistency**:
- `load_suggestions(path) -> dict[str, list[str]]` — Task 2/5/6에서 동일하게 사용
- `flatten(suggestions) -> (list[str], dict[str, str])` — Task 2/5에서 일치
- `is_command(text) -> bool`, `handle_command(text, chat_history, suggestions) -> CommandResult` — Task 3/6에서 일치
- `NodeRenderer(stream, formatters)` 시그니처 — Task 4/6에서 일치
- `run_turn(app, user_input, chat_history, renderer) -> (list[BaseMessage], BaseMessage | None)` — Task 6 내부 일치

추가 이슈 없음.
