# tool_call 에이전트 — 함수형 도구 ReAct 기반 멀티 DB 조회

## 배경 / 목적

기존 `templated_sql` 에이전트는 사전 정의된 SQL 템플릿에 사용자가 명시한 변수만 채워 실행하는 구조다. 도메인이 명확하고 SQL 모양이 정해진 경우에 적합하지만, 다음을 표현할 수 없다:

1. **DB 외부 변수가 끼는 작업.** 예: 어느 DB 파일에 접속할지 자체가 변수.
2. **도구 결과가 다음 도구의 파라미터가 되는 순차 조합.** 예: 메타DB에서 브랜치별 DB 경로를 얻은 뒤, 그 경로로 머신 DB를 조회.

본 작업은 **사전 정의된 함수 도구들을 ReAct 루프로 호출하는 범용 에이전트(`tool_call`)**를 신규로 추가한다. 에이전트 코어는 도메인 무지(LangChain `bind_tools`가 도구 docstring·시그니처에서 스키마 자동 추출). v1 도메인은 제조업 — 본사 메타DB가 브랜치(공장) 목록과 각 브랜치 DB 경로를 보관하고, 브랜치 DB가 그 브랜치의 머신 정보를 보관한다.

핵심 행동 원칙:

1. **도구 호출 체이닝.** 한 턴 안에서 LLM이 여러 도구를 순차 호출할 수 있다.
2. **파라미터 부족 시 자연어 회신.** LLM이 tool_calls 없이 자연어로 사용자에게 부족한 정보를 묻고 응답을 종료한다. 다음 턴에서 사용자가 보충하면 이어서 실행한다.
3. **멀티턴 흐름은 query_rewriter가 담당.** 에이전트는 chat_history를 보지 않고 자기완결 입력만 처리한다.
4. **레지스트리 추상화 신설 금지.** 새 도메인 모듈(`tool_call_agent`)을 빈땅에서 시작한다. `template_registry` 같은 보조 클래스를 만들지 않는다. 도구는 모듈 레벨 리스트.

## 범위

### In scope
- `src/tool_call_agent/` 신규 모듈 (`__init__.py`, `agent.py`, `prompt.py`, `tools.py`)
- `res/sample_db/factory/` 신규 디렉토리: `seed.py` + 자동 생성되는 `meta.db`, `branch_A.db`, `branch_B.db`, `branch_C.db`
- v1 도구 4개: `list_branches`, `get_branch_db_path`, `list_machines`, `get_machine_status`
- `src/main.py`에 import 한 줄 + 데모 시나리오 G 추가
- `res/suggestions.yaml`에 `tool_call` 카테고리 추가
- 단위/통합 테스트
- `README.md` 업데이트 (Architecture, Project Structure, Subagents 표, 데모 목록)

### Out of scope
- `evals/test_cases.yaml` 평가 케이스 추가 — 별도 작업
- `SqlExecutor` 변경 — 본 에이전트는 자체 sqlite 헬퍼를 사용 (재사용은 `validate_select_only` 모듈 하나만)
- 도구 외부 정의 (YAML 등) 또는 동적 등록
- 라우팅·그래프 빌드 코드 수정 (registry 자동 반영)
- `templated_sql_agent` 코드 변경
- `query_rewriter` 프롬프트 수정 (templated_sql 작업에서 추가된 "확인 응답 풀어쓰기" 룰을 그대로 재활용)
- ecommerce 도메인 도구 추가
- 다중 DB의 동시 트랜잭션, 캐싱, 풀링

## 설계

### 1. 디렉토리 구조

```
src/tool_call_agent/
├── __init__.py        # tools, agent 노출 + 등록 트리거
├── agent.py           # @registry.agent("tool_call") + ReAct 서브그래프 + wrapper
├── prompt.py          # 범용 시스템 프롬프트 (도메인 어휘 없음)
└── tools.py           # @tool 데코레이션된 v1 도구 4개 + 안전 헬퍼

res/sample_db/factory/
├── seed.py            # 4개 .db 자동 시드 (idempotent)
├── meta.db            # 시드 시 자동 생성 (branches 테이블)
├── branch_A.db        # 시드 시 자동 생성 (machines, machine_status)
├── branch_B.db
└── branch_C.db
```

설계 원칙:

