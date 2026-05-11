# templated_sql 에이전트 — 정해진 SQL 템플릿 기반 조회

## 배경 / 목적

기존 `sql` 에이전트는 자유형 text-to-SQL ReAct 패턴으로 임의의 자연어 질의를 SQL로 번역해 실행한다. 표현력은 높지만 (a) SQL 생성 정확도가 LLM에 의존하고 (b) 동일한 양식의 조회 패턴이 반복될 때 매번 처음부터 SQL을 생성하는 비용이 든다.

본 작업은 **사전 정의된 SQL 템플릿에 사용자가 명시한 변수만 채워 실행하는 구조화된 조회 에이전트**(`templated_sql`)를 추가한다. 운영 환경에서 "이런 패턴의 질의는 항상 이 SQL로 해결한다"가 합의된 도메인에 적합하다. 기존 `sql` 에이전트와는 공존하며, 라우터가 자동 합성된 description으로 두 에이전트를 구분한다.

핵심 행동 원칙:

1. **변수는 사용자가 명시하지 않으면 채우지 않는다.** 에이전트가 임의로 추측하거나 디폴트를 적용하지 않는다.
2. **변수 후보값은 사용자 동의가 있을 때만 조회한다.** 에이전트는 "전체 지점 목록을 보여드릴까요?" 형태의 자연어 제안을 하고, 사용자가 동의하면 미리 등록된 lookup SQL을 실행해 결과 표를 보여준다. 사용자는 그 결과를 보고 다음 턴에 원하는 값을 명시한다.
3. **멀티턴 흐름은 query_rewriter가 처리한다.** templated_sql 에이전트 자체는 chat_history를 보지 않으며, query_rewriter가 만든 자기완결 입력만 본다.

## 범위

### In scope
- `src/templated_sql_agent/` 신규 모듈 (`registry.py`, `templates.py`, `render.py`, `prompt.py`, `agent.py`, `__init__.py`)
- `src/sql_agent/backend/executor.py`의 `SqlExecutor.execute()`에 named-param 바인딩 인자 추가
- `src/query_rewriter/prompt.py`의 "대화 맥락 보충" 섹션에 확인 응답 룰 한 줄 추가
- 라우터 description은 등록된 템플릿에서 자동 합성
- v1 카탈로그: ecommerce.db 기반 5개 템플릿
- 단위/통합 테스트
- `README.md`/`AgentRegistry.md` 문서 업데이트
- `res/suggestions.yaml`에 `templated_sql` 카테고리 추가

### Out of scope
- `evals/test_cases.yaml` 테스트 케이스 추가 — 별도 작업으로 분리
- 새 도메인 DB 추가 (편의점 등) — ecommerce.db 재활용으로 합의
- 템플릿 외부 정의 (YAML 등) 또는 동적 등록
- 변수 후보값 캐싱
- 에이전트가 lookup_sql 결과 표를 LLM에게 다시 보여 변수 값을 자동 추론하는 흐름

## 설계

### 1. 디렉토리 구조

```
src/templated_sql_agent/
├── __init__.py        # templates.py를 import 해 등록을 트리거
├── registry.py        # SqlTemplate / TemplateVariable / TemplateRegistry (도메인 무지)
├── templates.py       # ecommerce 도메인 SqlTemplate 인스턴스 정의 (도메인 인식)
├── render.py          # 변수 검증·타입 강제 + (sql, params) 튜플 생성
├── prompt.py          # action 분류 + 변수 추출용 시스템 프롬프트 빌더
└── agent.py           # @registry.agent("templated_sql") wrapper + LLM 호출 + 분기 실행
```

기존 `sql_agent/`의 frontend(도메인 인식) ↔ backend(도메인 무지) 분리 철학을 동일하게 적용한다. 다른 도메인을 붙이려면 `templates.py`만 새로 작성하면 된다.

### 2. 데이터 모델 (`registry.py`)

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class TemplateVariable:
    name: str                                   # SQL named placeholder 키 (예: "store_id")
    description: str                            # 사용자/LLM 양쪽에 노출되는 의미
    sql_type: Literal["int", "text", "date"]    # coercion + 안전 검증용
    lookup_sql: str | None = None               # 후보값 조회용 SELECT (정적 등록)

