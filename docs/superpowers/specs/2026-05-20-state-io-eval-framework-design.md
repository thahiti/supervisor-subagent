# State-IO 워크플로우 및 공통 평가 프레임워크 설계

## 개요

`scripts/cli/`의 워크플로우 함수(`rewrite`, `route_trace`)를 모두 동일한 TypedDict(`CliState`)를 입력·출력으로 받는 state-IO 형태로 통일하고, 두 스모크(`scripts/smoke_query_rewriter.py`, `scripts/smoke_query_rewriter_router.py`)가 공통 평가 구조(`scripts/eval.py`)를 통해 케이스를 등록·실행·검증하도록 재구성한다.

목표 세 가지:

1. **균일한 워크플로우 시그니쳐** — 두 CLI의 워크플로우가 `(CliState) → CliState` 한 가지 형태로 통일된다.
2. **데이터-호출 분리** — 스모크 파일은 `CASES` 데이터와 한 줄 호출만 가지며, 평가 메커니즘(실행·검증·출력)은 한 곳에서 관리된다.
3. **선언적 검증** — `expected`는 출력 state의 어떤 필드를 무엇과 비교할지 선언만 한다. 어션 op는 값의 타입으로 추론된다(같음·정규식·정규식 AND).

## 배경

기존 워크플로우 시그니쳐는 다음과 같이 비대칭이다.

```python
rewrite(query: str, chat_history: list[BaseMessage]) -> str
route_trace(query: str, chat_history: list[BaseMessage]) -> tuple[str, str]
```

기존 스모크는 각자 in-process로 함수를 호출하지만, 입력 구성·반환값 해석·PASS/FAIL 판정·출력 포맷팅을 두 파일이 독립적으로 가지고 있어 중복과 표류 위험이 있다. 평가 규모를 늘리거나 새 워크플로우(예: 다른 에이전트의 트레이스)를 도입할 때 같은 보일러플레이트가 반복된다.

## 아키텍처

```
scripts/
├── cli/
│   ├── _common.py                ← CliState(State) 정의 + 기존 args/유틸
│   ├── query_rewriter.py         ← rewrite(state: CliState) -> CliState
│   └── query_rewriter_router.py  ← route_trace(state: CliState) -> CliState
├── eval.py                       ← 신규: EvalCase, run_eval, 결과 출력
├── smoke_query_rewriter.py       ← CASES 정의 + run_eval(CASES, rewrite, ...)
└── smoke_query_rewriter_router.py← CASES 정의 + run_eval(CASES, route_trace)
```

세 가지 분리 원칙:

- **CLI 모듈**은 워크플로우 함수를 직접 소유한다(이전 설계 결정 유지). 두 CLI 사이의 cross-import는 없다(strict isolation 유지). 각 CLI의 `main()`은 args 파싱 → 초기 `CliState` 구성 → 워크플로우 호출 → 결과 state에서 출력 필드 추출 → stdout 출력만 담당한다.
- **`scripts/eval.py`**는 워크플로우 자체를 모른다. 케이스를 받아 입력 state를 구성하고, 워크플로우를 호출하고, `expected` 어션을 검증하고, 결과를 출력하는 메커니즘만 가진다.
- **스모크 파일**은 데이터(`CASES`)와 한 줄 호출(`sys.exit(run_eval(...))`)만 가진다. 로직 없음.

## 컴포넌트

### CliState (in `scripts/cli/_common.py`)

```python
from typing import NotRequired
from src.state import State


class CliState(State):
    """CLI 워크플로우(rewrite, route_trace)의 state-IO 타입.

    프로덕션 `src.state.State`를 확장하여, 워크플로우가 채우는 편의
    필드를 가진다. NotRequired이므로 입력 단계엔 없어도 되고,
    워크플로우가 출력 state를 만들 때 채워진다.
    """

    rewritten: NotRequired[str]   # rewrite 단계가 생성한 리라이팅 텍스트
    next_node: NotRequired[str]   # route_trace의 router_conditional 결과
```

- 프로덕션 State와 구분되며, 프로덕션 코드는 `CliState`의 추가 필드를 모른다.
- TypedDict 서브클래싱이므로 `query_rewriter_node(state)`, `router_node(state)` 같은 프로덕션 노드에 그대로 전달 가능하다.

### 워크플로우 시그니쳐

```python
# scripts/cli/query_rewriter.py
def rewrite(state: CliState) -> CliState:
    """state["messages"]의 마지막 HumanMessage를 query로 보고
    `query_rewriter_node`를 호출, 결과 메시지를 messages에 누적하고
    `rewritten` 필드에 리라이팅 텍스트를 채워 반환한다.
    """
```

```python
# scripts/cli/query_rewriter_router.py
def route_trace(state: CliState) -> CliState:
    """rewrite 단계를 인라인 수행한 뒤 router_node → router_conditional.

    반환 state에는 `rewritten`, `next_agent`, `next_node`가 모두 채워진다.
    리라이팅 단계는 query_rewriter 모듈에 의존하지 않고 이 함수 안에서
    직접 수행한다(strict isolation; cross-CLI import 없음).
    """
```