- **에이전트 코어는 도구 내용을 모른다.** `agent.py`는 `TOOLS` 리스트만 import해 `bind_tools()` + ReAct 루프 실행.
- **도구는 자기완결.** 각 `@tool` 함수가 sqlite 커넥션을 직접 생성·정리. 모듈 레벨 싱글톤이나 공유 executor 없음.
- **레지스트리 신설 금지.** `template_registry`처럼 별도 클래스를 만들지 않는다. `TOOLS = [...]` 모듈 레벨 리스트가 전부.
- **기존 자산 최소 재사용.** SELECT-only 검증은 보안상 `src/sql_agent/backend/safety.py`의 `validate_select_only`만 재사용. 그 외에는 빈땅에서 작성.

### 2. 에이전트 그래프 (`agent.py`)

`sql_agent/frontend/agent.py`와 동일한 ReAct 패턴이지만 SQL 도메인 의존 제거. `WorkerState`를 사용해 ReAct 내부 메시지(tool_calls, ToolMessage)가 메인 그래프를 오염시키지 않는다.

```python
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.registry import registry
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.state import State, WorkerState
from src.tool_call_agent.prompt import SYSTEM_PROMPT
from src.tool_call_agent.tools import TOOLS, TOOLS_BY_NAME

logger = get_logger("agent.tool_call")
router_logger = get_logger("router.tool_call")


def build_tool_call_agent() -> CompiledStateGraph:
    @log_node("tool_call_agent_internal")
    def agent_node(state: WorkerState) -> dict:
        llm = get_chat_model().bind_tools(TOOLS)
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        response = llm.invoke(messages)
        return {"messages": [response]}

    @log_node("tool_call_tool_executor")
    def tool_executor_node(state: WorkerState) -> dict:
        last = state["messages"][-1]
        results: list[ToolMessage] = []
        for tc in getattr(last, "tool_calls", []):
            fn = TOOLS_BY_NAME.get(tc["name"])
            if fn is None:
                results.append(ToolMessage(
                    content=f"ERROR: 알 수 없는 tool '{tc['name']}'",
                    tool_call_id=tc["id"],
                ))
                continue
            try:
                out = fn.invoke(tc["args"])
                results.append(ToolMessage(content=str(out), tool_call_id=tc["id"]))
            except Exception as exc:
                logger.error("tool 실행 실패: %s", tc["name"], exc_info=True)
                results.append(ToolMessage(
                    content=f"ERROR: {tc['name']} 실행 중 예외: {exc}",
                    tool_call_id=tc["id"],
                ))
        return {"messages": results}

    def should_continue(state: WorkerState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(WorkerState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_executor_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()


tool_call_subgraph = build_tool_call_agent()


@registry.agent("tool_call")
@log_node("tool_call")
def tool_call_wrapper(state: State) -> dict:
    """제조업 브랜치(공장)별 머신 정보 조회를 처리합니다.

    처리 가능한 질의 유형:
    - 등록된 브랜치(공장) 목록 조회 (예: "어떤 브랜치가 있어?", "공장 목록 보여줘")
    - 특정 브랜치의 머신(설비) 목록 조회 (예: "아산 1공장의 머신 목록", "F-A 브랜치의 설비")
    - 특정 머신의 현재 상태/가동률 조회 (예: "아산 1공장 M-001 머신 상태", "F-B의 압출기 가동률")
    - 브랜치를 모르고 질문한 경우 사용자에게 어느 브랜치인지 되묻고, 사용자가 동의하면 브랜치 목록을 제공

    데이터 구조:
    - 본사 메타DB에 브랜치 코드/이름/지역/DB 경로가 등록되어 있음
    - 각 브랜치마다 별도의 DB 파일이 존재하며, 머신 정보는 해당 브랜치 DB에서만 조회 가능
    - 따라서 브랜치 정보가 명시되지 않은 머신 질의는 먼저 브랜치를 확정해야 함

    실행 방식:
    - 사전 정의된 함수형 도구들(브랜치 목록 조회, 브랜치 DB 경로 조회, 머신 목록 조회, 머신 상태 조회)을 ReAct 루프로 순차/조합 호출
    - 도구 실행에 필요한 파라미터(브랜치 코드, 머신 id 등)가 부족하면 사용자에게 자연어로 되묻고 그 턴을 종료. 다음 턴에서 사용자가 정보를 보충하면 이어서 실행

    라우팅 가이드:
    - 브랜치/공장/머신/설비/가동률/라인 같은 제조 도메인 키워드가 등장하면 이 에이전트
    - 직원/부서/고객/제품/주문 등 ecommerce 도메인은 이 에이전트가 아님 (sql 또는 templated_sql)
    - 자유형 임의 SQL이 필요한 분석성 질의는 이 에이전트가 아님 (sql)
    """
    result = tool_call_subgraph.invoke({"messages": state["messages"]})
    last = result["messages"][-1]
    return {"messages": [AIMessage(content=f"[조회 결과]\n{last.content}")]}
```