@dataclass(frozen=True)
class SqlTemplate:
    id: str                                     # 라우팅·로깅 키 (예: "product_stock")
    intent: str                                 # 라우터 description/카탈로그 표시용 한 줄
    sql: str                                    # :name 형식 named placeholder만 사용
    variables: tuple[TemplateVariable, ...]
```

`frozen=True`로 불변. `variables`는 tuple로 hashable 보장.

`sql_type`이 LLM에게 노출되는 의미는 다음과 같다 — coercion 규칙과 시스템 프롬프트 가이드를 동일 어휘로 묶어 두기 위함이다:
- `"int"` — 정수 ID 또는 수량.
- `"text"` — 카테고리/도시명/주문 상태 같은 문자열 값. lookup_sql이 있는 경우 결과 표에서 그대로 복사해 사용.
- `"date"` — `YYYY-MM-DD` 형식 단일 날짜 또는 `YYYY-MM` 같은 월 단위 문자열. 정규식으로 형식 검증.

### 3. 레지스트리 (`registry.py`)

```python
class TemplateRegistry:
    def __init__(self) -> None:
        self._templates: list[SqlTemplate] = []
        self._by_id: dict[str, SqlTemplate] = {}

    def register(self, template: SqlTemplate) -> None:
        """등록 시점에 다음을 검증하고 실패 시 ValueError를 즉시 발생시킨다.

        1. id 중복 금지.
        2. sql의 :name placeholder 집합과 variables의 name 집합이 정확히 일치.
        3. 각 lookup_sql은 SELECT-only (백엔드 safety.validate_select_only 재활용).
        """

    @property
    def templates(self) -> list[SqlTemplate]: ...   # 등록 순서 보존 (방어 복사)

    def get(self, template_id: str) -> SqlTemplate | None: ...

    def build_router_description(self) -> str: ...
    def build_catalog_for_llm(self) -> str: ...

template_registry = TemplateRegistry()
```

`build_router_description()`이 반환하는 문자열 형식:

```
사전 정의된 SQL 템플릿 기반의 데이터 조회를 처리합니다. 각 조회에 필요한 변수의
후보값을 사용자에게 안내하고, 사용자 동의 시 후보값을 조회해 표로 제시하는 흐름도
이 에이전트가 처리합니다. 다음 종류의 질의를 다룹니다:
- <intent_1>
- <intent_2>
- ...
```

이 문자열을 `@registry.agent("templated_sql", description=template_registry.build_router_description())`로 직접 주입한다. (현재 `AgentRegistry.register()`가 description 직접 주입을 지원함 — `src/registry.py:33-65`)

`build_catalog_for_llm()`이 반환하는 문자열 형식 (LLM 시스템 프롬프트에 들어감):

```
## 처리 가능한 질의 템플릿

### template_id: product_stock
의도: 특정 제품의 현재 재고 조회
변수:
- product_id (int): 조회 대상 제품. 후보값 조회 가능.

### template_id: dept_avg_salary
...
```

`lookup_sql` 본문은 LLM에게 노출하지 않는다. LLM은 "후보값 조회 가능" 여부만 알면 되며, 실행은 에이전트가 직접 수행한다.

### 4. 등록 메커니즘

기존 `AgentRegistry`와 동일한 "모듈 import 시 부수효과 등록" 패턴.

```python
# src/templated_sql_agent/templates.py
from src.templated_sql_agent.registry import (
    SqlTemplate, TemplateVariable, template_registry,
)