두 함수 모두 입력 state를 변형하지 않고 새 dict를 반환한다(``{**state, ...}`` 패턴). 입력 state에 없는 키는 기본값 없이 KeyError를 발생시키지 않도록 방어적으로 처리한다(예: `messages`가 비어 있으면 빈 리스트로 시작).

### EvalCase

```python
class EvalCase(TypedDict):
    """평가 케이스. 케이스 자체는 입력 데이터와 기대 검증값만 가진다.
    실행 정책(고정 시각, 재시도 횟수)은 케이스에 두지 않고 `run_eval`의
    인자로 전달한다.
    """

    id: str
    description: str
    input: dict[str, Any]      # CliState 속성 override
    expected: dict[str, Any]   # 필드 → 기대값(또는 Pattern, 또는 list[Pattern])
```

- `input`은 베이스라인 `CliState`에 머지될 override dict이다. 예: `{"messages": [HumanMessage("...")], "chat_history": to_messages([...])}`.
- `expected`는 출력 state의 필드명을 key로, 기대값을 value로 가진다.

### run_eval API (in `scripts/eval.py`)

```python
def run_eval(
    cases: list[EvalCase],
    workflow: Callable[[CliState], CliState],
    *,
    now: str = "",          # 설정 시 patched_now(now)로 전체 실행을 감쌈
    max_retries: int = 1,   # 어션 FAIL 시 케이스당 재시도 횟수 (예외엔 재시도 없음)
) -> int:
    """각 케이스에 대해 입력 CliState를 구성하고 workflow를 호출,
    expected 어션을 검증하여 PASS/FAIL을 출력한다. 종료 코드: 모두 통과 0, 아니면 1.
    """
```

- `now`와 `max_retries`는 스모크 단위 실행 정책이며 케이스 데이터가 아니다. 리라이터 스모크는 `now=FIXED_NOW, max_retries=3`을, 라우터 스모크는 둘 다 기본값을 사용한다.
- 케이스별로 다른 정책이 필요해질 때만 `EvalCase`에 `NotRequired` 필드로 추가한다(현재는 YAGNI).

### op 추론 규칙

`expected`의 각 value 타입에 따라 어션이 결정된다.

| value 타입 | 어션 의미 |
|---|---|
| `str`, `int`, `bool` 등 plain | `actual == value` (정확히 같음) |
| `re.Pattern` | `value.search(str(actual)) is not None` (정규식 매칭) |
| `list[re.Pattern]` | 모든 패턴이 매치 (정규식 AND) |

`list[re.Pattern]`은 "한 필드에 여러 패턴이 모두 나타나야 한다"는 기존 리라이터 스모크의 요구를 직접 표현한다(예: `[re.compile(r"2026-04-20"), re.compile(r"2026-04-26")]`).

대상 필드가 출력 state에 없을 때는 어션 FAIL로 처리하며, 실제값은 `<missing>` 토큰으로 출력한다.

## 데이터 흐름

```
EvalCase                 baseline CliState         result CliState
─────────                ─────────────────         ───────────────
input dict ─────merge───▶ {messages: [],   ──wf─▶ {messages: [...],
                          next_agent: "",          next_agent: "...",
                          chat_history: []}        chat_history: [...],
                                                   rewritten: "...",
                                                   next_node: "..."}
                                                          │
                                                          ▼
expected dict ───────────────────────────────────▶ field별 어션 검증
                                                          │
                                                          ▼
                                                   PASS / FAIL + diff 출력
```

1. 베이스라인 state: `{"messages": [], "next_agent": "", "chat_history": []}`.
2. `case["input"]`을 dict 머지로 적용해 입력 `CliState`를 만든다.
3. `now`가 설정되어 있으면 `patched_now(now)` 컨텍스트 안에서 `workflow(state)`를 호출한다.
4. 결과 state의 각 `expected` 필드에 대해 op 추론에 따라 어션을 검증한다.
5. 어션 실패 시 `max_retries`까지 재실행한다(예외는 즉시 FAIL, 재시도 없음).
6. 전체 결과를 케이스별로 출력하고 종합 카운트를 출력한다.

## 케이스 예시

### 리라이터 스모크

```python
CASES: list[EvalCase] = [
    {
        "id": "주:지난주",
        "description": "주:지난주",
        "input": {
            "messages": [HumanMessage("지난주 매출 알려줘")],
            "chat_history": [],
        },
        "expected": {
            "rewritten": [re.compile(r"2026-04-20"), re.compile(r"2026-04-26")],
        },
    },
    {
        "id": "coref:번역 결과 → 이거",
        "description": "이거 → 직전 번역 결과 복원",
        "input": {
            "messages": [HumanMessage("이거 일본어로도 번역해줘")],
            "chat_history": to_messages([
                ("human", "Hello, how are you?를 한국어로 번역해줘"),
                ("ai", "안녕하세요, 어떻게 지내세요?"),
            ]),
        },
        "expected": {
            "rewritten": re.compile(r"안녕하세요|Hello"),
        },
    },
]

if __name__ == "__main__":
    sys.exit(run_eval(CASES, rewrite, now="2026-04-29T14:30", max_retries=3))
```

