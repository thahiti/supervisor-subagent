# templated_sql 에이전트 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사전 정의된 SQL 템플릿에 사용자가 명시한 변수만 채워 실행하는 구조화 SQL 조회 에이전트 `templated_sql`을 추가한다. 기존 자유형 `sql` 에이전트와 공존하며, 라우터가 자동 합성된 description으로 두 에이전트를 구분한다.

**Architecture:** `src/templated_sql_agent/` 신규 모듈 — registry/templates/render/prompt/agent 5파일로 분리(도메인 무지 ↔ 인식). 단일 LLM 호출로 4-action(`execute_main`/`ask_clarification`/`execute_lookup`/`no_match`)을 분류하고 분기 실행. 멀티턴 흐름은 기존 query_rewriter가 처리하므로 에이전트는 chat_history를 보지 않음. 메인 SQL은 sqlite3 named-parameter 바인딩으로 안전 실행하고, 후보값 조회용 lookup_sql은 정적 등록 SELECT만 허용.

**Tech Stack:** Python 3.11+, LangGraph, langchain-core, sqlite3, pytest, dataclasses. 기존 `src/sql_agent/backend/SqlExecutor` 재활용.

**Spec:** `docs/superpowers/specs/2026-05-11-templated-sql-agent-design.md`

---

## Task 의존성 그래프

```
T1 (executor params 확장) ─┐
                            ├─→ T8 (agent.py)
T2 (registry 데이터 모델) ──┼─→ T3 (등록 검증)
                            │   ↓
                            │   T4 (build_*_for_llm)
                            │   ↓
                            ├─→ T5 (render.py)
                            ├─→ T6 (prompt.py)
                            └─→ T7 (templates.py) ─→ T8

T9 (wiring) ← T8
T10 (query_rewriter 보강)  — 독립
T11 (main.py 시나리오 F)   ← T9
T12 (suggestions.yaml)      — 독립
T13 (README 업데이트)       — 마지막
```

T1, T2, T10, T12는 서로 독립적이며 병렬 가능. 단순화를 위해 순서대로 진행한다.

---

## Task 1: SqlExecutor.execute()에 named-param 바인딩 인자 추가

기존 시그니처 `execute(query)`를 `execute(query, params=None)`로 확장한다. 기본값이 None이므로 기존 호출자(`src/sql_agent/tools.py:27`의 `execute_sql`)는 영향을 받지 않는다.

**Files:**
- Modify: `src/sql_agent/backend/executor.py:71-87`
- Modify: `src/sql_agent/backend/executor.py:139-162` (`_run_query`)
- Test: `tests/test_sql_backend.py` (회귀 + 신규)

- [ ] **Step 1: Write the failing test**

기존 `tests/test_sql_backend.py`의 `TestExecute` 클래스 끝(라인 153 직후)에 다음 케이스를 추가한다.

```python
    def test_execute_with_named_params(self, executor: SqlExecutor) -> None:
        r = executor.execute(
            "SELECT name FROM items WHERE id = :id",
            {"id": 2},
        )
        assert r["ok"]
        assert [row[0] for row in r["rows"]] == ["banana"]

    def test_execute_with_params_none_behaves_like_before(
        self, executor: SqlExecutor,
    ) -> None:
        r = executor.execute("SELECT name FROM items ORDER BY id")
        assert r["ok"]
        assert [row[0] for row in r["rows"]] == ["apple", "banana", "cherry"]

    def test_execute_with_params_isolates_injection(
        self, executor: SqlExecutor,
    ) -> None:
        # SQL 문자열 안에 직접 박지 않고 바인딩으로 전달하므로 인젝션 패턴이
        # 데이터 값으로만 취급된다.
        r = executor.execute(
            "SELECT name FROM items WHERE name = :n",
            {"n": "'; DROP TABLE items; --"},
        )
        assert r["ok"]
        assert r["rows"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sql_backend.py::TestExecute::test_execute_with_named_params -v`
Expected: FAIL (`execute()`가 두 번째 인자를 받지 못해 `TypeError`).

- [ ] **Step 3: Update SqlExecutor.execute() signature**

`src/sql_agent/backend/executor.py`의 `execute` 메서드(71-87)를 다음과 같이 교체.

```python
    def execute(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """쿼리를 검증하고 실행하여 결과를 반환한다.

        Args:
            query: 실행할 SQL 쿼리 문자열. params를 사용하는 경우 :name 형식
                named placeholder를 사용한다.
            params: sqlite3 named-parameter 바인딩 dict. None이면 미바인딩 실행.

        Returns:
            ExecutionResult. 실패 시 ok=False와 error 메시지를 포함한다.
        """
        try:
            validate_select_only(query)
        except UnsafeSqlError as exc:
            logger.warning("SQL 안전성 검증 실패: %s", exc)
            return _error_result(str(exc))

        safe_query = inject_limit_if_missing(query, self._row_limit)
        return self._run_query(safe_query, params)
```

- [ ] **Step 4: Update _run_query to pass params**

`src/sql_agent/backend/executor.py`의 `_run_query`(139-162)를 다음과 같이 교체.

```python
    def _run_query(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        try:
            with self._connect() as conn:
                cursor = conn.execute(query, params or {})
                rows = cursor.fetchall()
                columns = [d[0] for d in cursor.description] if cursor.description else []
        except sqlite3.Error as exc:
            logger.warning("SQL 실행 오류: %s | query=%s", exc, query[:120])
            return _error_result(f"SQLite 오류: {exc}")
        except FileNotFoundError as exc:
            logger.warning("DB 파일 없음: %s", exc)
            return _error_result(str(exc))

        markdown = to_markdown_table(columns, rows)
        logger.info(
            "SQL 실행 성공: rows=%d, query=%s", len(rows), query[:120],
        )
        return ExecutionResult(
            ok=True,
            columns=columns,
            rows=rows,
            markdown=markdown,
            error=None,
        )
```

`list_tables`(89)와 `get_schema`(101)는 `_run_query(query)` 형태로 호출하므로 params=None 기본값이 적용되어 변경 불필요.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_sql_backend.py -v`
Expected: 전체 PASS. 기존 테스트도 회귀 없이 통과.

- [ ] **Step 6: Commit**

```bash
git add src/sql_agent/backend/executor.py tests/test_sql_backend.py
git commit -m "$(cat <<'EOF'
feat(sql-backend): add named-param binding to SqlExecutor.execute

execute(query, params=None) 시그니처로 확장. params=None이면 기존 동작과
동등하여 sql_agent의 execute_sql 도구는 영향을 받지 않는다. templated_sql
에이전트가 사용자 입력으로 받은 변수를 SQL injection 없이 바인딩하기 위한
선행 작업.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: registry.py — 데이터 모델 + 기본 TemplateRegistry

`TemplateVariable`/`SqlTemplate` dataclass와 `TemplateRegistry`의 기본 인터페이스(`register` 최소판, `get`, `templates` property)를 작성. 등록 검증은 Task 3에서 추가.

**Files:**
- Create: `src/templated_sql_agent/__init__.py` (빈 파일로 시작 — Task 9에서 wiring)
- Create: `src/templated_sql_agent/registry.py`
- Test: `tests/test_templated_sql_registry.py`

- [ ] **Step 1: Create empty package init**

`src/templated_sql_agent/__init__.py` 를 빈 파일로 생성. Task 9에서 wiring을 채운다.

```python
```

- [ ] **Step 2: Write the failing test**

`tests/test_templated_sql_registry.py` 신규 작성.

```python
"""TemplateRegistry 단위 테스트."""

from __future__ import annotations

import pytest

from src.templated_sql_agent.registry import (
    SqlTemplate,
    TemplateRegistry,
    TemplateVariable,
)


def _make_template(template_id: str = "t1") -> SqlTemplate:
    return SqlTemplate(
        id=template_id,
        intent="테스트 의도",
        sql="SELECT * FROM t WHERE x = :x",
        variables=(
            TemplateVariable(
                name="x",
                description="테스트 변수",
                sql_type="int",
            ),
        ),
    )


class TestBasicRegistration:
    def test_register_and_get(self) -> None:
        reg = TemplateRegistry()
        t = _make_template()
        reg.register(t)
        assert reg.get("t1") is t

    def test_get_missing_returns_none(self) -> None:
        reg = TemplateRegistry()
        assert reg.get("nope") is None

    def test_templates_preserves_order(self) -> None:
        reg = TemplateRegistry()
        reg.register(_make_template("a"))
        reg.register(_make_template("b"))
        reg.register(_make_template("c"))
        assert [t.id for t in reg.templates] == ["a", "b", "c"]

    def test_templates_returns_defensive_copy(self) -> None:
        reg = TemplateRegistry()
        reg.register(_make_template("a"))
        got = reg.templates
        got.clear()
        assert [t.id for t in reg.templates] == ["a"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_templated_sql_registry.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.templated_sql_agent.registry'`).