`tool_calls`가 비어 있으면 즉시 END — 자연어 clarification 응답이 곧바로 사용자에게 전달된다.

### 3. 시스템 프롬프트 (`prompt.py`)

도메인 어휘 없음. ReAct 규율과 출력 형식 규칙만 명시. 도구 의미는 LangChain `bind_tools`가 도구 docstring으로 자동 노출.

```python
SYSTEM_PROMPT = """\
당신은 사전 정의된 도구들을 사용해 사용자의 정보 조회 요청을 처리하는 에이전트입니다.
사용 가능한 도구의 이름·설명·파라미터 스키마는 시스템이 별도로 제공합니다 (tool 바인딩).

## 처리 규칙

1. 사용자의 의도를 충족하려면 어떤 도구를, 어떤 순서로 호출해야 하는지 먼저 판단하세요.
2. 한 도구의 결과가 다른 도구의 파라미터로 필요하면 순차적으로 호출하세요 (한 턴 안에서 여러 번 호출 가능).
3. 도구 호출에 필요한 파라미터를 사용자 메시지나 이전 도구 결과에서 확보할 수 없으면, 도구를 호출하지 말고 사용자에게 자연어로 부족한 정보를 묻고 응답을 종료하세요.
4. 파라미터 값을 추측·날조하지 마세요. 사용자가 명시하지 않았고 도구로도 얻을 수 없는 값은 missing입니다.
5. 사용자에게 되물을 때, 후보값을 조회할 수 있는 도구가 있다면 "전체 목록을 보여드릴까요?" 형태로 제안하세요. 사용자가 동의하면 다음 턴에 해당 도구를 호출합니다.
6. 도구가 "ERROR: ..."로 시작하는 결과를 반환하면, 메시지를 읽고 (a) 파라미터를 수정해 재시도하거나 (b) 사용자에게 사유를 안내하세요.
7. 최종 응답은 도구 결과를 정리해 사용자가 바로 이해할 수 있는 형태로 작성하세요. 도구의 markdown 표는 보존하세요.
8. 시스템 내부 식별자(예: DB 파일 경로)는 사용자에게 노출하지 마세요. 사용자 친화적인 이름(브랜치 이름 등)으로 환원해서 보여주세요.

## 출력 형식

- 도구를 호출할 때는 tool_calls만 반환하세요 (텍스트는 비워도 됩니다).
- 사용자에게 응답할 때는 일반 자연어로 반환하세요 (tool_calls 없음).
"""
```

### 4. 도구 함수 시그니처 (`tools.py`)

v1 도구 4개. 각 함수가 자체 sqlite 커넥션을 생성·정리하며 모듈 레벨 싱글톤이 없다.

```python
@tool
def list_branches() -> str:
    """등록된 브랜치(공장) 목록을 markdown 표로 반환한다.

    반환 컬럼: branch_code, branch_name, region. branch_code는 다른 도구의 인자로 사용된다.
    """

@tool
def get_branch_db_path(branch_code: str) -> str:
    """특정 브랜치의 머신 DB 경로를 반환한다.

    list_machines / get_machine_status를 호출하기 전에 이 도구로 db_path를 확보해야 한다.
    branch_code는 list_branches 결과의 branch_code 컬럼 값과 정확히 일치해야 한다.

    Args:
        branch_code: 브랜치 코드 (예: "F-A").
    """

@tool
def list_machines(db_path: str) -> str:
    """특정 브랜치 DB의 머신(설비) 목록을 markdown 표로 반환한다.

    db_path는 get_branch_db_path의 반환값을 그대로 사용한다.

    Args:
        db_path: 브랜치 DB 파일 경로.
    """

@tool
def get_machine_status(db_path: str, machine_id: str) -> str:
    """특정 머신의 현재 상태/가동률을 markdown 표로 반환한다.

    Args:
        db_path: 브랜치 DB 파일 경로 (get_branch_db_path 결과).
        machine_id: 머신 id (list_machines 결과의 machine_id 컬럼).
    """

TOOLS = [list_branches, get_branch_db_path, list_machines, get_machine_status]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
```