template_registry.register(SqlTemplate(
    id="product_stock",
    intent="특정 제품의 현재 재고 조회",
    sql="SELECT id, name, category, stock FROM products WHERE id = :product_id",
    variables=(
        TemplateVariable(
            name="product_id",
            description="조회 대상 제품의 id",
            sql_type="int",
            lookup_sql="SELECT id, name, category FROM products ORDER BY category, name",
        ),
    ),
))
# ... 나머지 4개
```

```python
# src/templated_sql_agent/__init__.py
from src.templated_sql_agent import templates  # noqa: F401  - 등록 트리거
from src.templated_sql_agent.agent import templated_sql_wrapper  # noqa: F401
```

진입점(`src/main.py` 또는 그래프 빌드 직전)에서 `import src.templated_sql_agent`만 추가하면 등록·노드 추가가 자동 반영된다. 이 import는 기존 sql/math/translate 에이전트 import와 같은 자리에 둔다.

### 5. v1 도메인 카탈로그 (`templates.py`)

ecommerce.db의 기존 테이블 (`departments`, `employees`, `customers`, `products`, `orders`, `order_items`)을 활용한 5개 템플릿:

| id | intent | 변수 (이름, sql_type, lookup) |
|---|---|---|
| `dept_avg_salary` | 특정 부서의 평균 급여 | `dept_id` (int, ✅ `SELECT id, name FROM departments ORDER BY name`) |
| `product_stock` | 특정 제품의 현재 재고 | `product_id` (int, ✅ `SELECT id, name, category FROM products ORDER BY category, name`) |
| `category_top_n_revenue` | 특정 카테고리의 매출 상위 N개 제품 | `category` (text, ✅ `SELECT DISTINCT category FROM products ORDER BY category`), `n` (int, ❌) |
| `customer_orders` | 특정 고객의 주문 내역 | `customer_id` (int, ✅ `SELECT id, name, city FROM customers ORDER BY name`) |
| `monthly_order_count` | 특정 월의 특정 상태 주문 수 | `year_month` (text "YYYY-MM", ❌), `status` (text, ✅ `SELECT DISTINCT status FROM orders ORDER BY status`) |

각 메인 SQL은 named placeholder를 사용하며, `inject_limit_if_missing`이 자동 적용된다.

### 6. 실행 흐름 (`agent.py`)

서브그래프 없이 `translate_agent`와 동일한 **단일 노드 패턴**. ReAct 루프가 필요 없으므로 WorkerState도 불필요.

```python
@registry.agent("templated_sql", description=template_registry.build_router_description())
@log_node("templated_sql")
def templated_sql_wrapper(state: State) -> dict:
    llm = get_chat_model()
    system_prompt = build_system_prompt(template_registry)
    response = llm.invoke([SystemMessage(content=system_prompt)] + state["messages"])
    parsed = _parse_action_json(response.content)

    if parsed["action"] in {"no_match", "ask_clarification"}:
        return _emit(parsed["clarification"])

    template = template_registry.get(parsed["template_id"])
    if template is None:
        return _emit(_no_match_message(template_registry))

    if parsed["action"] == "execute_lookup":
        return _emit(_run_lookups(template, parsed["lookup_vars"]))

    # execute_main
    return _emit(_run_main(template, parsed["extracted"]))
```

`_emit(text)`는 `{"messages": [AIMessage(content=f"[조회 결과]\n{text}")]}` 형태의 dict를 반환한다(기존 에이전트들과 동일한 태깅 컨벤션).

`_run_lookups(template, lookup_vars)`:
- `lookup_vars`의 각 변수가 (a) 해당 템플릿에 실제 등록된 변수이고 (b) `lookup_sql`이 `None`이 아닌 경우에만 실행 대상. 둘 중 하나라도 위반되면 해당 변수는 조용히 skip하고 나머지만 진행. 모두 skip되면 "조회 가능한 후보값이 없습니다. 변수 값을 직접 알려주세요."로 응답.
- 각 변수의 `lookup_sql`을 `SqlExecutor.execute(sql)`로 실행 (params 없음).
- 결과 markdown 표를 변수 description과 함께 묶어 하나의 메시지로 반환:
  ```
  [지점 목록]
  | id | name | location |
  ...
  
  [라면 제품 목록]
  | id | name | category |
  ...
  
  원하시는 값을 알려주시면 조회를 진행합니다.
  ```

`_run_main(template, extracted)`:
- `render(template, extracted)`로 `(sql, params)` 생성.
- 실패 시(`TemplateRenderError`) "다음 변수를 다시 확인해 주세요: …" 안내 + 카탈로그 변수 스키마 노출.
- 성공 시 `SqlExecutor.execute(sql, params)`로 실행, markdown 결과 반환.

### 7. 시스템 프롬프트 (`prompt.py`)

```
당신은 사전 정의된 SQL 템플릿 기반의 조회를 수행하는 에이전트입니다.
한 번의 호출에서 다음 중 정확히 하나의 action을 결정해 JSON으로 반환하세요.