- [ ] **Step 4: Implement registry.py (minimal)**

`src/templated_sql_agent/registry.py`:

```python
"""SQL 템플릿 레지스트리.

도메인 무지: 어떤 SQL 템플릿이든 등록할 수 있고, 등록 검증과 조회 인터페이스만
제공한다. 실제 도메인 템플릿은 templates.py에서 정의한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TemplateVariable:
    """SQL 템플릿의 단일 변수 정의.

    Attributes:
        name: SQL named placeholder 키 (예: "store_id").
        description: 사용자/LLM 양쪽에 노출되는 의미.
        sql_type: coercion + 안전 검증용 타입.
            - "int": 정수 ID 또는 수량
            - "text": 카테고리/도시명/주문 상태 같은 문자열 값
            - "date": YYYY-MM-DD 또는 YYYY-MM 형식 문자열
        lookup_sql: 후보값 조회용 SELECT (정적 등록).
            None이면 후보값 조회 불가.
    """

    name: str
    description: str
    sql_type: Literal["int", "text", "date"]
    lookup_sql: str | None = None


@dataclass(frozen=True)
class SqlTemplate:
    """단일 SQL 템플릿 정의.

    Attributes:
        id: 라우팅·로깅 키 (예: "product_stock").
        intent: 라우터 description/카탈로그 표시용 한 줄.
        sql: :name 형식 named placeholder만 사용.
        variables: 템플릿에 등장하는 모든 변수 (튜플로 hashable 보장).
    """

    id: str
    intent: str
    sql: str
    variables: tuple[TemplateVariable, ...]


class TemplateRegistry:
    """SQL 템플릿 등록·조회 레지스트리."""

    def __init__(self) -> None:
        self._templates: list[SqlTemplate] = []
        self._by_id: dict[str, SqlTemplate] = {}

    def register(self, template: SqlTemplate) -> None:
        """템플릿을 레지스트리에 등록한다."""
        self._templates.append(template)
        self._by_id[template.id] = template

    @property
    def templates(self) -> list[SqlTemplate]:
        """등록된 모든 템플릿을 등록 순서대로 반환 (방어 복사)."""
        return list(self._templates)

    def get(self, template_id: str) -> SqlTemplate | None:
        """id로 템플릿을 조회. 없으면 None."""
        return self._by_id.get(template_id)


template_registry = TemplateRegistry()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_templated_sql_registry.py::TestBasicRegistration -v`
Expected: 4개 모두 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/templated_sql_agent/__init__.py src/templated_sql_agent/registry.py tests/test_templated_sql_registry.py
git commit -m "$(cat <<'EOF'
feat(templated-sql): add SqlTemplate / TemplateVariable / TemplateRegistry

도메인 무지의 데이터 모델과 기본 레지스트리 인터페이스. 등록·조회·순서 보존
+ 방어 복사. 등록 검증과 빌더 메서드는 후속 커밋에서 추가.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: TemplateRegistry — 등록 검증 (중복 id / placeholder 불일치 / lookup_sql SELECT-only)

import time에 잘못된 템플릿이 즉시 ValueError로 실패하도록 `register()`에 세 가지 검증을 추가한다.

**Files:**
- Modify: `src/templated_sql_agent/registry.py`
- Test: `tests/test_templated_sql_registry.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_templated_sql_registry.py` 끝에 다음 클래스를 추가.

```python
class TestRegistrationValidation:
    def test_rejects_duplicate_id(self) -> None:
        reg = TemplateRegistry()
        reg.register(_make_template("dup"))
        with pytest.raises(ValueError, match="중복"):
            reg.register(_make_template("dup"))

    def test_rejects_placeholder_mismatch_missing_var(self) -> None:
        reg = TemplateRegistry()
        bad = SqlTemplate(
            id="bad",
            intent="i",
            sql="SELECT * FROM t WHERE x = :x AND y = :y",
            variables=(
                TemplateVariable(name="x", description="d", sql_type="int"),
            ),
        )
        with pytest.raises(ValueError, match="placeholder"):
            reg.register(bad)

    def test_rejects_placeholder_mismatch_extra_var(self) -> None:
        reg = TemplateRegistry()
        bad = SqlTemplate(
            id="bad",
            intent="i",
            sql="SELECT * FROM t WHERE x = :x",
            variables=(
                TemplateVariable(name="x", description="d", sql_type="int"),
                TemplateVariable(name="y", description="d", sql_type="int"),
            ),
        )
        with pytest.raises(ValueError, match="placeholder"):
            reg.register(bad)

    def test_rejects_non_select_lookup_sql(self) -> None:
        reg = TemplateRegistry()
        bad = SqlTemplate(
            id="bad",
            intent="i",
            sql="SELECT * FROM t WHERE x = :x",
            variables=(
                TemplateVariable(
                    name="x",
                    description="d",
                    sql_type="int",
                    lookup_sql="DELETE FROM t",
                ),
            ),
        )
        with pytest.raises(ValueError, match="SELECT"):
            reg.register(bad)

    def test_accepts_select_lookup_sql(self) -> None:
        reg = TemplateRegistry()
        ok = SqlTemplate(
            id="ok",
            intent="i",
            sql="SELECT * FROM t WHERE x = :x",
            variables=(
                TemplateVariable(
                    name="x",
                    description="d",
                    sql_type="int",
                    lookup_sql="SELECT id, name FROM t ORDER BY name",
                ),
            ),
        )
        reg.register(ok)
        assert reg.get("ok") is ok

    def test_validation_failure_does_not_register(self) -> None:
        reg = TemplateRegistry()
        bad = SqlTemplate(
            id="bad",
            intent="i",
            sql="SELECT * FROM t WHERE x = :x AND y = :y",
            variables=(
                TemplateVariable(name="x", description="d", sql_type="int"),
            ),
        )
        with pytest.raises(ValueError):
            reg.register(bad)
        assert reg.get("bad") is None
        assert reg.templates == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_templated_sql_registry.py::TestRegistrationValidation -v`
Expected: 6개 모두 FAIL (검증 로직 미구현이므로 ValueError가 발생하지 않거나 등록이 성공함).

- [ ] **Step 3: Implement validation**

`src/templated_sql_agent/registry.py`에 다음을 추가/교체.

파일 상단의 import를 다음으로 교체:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from src.sql_agent.backend.safety import UnsafeSqlError, validate_select_only
```

`register` 메서드를 다음으로 교체:

```python
    def register(self, template: SqlTemplate) -> None:
        """템플릿을 레지스트리에 등록한다.

        검증 실패 시 ValueError를 즉시 발생시킨다. 검증 항목:
            1. id 중복 금지
            2. sql의 :name placeholder 집합과 variables의 name 집합이 정확히 일치
            3. 각 lookup_sql은 SELECT-only (백엔드 safety 재활용)
        """
        if template.id in self._by_id:
            raise ValueError(f"중복 템플릿 id: {template.id}")

        placeholders = set(re.findall(r":(\w+)", template.sql))
        var_names = {v.name for v in template.variables}
        if placeholders != var_names:
            raise ValueError(
                f"템플릿 '{template.id}': sql placeholder {sorted(placeholders)} "
                f"≠ variables {sorted(var_names)}"
            )

        for v in template.variables:
            if v.lookup_sql is not None:
                try:
                    validate_select_only(v.lookup_sql)
                except UnsafeSqlError as exc:
                    raise ValueError(
                        f"템플릿 '{template.id}' 변수 '{v.name}'의 lookup_sql은 "
                        f"SELECT-only여야 합니다: {exc}"
                    ) from exc

        self._templates.append(template)
        self._by_id[template.id] = template
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_templated_sql_registry.py -v`
Expected: 전체 PASS (기본 + 검증 모두).

- [ ] **Step 5: Commit**

```bash
git add src/templated_sql_agent/registry.py tests/test_templated_sql_registry.py
git commit -m "$(cat <<'EOF'
feat(templated-sql): validate template at registration time

register() 시점에 (1) id 중복 (2) :name placeholder ↔ variables 일치
(3) lookup_sql SELECT-only를 검증. import time에 잘못된 템플릿이 즉시
ValueError로 실패하므로 런타임에 사용자 앞에서 깨지지 않는다.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: TemplateRegistry — build_router_description / build_catalog_for_llm

라우터 description과 LLM 시스템 프롬프트의 템플릿 카탈로그 섹션을 자동 합성한다.

**Files:**
- Modify: `src/templated_sql_agent/registry.py`
- Test: `tests/test_templated_sql_registry.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_templated_sql_registry.py` 끝에 다음 클래스를 추가.