내부 헬퍼는 `tools.py` 안에 함께 둔다(모듈 외부 노출 없음):

- `_FACTORY_DB_ROOT = Path(.../res/sample_db/factory)` — 화이트리스트 루트
- `_META_DB = _FACTORY_DB_ROOT / "meta.db"`
- `_ensure_seeded()` — `meta.db`가 없으면 `res.sample_db.factory.seed.run()` 호출 (idempotent, 1회)
- `_resolve_branch_db(db_path)` — 절대/상대 경로 모두 받아 `_FACTORY_DB_ROOT` 직속 .db 파일만 허용, `meta.db`는 제외, 존재하지 않으면 거부
- `_read_query(db_file, sql, params)` — `validate_select_only` + `mode=ro` URI + `busy_timeout` + 자동 `LIMIT 100` 주입
- `_to_markdown(cols, rows)` — 결과 표 포맷팅

### 5. 샘플 DB (`res/sample_db/factory/`)

`meta.db` 스키마:

```sql
CREATE TABLE branches (
    branch_code TEXT PRIMARY KEY,
    branch_name TEXT NOT NULL,
    region      TEXT NOT NULL,
    db_path     TEXT NOT NULL  -- res/sample_db/factory 기준 상대경로
);
```

시드 행 3건:

| branch_code | branch_name | region | db_path |
|---|---|---|---|
| F-A | 아산 1공장 | 충남 | branch_A.db |
| F-B | 구미 2공장 | 경북 | branch_B.db |
| F-C | 광주 3공장 | 광주 | branch_C.db |

브랜치 DB 공통 스키마:

```sql
CREATE TABLE machines (
    machine_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    line        TEXT NOT NULL,
    model       TEXT NOT NULL
);
CREATE TABLE machine_status (
    machine_id     TEXT PRIMARY KEY REFERENCES machines(machine_id),
    state          TEXT NOT NULL,        -- "running" | "idle" | "maintenance" | "fault"
    uptime_ratio   REAL NOT NULL,        -- 0.0 ~ 1.0
    last_updated   TEXT NOT NULL         -- ISO datetime
);
```

각 브랜치 DB에 머신 3~5개 시드 (브랜치마다 서로 다른 머신 id/이름/라인).

`seed.py`의 진입점:

```python
def run() -> None:
    """meta.db와 brand_*.db를 모두 생성한다 (idempotent).

    이미 존재하면 INSERT OR REPLACE로 같은 데이터를 보장.
    """
```

### 6. 안전 정책 (3중 안전망 + 화이트리스트)

| 계층 | 보호 대상 | 구현 |
|---|---|---|
| 1. SQL 키워드 검증 | INSERT/UPDATE/DELETE/DROP 등 거부 | `validate_select_only` (재사용) |
| 2. 커넥션 mode | 쓰기 불가능 | `file:...?mode=ro` URI + `uri=True` |
| 3. 타임아웃 | 무한 대기 차단 | `busy_timeout` + Python `timeout` |
| 4. LIMIT 주입 | 대용량 폭주 차단 | LIMIT 미포함 쿼리에 자동 `LIMIT 100` |
| 5. 경로 화이트리스트 | path traversal 차단 | `_resolve_branch_db`가 `_FACTORY_DB_ROOT` 직속 .db만 허용, `meta.db` 제외 |

도구 함수 외부에서 받은 `db_path`(LLM이 생성)는 도구 진입 시점에 `_resolve_branch_db`를 통과해야 한다. 위반 시 `"ERROR: 허용되지 않은 DB 경로: ..."` 문자열을 반환해 ReAct 루프가 LLM에게 재시도 기회를 준다.

### 7. 에러 처리 표준

| 발생 지점 | 처리 |
|---|---|
| 도구 내부 SQL/IO 실패 | 도구가 `"ERROR: ..."` 문자열 반환 (예외는 그래프 밖으로 누출 금지). LLM이 사유를 사용자에게 안내하거나 파라미터를 수정해 재시도 |
| LLM이 미등록 tool 호출 | `tool_executor_node`가 `ToolMessage("ERROR: 알 수 없는 tool ...")` 반환. LLM이 다음 턴에 정상 도구로 복구 |
| 도구 함수가 예외를 던짐 (방어선) | `tool_executor_node`의 try/except가 `"ERROR: ... 실행 중 예외: ..."` ToolMessage 반환 |
| `_resolve_branch_db` 위반 | `"ERROR: 허용되지 않은 DB 경로"` 또는 `"ERROR: 존재하지 않는 DB 파일"` 반환 |
| LLM 호출 자체 실패 | wrapper에서 raise (sql_agent와 동일 — 상위 그래프 폴백) |