### 라우터 스모크

```python
CASES: list[EvalCase] = [
    {
        "id": "single-math",
        "description": "단일턴 수학",
        "input": {
            "messages": [HumanMessage("3 곱하기 7은 얼마야?")],
            "chat_history": [],
        },
        "expected": {
            "next_node": "math_agent",
        },
    },
    {
        "id": "multiturn-toolcall",
        "description": "공장2 단답 복원 → tool_call_agent",
        "input": {
            "messages": [HumanMessage("공장2")],
            "chat_history": to_messages([
                ("human", "브랜치에서 제품 재고 조사해줘"),
                ("ai", "어떤 브랜치에서 재고를 조사할까요?"),
            ]),
        },
        "expected": {
            "next_node": "tool_call_agent",
        },
    },
]

if __name__ == "__main__":
    sys.exit(run_eval(CASES, route_trace))
```

## 에러 처리

- **누락 필드**: `expected`의 필드가 결과 state에 없으면 FAIL, 실제값 표시는 `<missing>`.
- **예외**: 워크플로우 호출 중 예외는 즉시 FAIL, 재시도 없음. 출력에 `error: <ExceptionType>: <message>` 표시.
- **어션 실패 + max_retries > 1**: 같은 케이스를 재실행하고 시도 횟수를 출력에 표시(예: `(attempts=2)`).
- **`patched_now` 위치**: 전체 실행을 한 번 감싼다(루프 안이 아니라 바깥). 모든 케이스가 동일 시각을 기준으로 한다는 의미를 명확히 한다.

## 테스트

`scripts/eval.py`의 결정적 로직(케이스 입력 머지, op 추론에 따른 어션, 출력 포맷팅)은 `tests/test_route_eval.py`에 추가하는 단위 테스트로 검증한다. 워크플로우는 목으로 대체하여 실제 LLM을 부르지 않는다.

핵심 검증 항목:

- 어션 op 추론: str→eq, Pattern→regex, list[Pattern]→AND.
- 누락 필드 → FAIL + `<missing>`.
- 예외 → 즉시 FAIL, 재시도 없음.
- `max_retries > 1` + 모킹된 워크플로우가 최초 N-1회 실패 후 성공 → PASS, attempts 카운트.
- `now` 설정 → `patched_now`가 한 번 적용되어 케이스 내부에서 `datetime.now()`가 고정값을 반환.

CLI 워크플로우(`rewrite`, `route_trace`)의 state-IO 시그니쳐 자체는 기존 단위 테스트(LLM 목)에 입출력 dict 비교를 추가하여 검증한다.

실제 LLM 검증은 두 스모크 스크립트를 수동 실행해 수행한다(이전과 동일).

## 마이그레이션

원자적 커밋 두 개로 나눈다.

1. **`refactor(cli-state): state-IO 워크플로우 + CliState`**
   - `CliState`를 `scripts/cli/_common.py`에 추가.
   - `rewrite(state) -> state`, `route_trace(state) -> state`로 시그니쳐 변환.
   - 두 CLI `main()`에서 args → 초기 state 구성 → 워크플로우 호출 → 결과 state에서 `rewritten`/`next_node` 추출 → 기존 stdout 포맷 그대로 유지.
   - `tests/test_route_eval.py`: 단위 테스트의 입출력 비교를 dict 기준으로 갱신. 패치 타겟은 변경 없음.
   - 두 스모크는 아직 자체적으로 in-process 호출(평가 프레임워크 미도입). 입력 state 직접 구성 + 결과 state에서 필드 직접 검사로 잠정 갱신.
   - pytest 전부 통과 유지.

2. **`feat(scripts/eval): 공통 평가 프레임워크 + 스모크 갱신`**
   - `scripts/eval.py` 신설: `EvalCase`, `run_eval`, 출력 포맷팅.
   - 두 스모크를 데이터 + `run_eval(...)` 한 줄 호출로 축소.
   - 스모크 실행 결과는 이전 버전과 동등해야 한다(라우터 5/5, 리라이터 기존 7/11 패턴 유지).

## Out of scope

- LLM-as-Judge 평가는 손대지 않는다(`evals/run.py`는 그대로 유지).
- 케이스별 `now`/`max_retries` override는 도입하지 않는다(YAGNI).
- `subprocess` 기반 타임아웃·CLI 종단 테스트는 도입하지 않는다. 평가는 in-process이며 CLI 엔트리포인트 자체는 `tests/test_route_eval.py`의 main() 호출 테스트로만 커버한다.
- 새 어션 op(`contains`, `in`, 커스텀 predicate)는 도입하지 않는다. 현재 두 스모크가 요구하는 eq + regex + regex-AND만 지원한다.