```python
class TestBuilders:
    def _populated(self) -> TemplateRegistry:
        reg = TemplateRegistry()
        reg.register(SqlTemplate(
            id="t1",
            intent="첫 번째 의도",
            sql="SELECT * FROM t WHERE x = :x",
            variables=(
                TemplateVariable(
                    name="x",
                    description="x 설명",
                    sql_type="int",
                    lookup_sql="SELECT id, name FROM t ORDER BY name",
                ),
            ),
        ))
        reg.register(SqlTemplate(
            id="t2",
            intent="두 번째 의도",
            sql="SELECT * FROM t WHERE y = :y",
            variables=(
                TemplateVariable(
                    name="y",
                    description="y 설명",
                    sql_type="text",
                ),
            ),
        ))
        return reg

    def test_router_description_contains_header_and_intents(self) -> None:
        desc = self._populated().build_router_description()
        assert "사전 정의된 SQL 템플릿" in desc
        assert "후보값" in desc
        assert "첫 번째 의도" in desc
        assert "두 번째 의도" in desc

    def test_router_description_empty_registry(self) -> None:
        desc = TemplateRegistry().build_router_description()
        # 빈 레지스트리여도 헤더는 있고 의도 항목만 비어 있다.
        assert "사전 정의된 SQL 템플릿" in desc

    def test_catalog_for_llm_includes_template_id_and_variables(self) -> None:
        cat = self._populated().build_catalog_for_llm()
        assert "template_id: t1" in cat
        assert "template_id: t2" in cat
        assert "x (int)" in cat
        assert "y (text)" in cat
        assert "x 설명" in cat
        assert "y 설명" in cat

    def test_catalog_indicates_lookup_availability(self) -> None:
        cat = self._populated().build_catalog_for_llm()
        # x는 lookup_sql이 있고, y는 없다.
        # "후보값 조회 가능" / "후보값 조회 불가" 등으로 표기.
        assert "후보값 조회 가능" in cat
        assert "후보값 조회 불가" in cat

    def test_catalog_does_not_leak_lookup_sql_body(self) -> None:
        """lookup_sql 본문은 LLM에 노출되지 않아야 한다."""
        cat = self._populated().build_catalog_for_llm()
        assert "ORDER BY name" not in cat
        assert "SELECT id, name FROM t" not in cat
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_templated_sql_registry.py::TestBuilders -v`
Expected: 5개 모두 FAIL (메서드 미구현 → `AttributeError`).

- [ ] **Step 3: Implement builders**

`src/templated_sql_agent/registry.py`의 `TemplateRegistry` 클래스 끝에 다음 두 메서드를 추가.

```python
    def build_router_description(self) -> str:
        """라우터 description으로 사용할 문자열을 합성한다.

        헤더 + 등록된 모든 템플릿의 intent 불릿 리스트.
        """
        header = (
            "사전 정의된 SQL 템플릿 기반의 데이터 조회를 처리합니다. 각 조회에 "
            "필요한 변수의 후보값을 사용자에게 안내하고, 사용자 동의 시 후보값을 "
            "조회해 표로 제시하는 흐름도 이 에이전트가 처리합니다."
        )
        if not self._templates:
            return header

        lines = [header, "다음 종류의 질의를 다룹니다:"]
        for t in self._templates:
            lines.append(f"- {t.intent}")
        return "\n".join(lines)

    def build_catalog_for_llm(self) -> str:
        """templated_sql 에이전트 LLM 시스템 프롬프트의 템플릿 카탈로그 섹션.

        각 템플릿의 id/intent/변수 스키마(name, sql_type, description,
        lookup 가능 여부)를 포함한다. lookup_sql 본문은 노출하지 않는다.
        """
        if not self._templates:
            return "(등록된 템플릿 없음)"

        blocks: list[str] = []
        for t in self._templates:
            lines = [
                f"### template_id: {t.id}",
                f"의도: {t.intent}",
                "변수:",
            ]
            for v in t.variables:
                lookup_tag = "후보값 조회 가능" if v.lookup_sql else "후보값 조회 불가"
                lines.append(
                    f"- {v.name} ({v.sql_type}): {v.description}. {lookup_tag}."
                )
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_templated_sql_registry.py -v`
Expected: 전체 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/templated_sql_agent/registry.py tests/test_templated_sql_registry.py
git commit -m "$(cat <<'EOF'
feat(templated-sql): add description/catalog builders to TemplateRegistry

build_router_description은 라우터 시스템 프롬프트에 주입할 워커 설명을,
build_catalog_for_llm은 templated_sql LLM 시스템 프롬프트의 템플릿 카탈로그
섹션을 자동 합성한다. lookup_sql 본문은 LLM에 노출되지 않는다.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: render.py — 변수 검증 + 타입 coercion + (sql, params) 생성

`render(template, args)` 함수로 LLM이 추출한 인자를 안전하게 sqlite3 named-param dict로 변환한다.

**Files:**
- Create: `src/templated_sql_agent/render.py`
- Test: `tests/test_templated_sql_render.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_templated_sql_render.py` 신규:

```python
"""render 단위 테스트."""

from __future__ import annotations

import pytest

from src.templated_sql_agent.registry import SqlTemplate, TemplateVariable
from src.templated_sql_agent.render import TemplateRenderError, render


def _t(*vars_: TemplateVariable, sql: str | None = None) -> SqlTemplate:
    placeholder_part = " AND ".join(f"{v.name} = :{v.name}" for v in vars_)
    return SqlTemplate(
        id="t",
        intent="i",
        sql=sql or f"SELECT * FROM x WHERE {placeholder_part}",
        variables=vars_,
    )


class TestRenderHappy:
    def test_int_coercion(self) -> None:
        t = _t(TemplateVariable(name="id", description="d", sql_type="int"))
        sql, params = render(t, {"id": "42"})
        assert ":id" in sql
        assert params == {"id": 42}

    def test_int_already_int(self) -> None:
        t = _t(TemplateVariable(name="id", description="d", sql_type="int"))
        sql, params = render(t, {"id": 5})
        assert params == {"id": 5}

    def test_text_strip(self) -> None:
        t = _t(TemplateVariable(name="c", description="d", sql_type="text"))
        _, params = render(t, {"c": "  hello  "})
        assert params == {"c": "hello"}

    def test_date_full(self) -> None:
        t = _t(TemplateVariable(name="d", description="d", sql_type="date"))
        _, params = render(t, {"d": "2026-05-11"})
        assert params == {"d": "2026-05-11"}

    def test_date_month_only(self) -> None:
        t = _t(TemplateVariable(name="d", description="d", sql_type="date"))
        _, params = render(t, {"d": "2026-05"})
        assert params == {"d": "2026-05"}

    def test_multiple_variables(self) -> None:
        t = _t(
            TemplateVariable(name="a", description="d", sql_type="int"),
            TemplateVariable(name="b", description="d", sql_type="text"),
        )
        sql, params = render(t, {"a": 1, "b": "x"})
        assert params == {"a": 1, "b": "x"}


class TestRenderErrors:
    def test_missing_arg(self) -> None:
        t = _t(TemplateVariable(name="id", description="d", sql_type="int"))
        with pytest.raises(TemplateRenderError, match="누락"):
            render(t, {})

    def test_int_cast_failure(self) -> None:
        t = _t(TemplateVariable(name="id", description="d", sql_type="int"))
        with pytest.raises(TemplateRenderError, match="int"):
            render(t, {"id": "abc"})

    def test_text_empty_after_strip(self) -> None:
        t = _t(TemplateVariable(name="c", description="d", sql_type="text"))
        with pytest.raises(TemplateRenderError, match="text"):
            render(t, {"c": "   "})

    def test_date_wrong_separator(self) -> None:
        t = _t(TemplateVariable(name="d", description="d", sql_type="date"))
        with pytest.raises(TemplateRenderError, match="date"):
            render(t, {"d": "2026/05/11"})

    def test_date_natural_language(self) -> None:
        t = _t(TemplateVariable(name="d", description="d", sql_type="date"))
        with pytest.raises(TemplateRenderError, match="date"):
            render(t, {"d": "오늘"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_templated_sql_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.templated_sql_agent.render'`.

- [ ] **Step 3: Implement render.py**

`src/templated_sql_agent/render.py`:

```python
"""SQL 템플릿 변수 검증 + 타입 coercion + sqlite3 named-param 바인딩 생성."""

from __future__ import annotations

import re
from typing import Any

from src.templated_sql_agent.registry import SqlTemplate, TemplateVariable

_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


class TemplateRenderError(ValueError):
    """렌더링 단계에서 변수 누락·타입 불일치 등의 사유로 실패했을 때."""


def render(
    template: SqlTemplate,
    args: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """args를 검증·정제해 (sql, params) 튜플을 반환한다.

    Args:
        template: 렌더링 대상 SqlTemplate.
        args: 변수 이름 → 값 매핑. 일반적으로 LLM이 추출한 값.

    Returns:
        (sql_with_named_placeholders, params_dict). sqlite3.execute(sql, params)
        호출에 그대로 사용 가능.

    Raises:
        TemplateRenderError: 변수 누락 또는 타입 불일치.
    """
    params: dict[str, Any] = {}
    for var in template.variables:
        if var.name not in args:
            raise TemplateRenderError(f"누락된 변수: {var.name}")
        params[var.name] = _coerce(args[var.name], var)
    return template.sql, params


def _coerce(value: Any, var: TemplateVariable) -> Any:
    """variable.sql_type에 따른 coercion + 형식 검증."""
    if var.sql_type == "int":
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise TemplateRenderError(
                f"변수 '{var.name}'은(는) int여야 합니다. 입력값: {value!r}"
            ) from exc

    if var.sql_type == "text":
        text = str(value).strip()
        if not text:
            raise TemplateRenderError(
                f"변수 '{var.name}'(text)은(는) 비어 있을 수 없습니다."
            )
        return text

    if var.sql_type == "date":
        text = str(value).strip()
        if not _DATE_RE.match(text):
            raise TemplateRenderError(
                f"변수 '{var.name}'은(는) YYYY-MM 또는 YYYY-MM-DD 형식의 date "
                f"여야 합니다. 입력값: {value!r}"
            )
        return text

    raise TemplateRenderError(f"알 수 없는 sql_type: {var.sql_type}")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_templated_sql_render.py -v`
Expected: 전체 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/templated_sql_agent/render.py tests/test_templated_sql_render.py
git commit -m "$(cat <<'EOF'
feat(templated-sql): add render() for variable validation and binding

LLM이 추출한 인자를 SqlTemplate에 안전하게 매핑해 (sql, params) 튜플을
반환한다. int/text/date 각각의 coercion·형식 검증이 적용되며, 실패 시
TemplateRenderError로 그래프 안에서 사용자 안내로 변환된다.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: prompt.py — 시스템 프롬프트 빌더

action 분류 + 변수 추출용 LLM 시스템 프롬프트 빌더. 카탈로그는 `template_registry.build_catalog_for_llm()` 결과를 주입한다.

**Files:**
- Create: `src/templated_sql_agent/prompt.py`
- Test: `tests/test_templated_sql_agent.py` (이 파일은 Task 8에서 확장하지만 prompt 검증은 여기서 시작)

- [ ] **Step 1: Write the failing test**

`tests/test_templated_sql_agent.py` 신규:

```python
"""templated_sql 에이전트 단위 테스트.

LLM 호출 없이 프롬프트 합성과 wrapper 분기 로직을 검증한다.
"""

from __future__ import annotations

from src.templated_sql_agent.prompt import build_system_prompt
from src.templated_sql_agent.registry import (
    SqlTemplate,
    TemplateRegistry,
    TemplateVariable,
)


class TestPrompt:
    def _registry(self) -> TemplateRegistry:
        reg = TemplateRegistry()
        reg.register(SqlTemplate(
            id="sample",
            intent="샘플 의도",
            sql="SELECT * FROM t WHERE x = :x",
            variables=(
                TemplateVariable(
                    name="x", description="x 설명", sql_type="int",
                    lookup_sql="SELECT id, name FROM t ORDER BY name",
                ),
            ),
        ))
        return reg

    def test_prompt_lists_four_actions(self) -> None:
        prompt = build_system_prompt(self._registry())
        for action in ("execute_main", "ask_clarification", "execute_lookup", "no_match"):
            assert action in prompt

    def test_prompt_embeds_catalog(self) -> None:
        prompt = build_system_prompt(self._registry())
        assert "template_id: sample" in prompt
        assert "샘플 의도" in prompt
        assert "x (int)" in prompt

    def test_prompt_emphasizes_no_guessing(self) -> None:
        prompt = build_system_prompt(self._registry())
        # 변수 임의 추측 금지가 명시되어야 한다.
        assert "추측" in prompt or "임의" in prompt

    def test_prompt_specifies_json_output(self) -> None:
        prompt = build_system_prompt(self._registry())
        assert "JSON" in prompt
        assert '"action"' in prompt
        assert '"template_id"' in prompt
        assert '"extracted"' in prompt
        assert '"lookup_vars"' in prompt
        assert '"clarification"' in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_templated_sql_agent.py::TestPrompt -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement prompt.py**

`src/templated_sql_agent/prompt.py`:

```python
"""templated_sql 에이전트 시스템 프롬프트 빌더."""

from __future__ import annotations

from src.templated_sql_agent.registry import TemplateRegistry


_SYSTEM_PROMPT_TEMPLATE = """\
당신은 사전 정의된 SQL 템플릿 기반의 조회를 수행하는 에이전트입니다.
한 번의 호출에서 다음 중 정확히 하나의 action을 결정해 JSON으로 반환하세요.

## action 정의

- "execute_main": 사용자가 매핑된 템플릿의 모든 변수 값을 명시했고, 그 값을
  그대로 사용해 메인 SQL을 실행할 수 있을 때.
- "ask_clarification": 매핑된 템플릿이 있지만 필요한 변수 일부 또는 전부가
  사용자 메시지에서 추출되지 않을 때. 어떤 변수가 부족한지 자연어로 묻고,
  해당 변수에 후보값 조회가 가능하면 "전체 ~ 목록을 보여드릴까요?" 형태로
  제안하세요. SQL을 사용자에게 노출하지 마세요.
- "execute_lookup": 사용자가 직전 ask_clarification 제안에 동의하여(예:
  "응", "보여줘", "전체 지점 목록 보여줘") 변수 후보값을 조회해 달라고 한
  경우. 어떤 변수의 후보값을 조회할지 lookup_vars 리스트로 명시.
- "no_match": 어떤 템플릿과도 의미가 일치하지 않을 때. 사용자에게 처리 가능한
  질의 종류를 안내.

## 처리 규칙

- 변수 값을 임의로 추측하지 마세요. 사용자가 명시하지 않았으면 missing입니다.
- 디폴트(예: "전체", "all")를 임의로 적용하지 마세요. 항상 사용자의 명시적
  선택을 받아야 합니다.
- lookup_sql 본문은 보이지 않습니다. 후보값 조회 가능 여부만 카탈로그에
  표시됩니다. 후보값 조회 불가 변수는 직접 값을 받아야 합니다.

## 출력 형식

정확히 아래 JSON 한 객체만 반환하세요. 다른 텍스트나 ```json 블록 펜스도
넣지 마세요.

{{
  "action": "execute_main|ask_clarification|execute_lookup|no_match",
  "template_id": "<id 또는 null>",
  "extracted": {{"<var>": <value>, ...}},
  "lookup_vars": ["<var>", ...],
  "clarification": "<사용자에게 보여줄 자연어. ask_clarification/no_match일 때만>"
}}

## 처리 가능한 질의 템플릿

{catalog}
"""


def build_system_prompt(registry: TemplateRegistry) -> str:
    """레지스트리에 등록된 템플릿을 반영해 시스템 프롬프트를 합성한다."""
    return _SYSTEM_PROMPT_TEMPLATE.format(catalog=registry.build_catalog_for_llm())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_templated_sql_agent.py::TestPrompt -v`
Expected: 4개 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/templated_sql_agent/prompt.py tests/test_templated_sql_agent.py
git commit -m "$(cat <<'EOF'
feat(templated-sql): add LLM system prompt builder

build_system_prompt이 4가지 action 정의 + 처리 규칙 + 출력 JSON 스키마 +
등록된 템플릿 카탈로그를 합성한다. lookup_sql 본문은 LLM에 노출되지 않고,
"후보값 조회 가능" 여부만 카탈로그에 표시된다.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: templates.py — v1 도메인 카탈로그 5개

ecommerce.db 기반 5개 템플릿을 모듈 레벨에서 등록한다. 모듈 import만으로 등록이 트리거된다.

**Files:**
- Create: `src/templated_sql_agent/templates.py`
- Test: `tests/test_templated_sql_templates.py`

- [ ] **Step 1: Write the failing test**

`tests/test_templated_sql_templates.py` 신규:

```python
"""templates.py 등록 검증.

import 시 등록 검증이 통과하고 5개 템플릿이 모두 들어가는지 확인한다.
"""

from __future__ import annotations

from src.templated_sql_agent.registry import template_registry
import src.templated_sql_agent.templates  # noqa: F401 - 등록 트리거


EXPECTED_IDS = {
    "dept_avg_salary",
    "product_stock",
    "category_top_n_revenue",
    "customer_orders",
    "monthly_order_count",
}