원칙: ReAct 루프 내부의 도구 실패는 모두 LLM에게 `ToolMessage`로 다시 보여준다. LLM이 (a) 재시도, (b) 사용자 안내, (c) 다른 경로 탐색 중 하나를 선택.

### 8. 멀티턴 흐름 (데모 시나리오 G)

```
[Turn 1 — 정보 부족]
caller: { messages: [HumanMessage("머신 상태 알려줘")], chat_history: [] }
→ query_rewriter: no-op
→ router: → tool_call_agent
→ tool_call_agent ReAct:
   (1) tool_calls 없는 응답: "어느 브랜치의 어느 머신 상태를 조회할까요?
                              등록된 브랜치 목록을 보여드릴까요?"
→ response_generator
→ chat_history 누적

[Turn 2 — 사용자 동의]
caller: { messages: [HumanMessage("응 보여줘")], chat_history: <turn1> }
→ query_rewriter: "전체 브랜치 목록을 보여줘"로 리라이팅
                  (templated_sql 작업에서 추가된 확인 응답 룰이 그대로 동작)
→ router: → tool_call_agent
→ tool_call_agent ReAct:
   (1) list_branches() → markdown
   (2) 자연어 응답: "F-A 아산 1공장, F-B 구미 2공장, F-C 광주 3공장이 있습니다.
                    어느 곳의 머신 상태를 조회할까요?"

[Turn 3 — 사용자 선택]
caller: { messages: [HumanMessage("아산 1공장의 M-001")], chat_history: <turn1+2> }
→ query_rewriter: 머신 상태 의도 보충 ("아산 1공장의 M-001 머신 상태")
→ router: → tool_call_agent
→ tool_call_agent ReAct:
   (1) list_branches() → "아산 1공장" → "F-A" 매핑
   (2) get_branch_db_path("F-A") → "/.../branch_A.db"
   (3) get_machine_status(db_path="/.../branch_A.db", machine_id="M-001")
   (4) 자연어 응답: "F-A(아산 1공장)의 M-001 머신 상태입니다: ..."
```

query_rewriter는 본 작업에서 손대지 않는다. templated_sql 작업에서 추가된 "응/네/보여줘 등 확인 응답 → 직전 제안의 구체 행동을 풀어쓰기" 룰이 그대로 재활용된다.

### 9. 그래프/라우터 통합

기존 프로젝트 패턴으로 자동 반영. 그래프 빌드 코드와 라우터 시스템 프롬프트는 `registry.entries` / `registry.build_workers_prompt()`로 합성되므로 **수정 불필요**.

`src/main.py` 상단의 에이전트 import 블록에 한 줄만 추가:

```python
import src.tool_call_agent  # noqa: F401
```

`src/tool_call_agent/__init__.py`:

```python
from src.tool_call_agent.agent import tool_call_wrapper  # noqa: F401 - 등록 트리거
from src.tool_call_agent.tools import TOOLS, TOOLS_BY_NAME  # noqa: F401
```

`src/main.py`에 데모 시나리오 G 추가 — 위 멀티턴 흐름을 실제 LLM으로 실행.

### 10. CLI 추천 질문 (`res/suggestions.yaml`)

```yaml
tool_call:
  - "어떤 브랜치가 등록되어 있어?"
  - "아산 1공장의 머신 목록 보여줘"
  - "F-A 브랜치의 M-001 머신 상태 알려줘"
  - "구미 2공장에 어떤 머신이 있어?"
  - "머신 상태 조회해줘"   # 부족한 정보 케이스 — clarification 트리거
```

## 테스트 계획

### tests/test_tool_call_tools.py (신규)
임시 디렉토리에 mini fixture DB를 만들어 도구 함수 단위 테스트.

- `list_branches`: 시드된 3개 브랜치가 markdown에 포함
- `get_branch_db_path`:
  - 정상: 등록된 코드 → 절대 경로 반환
  - 미등록 코드 → `"ERROR: 등록되지 않은 branch_code: ..."`
- `list_machines`:
  - 정상: 브랜치 DB의 머신 목록 반환
  - 디렉토리 탈출 시도 (`"../../etc/passwd"`) → `"ERROR: 허용되지 않은 DB 경로"`
  - `meta.db` 경로 주입 → `"ERROR: 허용되지 않은 DB 경로"`
  - 존재하지 않는 .db → `"ERROR: 존재하지 않는 DB 파일"`