## action 정의

- "execute_main": 사용자가 매핑된 템플릿의 모든 변수 값을 명시했고, 그 값을
  그대로 사용해 메인 SQL을 실행할 수 있을 때.
- "ask_clarification": 매핑된 템플릿이 있지만 필요한 변수 일부 또는 전부가
  사용자 메시지에서 추출되지 않을 때. 어떤 변수가 부족한지 자연어로 묻고,
  해당 변수에 후보값 조회가 가능하면 "전체 ~ 목록을 보여드릴까요?" 형태로
  제안한다.
- "execute_lookup": 사용자가 직전 ask_clarification 제안에 동의해(예: "응",
  "보여줘", "전체 지점 목록 보여줘") 변수 후보값을 조회해 달라고 한 경우.
  어떤 변수의 후보값을 조회할지 lookup_vars 리스트로 명시한다.
- "no_match": 어떤 템플릿과도 의미가 일치하지 않을 때. 사용자에게 처리 가능한
  질의 종류를 안내한다.

## 처리 규칙

- 변수 값을 임의로 추측하지 마세요. 사용자가 명시하지 않았으면 missing입니다.
- 디폴트(예: "전체", "all")를 적용하지 마세요. 항상 사용자의 명시적 선택을
  받아야 합니다.
- lookup_sql 본문은 보이지 않습니다. 후보값 조회 가능 여부만 카탈로그에
  표시됩니다.

## 출력 형식 (정확히 이 JSON만)

```json
{
  "action": "execute_main|ask_clarification|execute_lookup|no_match",
  "template_id": "<id 또는 null>",
  "extracted": {"<var>": <value>, ...},
  "lookup_vars": ["<var>", ...],
  "clarification": "<사용자에게 보여줄 자연어. ask_clarification/no_match일 때만 사용>"
}
```

## 처리 가능한 질의 템플릿

{catalog}
```

`{catalog}`는 `template_registry.build_catalog_for_llm()`로 치환.

### 8. 안전 치환 (`render.py`)

```python
class TemplateRenderError(ValueError):
    pass