class TestTemplatesRegistered:
    def test_all_expected_ids_present(self) -> None:
        ids = {t.id for t in template_registry.templates}
        assert EXPECTED_IDS.issubset(ids)

    def test_each_has_nonempty_intent_and_sql(self) -> None:
        for t in template_registry.templates:
            if t.id not in EXPECTED_IDS:
                continue
            assert t.intent.strip()
            assert t.sql.strip().lower().startswith("select")
            assert len(t.variables) >= 1

    def test_lookup_variables_have_select_only_sql(self) -> None:
        # 등록 검증이 lookup_sql을 SELECT-only로 강제하지만,
        # 추가로 명시 검증한다.
        for t in template_registry.templates:
            for v in t.variables:
                if v.lookup_sql is None:
                    continue
                normalized = v.lookup_sql.strip().lower()
                assert normalized.startswith("select") or normalized.startswith("with")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_templated_sql_templates.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.templated_sql_agent.templates'`).

- [ ] **Step 3: Implement templates.py**

`src/templated_sql_agent/templates.py`:

```python
"""ecommerce.db 도메인 SQL 템플릿 카탈로그.

모듈 import 시 부수효과로 template_registry에 모든 템플릿이 등록된다.
다른 도메인을 추가하려면 이 파일과 동일한 형식의 새 모듈을 작성하고,
패키지 __init__.py에서 import하면 된다.
"""

from __future__ import annotations

from src.templated_sql_agent.registry import (
    SqlTemplate,
    TemplateVariable,
    template_registry,
)

# 부서별 평균 급여
template_registry.register(SqlTemplate(
    id="dept_avg_salary",
    intent="특정 부서의 평균 급여 조회",
    sql=(
        "SELECT d.name AS department, AVG(e.salary) AS avg_salary, "
        "COUNT(e.id) AS headcount "
        "FROM employees e "
        "JOIN departments d ON e.dept_id = d.id "
        "WHERE d.id = :dept_id "
        "GROUP BY d.name"
    ),
    variables=(
        TemplateVariable(
            name="dept_id",
            description="조회 대상 부서의 id",
            sql_type="int",
            lookup_sql="SELECT id, name, location FROM departments ORDER BY name",
        ),
    ),
))

# 특정 제품 재고
template_registry.register(SqlTemplate(
    id="product_stock",
    intent="특정 제품의 현재 재고 조회",
    sql=(
        "SELECT id, name, category, price, stock "
        "FROM products WHERE id = :product_id"
    ),
    variables=(
        TemplateVariable(
            name="product_id",
            description="조회 대상 제품의 id",
            sql_type="int",
            lookup_sql=(
                "SELECT id, name, category FROM products "
                "ORDER BY category, name"
            ),
        ),
    ),
))

# 카테고리별 매출 상위 N개
template_registry.register(SqlTemplate(
    id="category_top_n_revenue",
    intent="특정 카테고리의 매출 상위 N개 제품 조회",
    sql=(
        "SELECT p.name, SUM(oi.quantity * oi.unit_price) AS revenue "
        "FROM order_items oi "
        "JOIN products p ON oi.product_id = p.id "
        "WHERE p.category = :category "
        "GROUP BY p.name "
        "ORDER BY revenue DESC "
        "LIMIT :n"
    ),
    variables=(
        TemplateVariable(
            name="category",
            description="조회 대상 제품 카테고리명",
            sql_type="text",
            lookup_sql="SELECT DISTINCT category FROM products ORDER BY category",
        ),
        TemplateVariable(
            name="n",
            description="조회할 상위 제품 개수",
            sql_type="int",
        ),
    ),
))

# 특정 고객의 주문 내역
template_registry.register(SqlTemplate(
    id="customer_orders",
    intent="특정 고객의 주문 내역 조회",
    sql=(
        "SELECT id, order_date, status, total_amount "
        "FROM orders WHERE customer_id = :customer_id "
        "ORDER BY order_date DESC"
    ),
    variables=(
        TemplateVariable(
            name="customer_id",
            description="조회 대상 고객의 id",
            sql_type="int",
            lookup_sql="SELECT id, name, city FROM customers ORDER BY name",
        ),
    ),
))

# 특정 월의 특정 상태 주문 수
template_registry.register(SqlTemplate(
    id="monthly_order_count",
    intent="특정 월의 특정 상태 주문 건수 집계",
    sql=(
        "SELECT COUNT(*) AS order_count "
        "FROM orders "
        "WHERE strftime('%Y-%m', order_date) = :year_month "
        "AND status = :status"
    ),
    variables=(
        TemplateVariable(
            name="year_month",
            description="조회 대상 월(YYYY-MM 형식)",
            sql_type="date",
        ),
        TemplateVariable(
            name="status",
            description="조회 대상 주문 상태",
            sql_type="text",
            lookup_sql="SELECT DISTINCT status FROM orders ORDER BY status",
        ),
    ),
))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_templated_sql_templates.py -v`
Expected: 3개 PASS.

추가 회귀 확인: 다른 테스트 파일이 templates 등록 부수효과의 영향을 받지 않는지.

Run: `uv run pytest tests/test_templated_sql_registry.py tests/test_templated_sql_render.py -v`
Expected: 모두 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/templated_sql_agent/templates.py tests/test_templated_sql_templates.py
git commit -m "$(cat <<'EOF'
feat(templated-sql): register v1 ecommerce template catalog

5개 템플릿: dept_avg_salary, product_stock, category_top_n_revenue,
customer_orders, monthly_order_count. 모듈 import 시 부수효과로 등록되며,
등록 검증(placeholder 일치, lookup_sql SELECT-only)이 자동 적용된다.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: agent.py — wrapper + 4-action 분기

LLM 호출과 4-action 분기, 실행 헬퍼(`_run_main`, `_run_lookups`, `_no_match_message`)를 한 모듈로 모은다. 서브그래프 없는 단일 노드 패턴(`translate_agent`와 동일).

**Files:**
- Create: `src/templated_sql_agent/agent.py`
- Test: `tests/test_templated_sql_agent.py` (확장)

- [ ] **Step 1: Write the failing tests**

`tests/test_templated_sql_agent.py` 끝에 다음 클래스들을 추가.