- `get_machine_status`:
  - 정상: state/uptime_ratio 컬럼 반환
  - 미존재 machine_id → `"ERROR: 머신을 찾을 수 없습니다: ..."`
- read-only 검증: 도구 실행 후 DB 파일의 mtime 불변
- `_resolve_branch_db` 단위 검증: 절대경로 입력 / 상대경로 입력 / 화이트리스트 위반

### tests/test_tool_call_agent.py (신규)
LLM mock으로 tool_calls 시드. 서브그래프 동작 검증.

- 단일 도구 호출 → 종료
- 멀티 도구 체이닝 (3-step: list_branches → get_branch_db_path → get_machine_status)
- clarification 시나리오 (tool_calls 없이 자연어 응답 → 즉시 END, 도구 실행 노드 미진입)
- 미등록 tool 이름 호출 → `ToolMessage("ERROR: 알 수 없는 tool ...")` → 다음 턴에 정상 도구로 복구
- 도구 예외 노출 → `ToolMessage("ERROR: ... 실행 중 예외: ...")` → 그래프 정상 종료
- wrapper 출력 태깅: 최종 메시지가 `"[조회 결과]\n..."` 접두어로 시작

### tests/test_factory_seed.py (신규)
- `seed.run()` 실행 후 `meta.db`와 3개 `branch_*.db` 생성 확인
- 행 수 검증: meta.branches=3, 각 branch.machines>=3
- idempotent: 두 번 실행해도 행 수 유지

### tests/test_router_routing.py (수정 또는 신규)
- "아산 1공장 M-001 상태" → `tool_call` 라우팅
- "어떤 공장 있어?" → `tool_call` 라우팅
- "직원 평균 급여" → 여전히 `templated_sql` 또는 `sql` (회귀 확인)

### 회귀 테스트
- 기존 `tests/test_templated_sql_agent.py`, `tests/test_sql_backend.py`, `tests/test_query_rewriter.py`가 모두 통과해야 함 — 본 작업은 이들 모듈을 수정하지 않음

### 수동 검증
- `src/main.py` 시나리오 G를 실제 LLM으로 1회 실행해 3턴 시퀀스 로그 확인

### 평가
- `evals/test_cases.yaml`은 본 작업에서 손대지 않음 (out of scope)

## 영향 분석

### 신규 파일
- `src/tool_call_agent/__init__.py`
- `src/tool_call_agent/agent.py`
- `src/tool_call_agent/prompt.py`
- `src/tool_call_agent/tools.py`
- `res/sample_db/factory/seed.py`
- `tests/test_tool_call_tools.py`
- `tests/test_tool_call_agent.py`
- `tests/test_factory_seed.py`

### 자동 생성 (런타임)
- `res/sample_db/factory/meta.db`
- `res/sample_db/factory/branch_A.db`
- `res/sample_db/factory/branch_B.db`
- `res/sample_db/factory/branch_C.db`

### 수정 파일
- `src/main.py` — `import src.tool_call_agent` 한 줄 + 시나리오 G
- `res/suggestions.yaml` — `tool_call` 카테고리 추가
- `README.md` — Architecture 다이어그램, Project Structure, Subagents 표, 데모 목록
- `tests/test_router_routing.py` — `tool_call` 라우팅 케이스 추가 (없으면 신규)

### 변경 없음
- `src/router/router.py` — `registry.build_workers_prompt()`로 자동 합성
- `src/registry.py` — 인터페이스 그대로 사용
- `src/state.py` — 새 필드 불필요
- `src/sql_agent/` — `SqlExecutor` 손대지 않음. `validate_select_only`만 재사용 (import-only)
- `src/templated_sql_agent/` — 영향 없음
- `src/query_rewriter/` — 확인 응답 룰이 templated_sql 작업에서 추가되어 그대로 재활용
- `Agents.md`, `AgentRegistry.md` — 등록 메커니즘 변경 없음

### 외부 인터페이스 영향
- 라우터 description이 `tool_call` 추가로 한 줄 늘어남 → 기존 sql/templated_sql로 가던 케이스 일부가 tool_call로 옮겨갈 수 있음. 평가는 별도 작업에서 검증.
- `validate_select_only`는 import-only 재사용이므로 sql_agent의 동작에 영향 없음.