def render(template: SqlTemplate, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """args를 검증·정제해 (sql, params) 튜플을 반환.

    - 누락된 변수가 있으면 TemplateRenderError.
    - sql_type별 coercion:
        "int"  → int(value)  (실패 시 TemplateRenderError)
        "text" → str(value).strip()  (빈 문자열이면 TemplateRenderError)
        "date" → r"^\d{4}-\d{2}(-\d{2})?$" 정규식 매칭 (불일치 시 TemplateRenderError)
    """
```

반환된 `(sql, params)`는 `SqlExecutor.execute(sql, params)`에서 `cursor.execute(sql, params)`로 sqlite3 named-param 바인딩된다. 문자열 포맷팅(`%` / `.format` / f-string)은 사용하지 않는다 — SQL injection 차단의 유일한 보장이다.

### 9. SqlExecutor 시그니처 확장

`src/sql_agent/backend/executor.py:71` 의 `execute(query: str)`를 다음과 같이 확장:

```python
def execute(self, query: str, params: dict[str, Any] | None = None) -> ExecutionResult:
    try:
        validate_select_only(query)
    except UnsafeSqlError as exc:
        ...

    safe_query = inject_limit_if_missing(query, self._row_limit)
    return self._run_query(safe_query, params)

def _run_query(self, query: str, params: dict[str, Any] | None = None) -> ExecutionResult:
    ...
    cursor = conn.execute(query, params or {})
    ...
```

- `params=None`이면 기존 동작과 동등 (`{}` 바인딩은 placeholder가 없는 쿼리에 영향 없음).
- 기존 `sql_agent`의 `execute_sql` 도구(`src/sql_agent/tools.py:27`)는 변경 없이 동작.

### 10. query_rewriter 프롬프트 보강

`src/query_rewriter/prompt.py:198-202`의 "### 2. 대화 맥락 보충" 섹션 불릿 리스트에 한 줄을 추가한다.

추가될 룰:

```
- "응", "네", "그래", "예", "보여줘" 등 확인 응답 → 직전 에이전트 메시지가 제안한
  구체 행동을 명시적으로 풀어서 재작성 (예: "응" → "전체 지점 목록과 라면 제품
  목록을 보여줘")
```

이 룰은 templated_sql 에이전트의 멀티턴 흐름(ask_clarification → 사용자 동의 → execute_lookup)을 시스템 차원에서 가능하게 하는 안전망이다. 다른 에이전트의 멀티턴에도 동일한 효과가 있다.

### 11. 라우터/그래프 통합

- 그래프 빌드(`src/main.py`)는 `registry.entries`를 순회하므로 templated_sql이 등록되면 자동으로 노드/엣지가 추가된다. **그래프 빌드 코드 수정 불필요.**
- 라우터 시스템 프롬프트(`src/router/router.py`)도 `registry.build_workers_prompt()`로 자동 합성되므로 **별도 수정 불필요.**
- 단, 진입점 import 목록에 `import src.templated_sql_agent`를 추가해야 등록이 트리거된다.

### 12. CLI 추천 질문 (`res/suggestions.yaml`)

`templated_sql` 카테고리를 새로 추가하고, 5개 템플릿 각각에 매칭되는 자연어 질문을 1~2개씩 시드한다. 예:

```yaml
templated_sql:
  - "엔지니어링 부서 평균 급여 알려줘"
  - "상품 id 5번 재고는?"
  - "전자기기 카테고리 매출 상위 3개"
  - "고객 id 12번 주문 내역"
  - "2026-04 paid 주문이 몇 건?"
```

## 데이터 흐름 (멀티턴 시연)

```
[Turn 1]
caller invoke({messages: [HumanMessage("라면 재고 알려줘")], chat_history: []})
  → query_rewriter: chat_history 비어 있음 → no-op
  → router: → templated_sql_agent
  → templated_sql:
       LLM: { action: "ask_clarification",
              template_id: "product_stock",
              missing-like 안내: clarification }
       → "어느 제품의 재고를 조회할까요?
          전체 제품 목록을 보여드릴까요?"
  → response_generator
  → chat_history 누적

[Turn 2]
caller invoke({messages: [HumanMessage("응 보여줘")], chat_history: <turn1>})
  → query_rewriter:
       → "전체 제품 목록을 보여줘" 로 리라이팅
  → router: → templated_sql_agent
  → templated_sql:
       LLM: { action: "execute_lookup",
              template_id: "product_stock",
              lookup_vars: ["product_id"] }
       → product_stock의 product_id.lookup_sql 실행
       → "| id | name | category | ... |"
  → response_generator

[Turn 3]
caller invoke({messages: [HumanMessage("상품 id 5번 재고")], chat_history: <turn1+2>})
  → query_rewriter: no-op (이미 명확)
  → router: → templated_sql_agent
  → templated_sql:
       LLM: { action: "execute_main",
              template_id: "product_stock",
              extracted: {"product_id": 5} }
       → render → executor.execute(sql, {"product_id": 5})
       → 결과 markdown
  → response_generator
```

## 에러 처리

- LLM JSON 파싱 실패 → action=`no_match`로 폴백 + 처리 가능 질의 종류 안내. 라우터 폴백 패턴과 동형.
- LLM이 반환한 `template_id`가 미등록 → 동일하게 `no_match` 처리.
- `render`에서 `TemplateRenderError` → 사용자에게 "다음 변수가 잘못되었거나 누락되었습니다: …" 안내 + 해당 변수의 description/sql_type 노출. 그래프 자체는 정상 종료.
- `SqlExecutor.execute()`가 `ok=False`로 반환 → markdown 결과(`ERROR: ...`)를 그대로 노출 (기존 sql_agent와 동일 컨벤션).
- `_run_lookups`에서 일부 변수의 lookup이 실패하면 성공한 표 + 실패한 변수의 에러 메시지를 함께 노출 (조회 자체는 실행 사실을 사용자에게 알림).
- import 시 등록 검증 실패(중복 id, placeholder 불일치, lookup_sql이 SELECT-only가 아님)는 즉시 `ValueError` → 런타임이 아닌 모듈 로드 시점에 깨짐.

## 테스트 계획

### tests/test_templated_sql_registry.py (신규)
- 정상 등록: 등록 후 `templates`, `get`, `build_router_description`, `build_catalog_for_llm` 출력 검증.
- 중복 id 거부: 같은 id 두 번 register → `ValueError`.
- placeholder 불일치 거부: sql에 `:foo`만 있고 variables에 `bar`만 있으면 `ValueError`.
- 비-SELECT lookup_sql 거부: `INSERT ...` lookup_sql 등록 시 `ValueError`.

### tests/test_templated_sql_render.py (신규)
- 정상: int/text/date 각 sql_type별 정상 coercion 후 (sql, params) 검증.
- 누락 변수: `args`에 key가 없으면 `TemplateRenderError`.
- int 캐스팅 실패: `args["product_id"] = "abc"` → `TemplateRenderError`.
- date 형식 위반: `"2026/05/11"` → `TemplateRenderError`. `"2026-05"` 및 `"2026-05-11"`은 허용.
- text 빈 문자열: `""` → `TemplateRenderError`.

### tests/test_templated_sql_agent.py (신규)
- 4가지 action 분기 각각 (LLM mock으로 JSON 응답 시드):
  - `execute_main` → executor mock 호출 검증 (named params 전달 확인).
  - `ask_clarification` → AIMessage content가 clarification 그대로.
  - `execute_lookup` → 지정된 variable의 lookup_sql이 executor에 전달되는지 검증.
  - `no_match` → 안내 메시지에 등록 템플릿 intent들이 포함되는지.
- LLM JSON 파싱 실패 → `no_match` 폴백.
- 미등록 template_id 반환 → `no_match` 폴백.
- `_run_main`에서 `TemplateRenderError` → 안내 메시지 반환 (예외가 그래프 밖으로 새지 않음).

### tests/test_sql_backend.py (수정)
- `execute(query, params)` 시그니처 회귀 테스트: `params` 미전달 시 기존 동작 보존.
- `params` 전달 시 sqlite3 named-param 바인딩이 적용되는지 (`:foo` 치환).

### tests/test_query_rewriter.py (수정)
- 신규: 직전 AIMessage가 "전체 …을 보여드릴까요?"이고 현재 입력이 "응" 또는 "보여줘"일 때, 리라이팅 결과가 직전 제안의 구체 행동을 명시적으로 풀어 쓰는지 검증 (LLM 응답 mock).

### scripts/Smoke 또는 main.py 시나리오
- `src/main.py`에 시나리오 F를 추가해 위 [데이터 흐름] 3턴 시퀀스를 실제 실행하고 로그 출력.

## 영향 분석

### 변경 대상 파일
- 신규: `src/templated_sql_agent/` 전체 (`__init__.py`, `registry.py`, `templates.py`, `render.py`, `prompt.py`, `agent.py`)
- 수정: `src/sql_agent/backend/executor.py` — `execute()` 시그니처 확장
- 수정: `src/query_rewriter/prompt.py` — "대화 맥락 보충" 룰 한 줄 추가
- 수정: `src/main.py` (또는 에이전트 import 진입점) — `import src.templated_sql_agent` 한 줄, 시나리오 F 추가
- 수정: `res/suggestions.yaml` — `templated_sql` 카테고리 추가
- 수정: `README.md` — Project Structure, Subagents 표, 데모 시나리오 목록
- 수정: `AgentRegistry.md` — 본 작업으로 변경되는 메커니즘은 없음. 단, 새 워커 등록 사례로 templated_sql을 짧게 언급할 수 있음 (선택)
- 신규/수정 테스트: 위 [테스트 계획] 참조

### 변경 없음
- `src/router/router.py` — registry 기반 라우팅이므로 자동 반영
- `src/registry.py` — 인터페이스 그대로 사용
- `src/state.py` — 새 필드 불필요
- `src/sql_agent/frontend/*` — 자유형 sql 에이전트는 그대로

### 외부 인터페이스 영향
- `SqlExecutor.execute()`에 optional `params` 인자가 추가됨. 기존 호출자(`src/sql_agent/tools.py:27`의 `execute_sql`)는 영향 없음 (default `None`).
- 라우터 description이 templated_sql 추가로 늘어남 → 기존 sql 에이전트로 라우팅되는 케이스 중 일부가 templated_sql로 옮겨갈 수 있음. 평가 시 확인 필요(별도 작업).