```python
import json
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from src.templated_sql_agent.agent import templated_sql_wrapper


def _state(user_text: str) -> dict:
    return {
        "messages": [HumanMessage(content=user_text)],
        "next_agent": "",
        "chat_history": [],
    }


def _llm_returning(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.invoke.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))
    return mock


class TestAgentDispatch:
    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_ask_clarification_returns_text_verbatim(
        self, mock_get_model: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "ask_clarification",
            "template_id": "product_stock",
            "extracted": {},
            "lookup_vars": [],
            "clarification": "어느 제품을 조회할까요? 전체 제품 목록을 보여드릴까요?",
        })
        result = templated_sql_wrapper(_state("재고 알려줘"))
        msg = result["messages"][-1]
        assert isinstance(msg, AIMessage)
        assert "어느 제품을 조회할까요" in msg.content

    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_no_match_returns_catalog_intents(
        self, mock_get_model: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "no_match",
            "template_id": None,
            "extracted": {},
            "lookup_vars": [],
            "clarification": "처리 가능한 질의 종류는: …",
        })
        result = templated_sql_wrapper(_state("무엇이든"))
        content = result["messages"][-1].content
        # clarification을 그대로 노출.
        assert "처리 가능한 질의" in content

    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_json_parse_failure_falls_back_to_no_match(
        self, mock_get_model: MagicMock,
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="이건 JSON이 아닙니다")
        mock_get_model.return_value = mock_llm
        result = templated_sql_wrapper(_state("ㅁㄴㅇㄹ"))
        # no_match 폴백: 처리 가능 질의 목록이 노출되어야 한다.
        content = result["messages"][-1].content
        # 5개 v1 템플릿 중 일부 intent가 포함되어야 한다.
        assert "특정 제품의 현재 재고 조회" in content

    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_unknown_template_id_falls_back_to_no_match(
        self, mock_get_model: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "execute_main",
            "template_id": "definitely_not_registered",
            "extracted": {"x": 1},
            "lookup_vars": [],
            "clarification": "",
        })
        result = templated_sql_wrapper(_state("..."))
        content = result["messages"][-1].content
        assert "특정 제품의 현재 재고 조회" in content


class TestExecuteMain:
    @patch("src.templated_sql_agent.agent._executor")
    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_execute_main_calls_executor_with_named_params(
        self,
        mock_get_model: MagicMock,
        mock_executor: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "execute_main",
            "template_id": "product_stock",
            "extracted": {"product_id": "7"},
            "lookup_vars": [],
            "clarification": "",
        })
        mock_executor.execute.return_value = {
            "ok": True, "columns": ["id"], "rows": [(7,)],
            "markdown": "| id |\n|---|\n| 7 |", "error": None,
        }

        result = templated_sql_wrapper(_state("상품 7번 재고"))

        call = mock_executor.execute.call_args
        sql_arg, params_arg = call[0][0], call[0][1]
        assert ":product_id" in sql_arg
        assert params_arg == {"product_id": 7}
        assert "| 7 |" in result["messages"][-1].content

    @patch("src.templated_sql_agent.agent._executor")
    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_execute_main_render_error_reports_to_user(
        self,
        mock_get_model: MagicMock,
        mock_executor: MagicMock,
    ) -> None:
        # int 변수에 "abc"를 줘서 TemplateRenderError 유발.
        mock_get_model.return_value = _llm_returning({
            "action": "execute_main",
            "template_id": "product_stock",
            "extracted": {"product_id": "abc"},
            "lookup_vars": [],
            "clarification": "",
        })
        result = templated_sql_wrapper(_state("..."))
        # render 실패 시 executor는 호출되지 않아야 한다.
        mock_executor.execute.assert_not_called()
        content = result["messages"][-1].content
        # 사용자 안내에 변수 이름이 들어가야 한다.
        assert "product_id" in content


class TestExecuteLookup:
    @patch("src.templated_sql_agent.agent._executor")
    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_execute_lookup_runs_lookup_sql(
        self,
        mock_get_model: MagicMock,
        mock_executor: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "execute_lookup",
            "template_id": "product_stock",
            "extracted": {},
            "lookup_vars": ["product_id"],
            "clarification": "",
        })
        mock_executor.execute.return_value = {
            "ok": True, "columns": ["id", "name", "category"],
            "rows": [(1, "A", "X")],
            "markdown": "| id | name | category |\n| 1 | A | X |",
            "error": None,
        }

        result = templated_sql_wrapper(_state("응 보여줘"))

        # lookup_sql만 호출되었고 params는 없어야 한다 (positional 1개).
        called_args = mock_executor.execute.call_args
        assert len(called_args[0]) == 1, (
            f"lookup은 params 없이 호출되어야 함. 실제: {called_args}"
        )
        called_sql = called_args[0][0]
        assert "FROM products" in called_sql
        assert "ORDER BY" in called_sql
        content = result["messages"][-1].content
        assert "| name |" in content or "| id |" in content

    @patch("src.templated_sql_agent.agent._executor")
    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_execute_lookup_skips_vars_without_lookup_sql(
        self,
        mock_get_model: MagicMock,
        mock_executor: MagicMock,
    ) -> None:
        # category_top_n_revenue의 n은 lookup_sql=None이다.
        mock_get_model.return_value = _llm_returning({
            "action": "execute_lookup",
            "template_id": "category_top_n_revenue",
            "extracted": {},
            "lookup_vars": ["n", "category"],
            "clarification": "",
        })
        mock_executor.execute.return_value = {
            "ok": True, "columns": ["category"], "rows": [("X",)],
            "markdown": "| category |\n|---|\n| X |", "error": None,
        }

        result = templated_sql_wrapper(_state("응"))

        # category만 lookup 가능 → executor 1회만 호출되어야 한다.
        assert mock_executor.execute.call_count == 1
        called_sql = mock_executor.execute.call_args[0][0]
        assert "DISTINCT category" in called_sql

    @patch("src.templated_sql_agent.agent._executor")
    @patch("src.templated_sql_agent.agent.get_chat_model")
    def test_execute_lookup_when_no_lookup_available(
        self,
        mock_get_model: MagicMock,
        mock_executor: MagicMock,
    ) -> None:
        mock_get_model.return_value = _llm_returning({
            "action": "execute_lookup",
            "template_id": "monthly_order_count",
            "extracted": {},
            "lookup_vars": ["year_month"],  # lookup_sql=None
            "clarification": "",
        })
        result = templated_sql_wrapper(_state("응"))
        mock_executor.execute.assert_not_called()
        content = result["messages"][-1].content
        assert "직접" in content or "값을" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_templated_sql_agent.py -v`
Expected: 새 케이스들이 FAIL (agent.py 모듈 미존재).

- [ ] **Step 3: Implement agent.py**

`src/templated_sql_agent/agent.py`:

```python
"""templated_sql 에이전트: 사전 정의 SQL 템플릿 기반 조회.

단일 LLM 호출로 4-action(execute_main/ask_clarification/execute_lookup/
no_match)을 분류하고 분기 실행한다. 멀티턴 흐름은 query_rewriter가
처리하므로 이 에이전트는 chat_history를 보지 않는다.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage

from src.registry import registry
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.sql_agent.tools import _executor  # 모듈 레벨 SqlExecutor 인스턴스 재활용
from src.state import State
from src.templated_sql_agent.prompt import build_system_prompt
from src.templated_sql_agent.registry import SqlTemplate, template_registry
from src.templated_sql_agent.render import TemplateRenderError, render

logger = get_logger("agent.templated_sql")


def _emit(content: str) -> dict:
    """그래프 반환 dict 표준 형식 (다른 서브에이전트들과 동일한 태깅)."""
    return {"messages": [AIMessage(content=f"[조회 결과]\n{content}")]}


def _parse_action_json(text: str) -> dict[str, Any] | None:
    """LLM 응답에서 JSON 객체를 추출한다. 실패 시 None."""
    stripped = text.strip()
    # ```json 블록 펜스가 섞여 있으면 안의 내용만 추출.
    if "```" in stripped:
        try:
            start = stripped.index("```")
            after = stripped[start + 3:]
            if after.startswith("json"):
                after = after[4:]
            end = after.index("```")
            stripped = after[:end].strip()
        except ValueError:
            pass
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None


def _no_match_message() -> str:
    """no_match 상황에서 사용자에게 보여줄 안내 메시지."""
    if not template_registry.templates:
        return "처리 가능한 질의가 등록되어 있지 않습니다."
    lines = ["이 에이전트가 처리할 수 있는 질의 종류는 다음과 같습니다:"]
    for t in template_registry.templates:
        lines.append(f"- {t.intent}")
    lines.append("위 질의 중 하나로 다시 질문해 주세요.")
    return "\n".join(lines)


def _run_main(template: SqlTemplate, extracted: dict[str, Any]) -> str:
    """메인 SQL을 실행하고 markdown 결과(or 사용자 안내) 문자열을 반환."""
    try:
        sql, params = render(template, extracted)
    except TemplateRenderError as exc:
        logger.info("render 실패: %s", exc)
        return (
            f"다음 변수가 잘못되었거나 누락되었습니다: {exc}\n"
            "값을 확인해 다시 알려주세요."
        )
    result = _executor.execute(sql, params)
    return result["markdown"]


def _run_lookups(
    template: SqlTemplate,
    lookup_vars: list[str],
) -> str:
    """후보값 조회 SQL을 실행하고 결과 표들을 묶어 markdown 문자열로 반환."""
    candidates = [
        v for v in template.variables
        if v.name in lookup_vars and v.lookup_sql is not None
    ]
    if not candidates:
        return (
            "조회 가능한 후보값이 없습니다. 변수 값을 직접 알려주세요.\n"
            "필요한 변수:\n"
            + "\n".join(
                f"- {v.name} ({v.sql_type}): {v.description}"
                for v in template.variables
            )
        )

    blocks: list[str] = []
    for v in candidates:
        assert v.lookup_sql is not None
        r = _executor.execute(v.lookup_sql)
        header = f"[{v.description} 후보값]"
        if r["ok"]:
            blocks.append(f"{header}\n{r['markdown']}")
        else:
            blocks.append(f"{header}\n조회 실패: {r['error']}")

    blocks.append("원하시는 값을 알려주시면 조회를 진행합니다.")
    return "\n\n".join(blocks)


@registry.agent(
    "templated_sql",
    description=template_registry.build_router_description(),
)
@log_node("templated_sql")
def templated_sql_wrapper(state: State) -> dict:
    """사전 정의된 SQL 템플릿 기반 조회를 처리한다."""
    llm = get_chat_model()
    system_prompt = build_system_prompt(template_registry)
    messages = [SystemMessage(content=system_prompt)] + state["messages"]

    logger.info("LLM 호출 시작 (templates=%d)", len(template_registry.templates))
    try:
        response = llm.invoke(messages)
    except Exception:
        logger.error("LLM 호출 실패", exc_info=True)
        raise

    parsed = _parse_action_json(response.content)
    if parsed is None:
        logger.warning("JSON 파싱 실패 → no_match 폴백. 원본: %s", response.content)
        return _emit(_no_match_message())

    action = parsed.get("action")
    template_id = parsed.get("template_id")

    if action in {"ask_clarification", "no_match"}:
        clarification = parsed.get("clarification") or _no_match_message()
        return _emit(clarification)

    template = template_registry.get(template_id) if template_id else None
    if template is None:
        logger.warning("미등록 template_id: %s → no_match 폴백", template_id)
        return _emit(_no_match_message())

    if action == "execute_lookup":
        lookup_vars = parsed.get("lookup_vars") or []
        return _emit(_run_lookups(template, lookup_vars))

    if action == "execute_main":
        extracted = parsed.get("extracted") or {}
        return _emit(_run_main(template, extracted))

    logger.warning("알 수 없는 action: %s → no_match 폴백", action)
    return _emit(_no_match_message())
```

**주의:** 이 모듈은 `src.sql_agent.tools._executor`(모듈 레벨 SqlExecutor 인스턴스, `src/sql_agent/tools.py:17`)를 재활용한다. ecommerce.db 경로/auto_seed 설정이 한 곳에서 일관 관리된다.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_templated_sql_agent.py -v`
Expected: 모든 케이스 PASS.

추가: 모든 templated_sql 테스트 회귀 확인.

Run: `uv run pytest tests/test_templated_sql_registry.py tests/test_templated_sql_render.py tests/test_templated_sql_templates.py tests/test_templated_sql_agent.py -v`
Expected: 모두 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/templated_sql_agent/agent.py tests/test_templated_sql_agent.py
git commit -m "$(cat <<'EOF'
feat(templated-sql): add agent wrapper with 4-action dispatch

단일 LLM 호출로 action을 분류하고 execute_main/ask_clarification/
execute_lookup/no_match로 분기. JSON 파싱 실패·미등록 template_id·
render 실패는 모두 사용자 안내로 변환되어 그래프 밖으로 새지 않는다.
기존 sql_agent의 SqlExecutor 인스턴스를 재활용해 DB 설정을 일관 관리.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: __init__.py 패키지 wiring + src/__init__.py에 등록 트리거 추가

기존 에이전트들과 동일한 등록 트리거 흐름을 만든다.

**Files:**
- Modify: `src/templated_sql_agent/__init__.py`
- Modify: `src/__init__.py`

- [ ] **Step 1: Wire the package init**

`src/templated_sql_agent/__init__.py`를 다음으로 교체.

```python
# templates를 먼저 import해 모든 SqlTemplate을 레지스트리에 등록시킨 뒤,
# agent를 import해 @registry.agent(description=...) 데코레이터가 자동
# 합성된 description으로 실행되도록 한다. 순서가 바뀌면 description에
# 템플릿 의도 목록이 누락된다.
from src.templated_sql_agent import templates  # noqa: F401
from src.templated_sql_agent.agent import templated_sql_wrapper

__all__ = ["templated_sql_wrapper"]
```

- [ ] **Step 2: Add registration trigger**

`src/__init__.py`를 다음으로 교체.

```python
# 각 에이전트 모듈을 import하여 @registry.agent 데코레이터를 통한 자동 등록을 트리거한다.
from src.math_agent import math_wrapper  # noqa: F401
from src.registry import registry  # noqa: F401
from src.sql_agent import sql_wrapper  # noqa: F401
from src.templated_sql_agent import templated_sql_wrapper  # noqa: F401
from src.translate_agent import translate_wrapper  # noqa: F401

__all__ = ["math_wrapper", "sql_wrapper", "templated_sql_wrapper", "translate_wrapper", "registry"]
```

- [ ] **Step 3: Verify wiring with a smoke test**

전체 테스트 실행 + 등록 확인.

Run: `uv run pytest tests/ -v -k templated_sql`
Expected: 전체 PASS.

추가 확인: 새 에이전트가 글로벌 registry에 들어왔는지 ad-hoc 검증.

Run: `uv run python -c "import src; from src.registry import registry; print([e.name for e in registry.entries])"`
Expected: 출력에 `'templated_sql'`이 포함된다.

- [ ] **Step 4: Commit**

```bash
git add src/templated_sql_agent/__init__.py src/__init__.py
git commit -m "$(cat <<'EOF'
feat(templated-sql): wire package init and add to global registry trigger

templates를 먼저 import해 5개를 등록시킨 뒤 agent를 import하면 라우터
description이 등록된 모든 의도를 반영해 자동 합성된다. src/__init__.py에
한 줄 추가로 그래프 빌드 시점에 자동 노드/엣지가 추가된다.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: query_rewriter 프롬프트 — 확인 응답 룰 추가

`src/query_rewriter/prompt.py:198-202`의 "### 2. 대화 맥락 보충" 섹션에 한 줄을 추가하고, 테스트 케이스를 보강한다.

**Files:**
- Modify: `src/query_rewriter/prompt.py:198-202` (불릿 리스트)
- Test: `tests/test_query_rewriter.py`

- [ ] **Step 1: Write the failing test**

`tests/test_query_rewriter.py` 끝(`TestQueryRewriterNode`의 마지막 메서드 다음)에 다음을 추가.

```python
class TestPromptConfirmationRule:
    def test_prompt_includes_confirmation_response_rule(self) -> None:
        prompt = build_rewriter_system_prompt(datetime(2026, 5, 11, 9, 0))
        # 확인 응답 처리 룰이 명시되어야 한다.
        assert "확인 응답" in prompt or "응" in prompt
        # 직전 제안의 구체 행동으로 풀어쓴다는 의미가 포함되어야 한다.
        assert "구체" in prompt or "풀어" in prompt or "명시" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_query_rewriter.py::TestPromptConfirmationRule -v`
Expected: FAIL (현재 프롬프트에 해당 문구 없음).

- [ ] **Step 3: Update query_rewriter prompt**

`src/query_rewriter/prompt.py:198-202`의 다음 부분:

```python
이전 턴들의 대화(시스템 메시지 다음에 주어지는 사용자/어시스턴트 메시지 쌍)는 큐레이션된 과거 대화입니다. 이를 참고하여 현재 사용자 메시지의 모호한 지시어를 구체적으로 바꿔주세요:
- "이거", "그거", "저거" → 지칭하는 대상을 명시
- "더 해줘", "다시 해줘" → 이전에 수행한 작업을 구체적으로 명시
- "반대로 해줘" → 이전 작업의 반대 방향을 명시
- 새로운 독립 질문이면 맥락 보충 없이 그대로 유지
```

을 다음으로 교체:

```python
이전 턴들의 대화(시스템 메시지 다음에 주어지는 사용자/어시스턴트 메시지 쌍)는 큐레이션된 과거 대화입니다. 이를 참고하여 현재 사용자 메시지의 모호한 지시어를 구체적으로 바꿔주세요:
- "이거", "그거", "저거" → 지칭하는 대상을 명시
- "더 해줘", "다시 해줘" → 이전에 수행한 작업을 구체적으로 명시
- "반대로 해줘" → 이전 작업의 반대 방향을 명시
- "응", "네", "그래", "예", "보여줘" 등 확인 응답 → 직전 에이전트 메시지가 제안한 구체 행동을 명시적으로 풀어서 재작성 (예: "응" → "전체 지점 목록과 라면 제품 목록을 보여줘")
- 새로운 독립 질문이면 맥락 보충 없이 그대로 유지
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_query_rewriter.py -v`
Expected: 신규 케이스 PASS + 기존 모든 케이스 회귀 없이 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/query_rewriter/prompt.py tests/test_query_rewriter.py
git commit -m "$(cat <<'EOF'
feat(query-rewriter): add confirmation-response rewriting rule

"응", "보여줘" 같은 짧은 확인 응답을 직전 에이전트 제안의 구체 행동으로
풀어 쓰도록 프롬프트에 룰 한 줄 추가. templated_sql의 멀티턴
(ask_clarification → 동의 → execute_lookup) 흐름의 안전망이며 다른
에이전트 멀티턴에도 동일한 효과가 있다.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: main.py 시나리오 F — templated_sql 멀티턴 시연

3턴 시퀀스(ask_clarification → execute_lookup → execute_main)를 데모 실행으로 보여준다.

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Read existing scenario structure**

이 작업은 코드 단위 테스트보다는 실제 실행을 통한 수동 검증이 목적이다. 기존 `run_multiturn_scenario`는 2턴 구조이므로 3턴 헬퍼를 추가한다.

- [ ] **Step 2: Add 3-turn helper**

`src/main.py`의 `run_multiturn_scenario` 함수(85-121) 바로 다음에 다음 함수를 추가.

```python
def run_three_turn_scenario(
    app,
    name: str,
    description: str,
    turn1: str,
    turn2: str,
    turn3: str,
) -> None:
    """3턴 멀티턴 시나리오. chat_history를 누적해 다음 invoke에 인계."""
    logger.info("시나리오 %s: %s", name, description)
    chat_history: list = []

    for i, msg in enumerate((turn1, turn2, turn3), start=1):
        logger.info("%d차 입력: %s", i, msg)
        result = app.invoke({
            "messages": [HumanMessage(content=msg)],
            "next_agent": "",
            "chat_history": chat_history,
        })
        chat_history = result.get("chat_history", chat_history)
        logger.info("%d차 종료 후 chat_history 길이: %d", i, len(chat_history))

        logger.info(
            "\n%s\n"
            "  [SCENARIO %s · turn %d] Finished\n"
            "%s\n"
            "  Final State:\n%s\n"
            "%s",
            "=" * 60, name, i, "=" * 60,
            format_state_pretty(result),
            "=" * 60,
        )
```

- [ ] **Step 3: Append scenario F call to main()**

`src/main.py`의 `main()` 함수 끝(`run_multiturn_scenario(..., "E", ...)` 다음)에 다음을 추가.

```python
    run_three_turn_scenario(
        app, "F",
        "templated_sql 멀티턴 — 변수 부족 → 후보값 조회 → 실행",
        "상품 재고 알려줘",
        "응 보여줘",
        "상품 id 5번 재고 알려줘",
    )
```

- [ ] **Step 4: Smoke run**

OPENAI_API_KEY가 설정되어 있고 ecommerce.db 시드가 가능한 환경에서:

Run: `uv run python -m src.main`
Expected: 시나리오 A~F가 모두 로그에 출력되며, F의 1차에는 ask_clarification, 2차에는 lookup 결과 표, 3차에는 product_stock 메인 SQL 결과가 나타남. (LLM 응답의 정확성은 본 테스트에서 검증 대상이 아니지만, 그래프가 끝까지 도는지는 확인.)

만약 OPENAI_API_KEY가 없거나 실행이 어려운 환경이라면 step 4는 코드 빌드 확인으로 대체:

Run: `uv run python -c "from src.main import build_graph; build_graph(); print('graph built')"`
Expected: 출력 "graph built" + 예외 없음.

- [ ] **Step 5: Commit**

```bash
git add src/main.py
git commit -m "$(cat <<'EOF'
feat(main): add scenario F demonstrating templated_sql 3-turn flow

ask_clarification → execute_lookup → execute_main 3턴 흐름을 멀티턴 데모로
시연. chat_history 누적이 query_rewriter의 확인 응답 룰과 결합해 사용자의
짧은 동의("응 보여줘")가 lookup 실행으로 풀이되는 흐름을 보인다.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: res/suggestions.yaml — templated_sql 카테고리

CLI 추천 질문에 새 카테고리를 추가한다.

**Files:**
- Modify: `res/suggestions.yaml`

- [ ] **Step 1: Append category**

`res/suggestions.yaml` 끝에 다음을 추가.

```yaml
templated_sql:
  - "엔지니어링 부서의 평균 급여 알려줘"
  - "상품 id 5번 재고 알려줘"
  - "전자기기 카테고리 매출 상위 3개 제품"
  - "고객 id 12번 주문 내역"
  - "2026-04 paid 상태 주문 건수"
  - "라면 재고 알려줘"
```

마지막 항목 "라면 재고 알려줘"는 ecommerce.db에 매칭되지 않는 질의로, ask_clarification 흐름을 자연스럽게 시연한다(`product_stock`의 product_id가 누락된 케이스). 카테고리 키 `templated_sql`은 `registry.agent_names`와 일치하므로 카테고리-에이전트 매핑이 자동 적용된다.

- [ ] **Step 2: Verify CLI loads suggestions**

Run: `uv run python -c "from src.cli.suggestions import load_suggestions; print(list(load_suggestions().keys()))"`
Expected: 출력에 `'templated_sql'`이 포함된다.

(`src/cli/suggestions.py`의 정확한 함수명이 다르면 해당 모듈을 grep하여 확인. 본 step은 yaml이 파싱되는지 + 키가 인식되는지 sanity check만 수행.)

- [ ] **Step 3: Commit**

```bash
git add res/suggestions.yaml
git commit -m "$(cat <<'EOF'
chore(cli): add templated_sql suggestions

5개 v1 템플릿 각각에 매칭되는 질문과, ask_clarification 흐름을 시연할
의도적 변수 누락 질의("라면 재고 알려줘") 1개를 시드.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: README.md 업데이트

Architecture 다이어그램, Project Structure 트리, Subagents 표, Demo 시나리오 목록 4곳을 갱신.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update Architecture diagram**

`README.md:7-12`의 Architecture 코드블록에서 router 분기 부분을 다음으로 교체.

```
[START] → [query_rewriter] → [router] ─┬→ [math_agent]          ─┐
                                       ├→ [translate_agent]      │
                                       ├→ [sql_agent]            ├→ [response_generator] → [END]
                                       ├→ [templated_sql_agent]  │
                                       └→ [response_generator] (FINISH)
```

- [ ] **Step 2: Update subagents bullet**

`README.md:16`의 다음 줄:

```
- **subagents** — `math`, `translate`, `sql` 중 선택된 하나만 실행된다.
```

을 다음으로 교체.

```
- **subagents** — `math`, `translate`, `sql`, `templated_sql` 중 선택된 하나만 실행된다.
```

- [ ] **Step 3: Update Project Structure tree**

`README.md:52`의 `sql_agent/` 항목 바로 다음 줄에 다음을 추가.

```
│   ├── templated_sql_agent/       # 사전 정의 SQL 템플릿 기반 조회
│   │   ├── registry.py            #   SqlTemplate / TemplateRegistry
│   │   ├── templates.py           #   ecommerce 도메인 5개 템플릿 등록
│   │   ├── render.py              #   변수 검증 + named-param 바인딩
│   │   ├── prompt.py              #   action 분류용 시스템 프롬프트
│   │   └── agent.py               #   wrapper + 4-action 분기
```

- [ ] **Step 4: Update Subagents table**

`README.md:79-83`의 표에 다음 행을 추가(translate 다음 줄).

```
| `templated_sql` | LLM 직접 호출 + 분기 | 정적 등록 `SqlTemplate` 카탈로그, lookup_sql, `SqlExecutor` 재활용 |
```

- [ ] **Step 5: Update demo scenarios**

`README.md:30-34`의 데모 시나리오 목록에 다음 항목을 추가.

```
- **F** templated_sql 멀티턴 — 변수 부족 → 후보값 조회 → 실행의 3턴 시연
```

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: document templated_sql agent in README

Architecture 다이어그램·subagents 목록·Project Structure 트리·서브에이전트
표·데모 시나리오 5곳을 갱신. 새 에이전트의 위치, 책임, 데모 시나리오를
한눈에 확인할 수 있도록 정리.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 최종 검증

모든 task 완료 후 전체 회귀 검증.

- [ ] **전체 단위 테스트**

Run: `uv run pytest tests/ -v`
Expected: 전체 PASS. 기존 테스트가 회귀하지 않아야 한다.

- [ ] **그래프 빌드**

Run: `uv run python -c "from src.main import build_graph; app = build_graph(); print('ok')"`
Expected: "ok" 출력 + 예외 없음.

- [ ] **등록 확인**

Run: `uv run python -c "import src; from src.registry import registry; print(registry.agent_names)"`
Expected: `['math', 'sql', 'templated_sql', 'translate']` 또는 등록 순서대로의 동등한 목록 (등록 순서는 `src/__init__.py`의 import 순서를 따른다).

- [ ] **타입 체크 (선택)**

`mypy` 또는 `pyright`가 프로젝트에 구성되어 있으면 실행. 미구성이면 skip.

---

## 참고: spec ↔ task 매핑

| spec 섹션 | 구현 task |
|---|---|
| 1. 디렉토리 구조 | T2~T9 (각 파일별) |
| 2. 데이터 모델 | T2 |
| 3. 레지스트리 + builders | T2/T3/T4 |
| 4. 등록 메커니즘 | T7/T9 |
| 5. v1 도메인 카탈로그 | T7 |
| 6. 실행 흐름 (agent.py) | T8 |
| 7. 시스템 프롬프트 | T6 |
| 8. 안전 치환 (render) | T5 |
| 9. SqlExecutor 시그니처 확장 | T1 |
| 10. query_rewriter 프롬프트 보강 | T10 |
| 11. 라우터/그래프 통합 | T9 |
| 12. CLI 추천 질문 | T12 |
| 데이터 흐름 시연 | T11 |
| 에러 처리 | T8 (분산), T1/T5 (예외) |
| 테스트 계획 | T1~T8 각 step의 테스트 케이스 |
| 영향 분석 / 문서 갱신 | T13 |
