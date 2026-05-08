# Interactive CLI Design

- 작성일: 2026-05-08
- 상태: Draft (사용자 리뷰 대기)
- 대상 모듈: `src/cli/` (신규), `res/suggestions.yaml` (신규)

## 배경 및 목적

현재 `src/main.py`는 5개의 정해진 데모 시나리오를 일괄 실행한다 (회귀/데모 용도). 실제 사용자가 자유롭게 질문하고 멀티턴으로 상호작용할 수 있는 인터랙티브 진입점이 없다.

본 스펙은 다음 세 가지를 만족하는 터미널 CLI를 추가하는 것을 목적으로 한다.

1. **사용자 입력 기반 멀티턴 대화** — 한 번의 답변으로 끝나지 않고 `chat_history`를 누적하며 이어 질문할 수 있다.
2. **카테고리별 추천 질문 + Fuzzy 자동 제안** — 사용자가 무엇을 물을 수 있는지 즉시 인지하고, 입력 중 fuzzy 매칭으로 추천을 선택·편집할 수 있다.
3. **서브에이전트 처리 과정 스트리밍** — 답변이 끝까지 나오기를 기다리지 않고, 그래프의 각 노드가 끝날 때마다 진행 상황과 핵심 정보를 터미널에 즉시 표시한다.

기존 `src/main.py`는 변경하지 않고 신규 진입점으로 분리한다.

## Non-goals (YAGNI)

명시적으로 제외하는 항목:

- LLM 토큰 단위 스트리밍 (노드 이벤트 단위로 충분)
- 추천 질문 파일의 실시간 watch/reload (재시작 필요)
- 채팅 히스토리 디스크 영속화 (세션 휘발)
- 카테고리별 별도 fuzzy 풀 (단일 평면 풀 + 카테고리 라벨로 충분)
- 슬래시 명령 자동완성
- TUI 위젯/패널 분할 (단순 라인 기반 출력)

## 아키텍처

### 진입점

| 진입점 | 용도 | 변경 여부 |
|--------|------|-----------|
| `python -m src.main` | 5개 데모 시나리오 일괄 실행 (회귀/데모) | 변경 없음 |
| `python -m src.cli` | **신규** 인터랙티브 멀티턴 REPL | 신규 |
| `python -m evals.run` | LLM-as-Judge 평가 | 변경 없음 |

### 신규 모듈 구성

```
src/cli/
├── __init__.py
├── app.py             # REPL 루프 (멀티턴, chat_history 인계)
├── prompt.py          # prompt_toolkit 세션 + 키바인딩
├── suggestions.py     # YAML 로딩 + fuzzy completer 빌드
├── streaming.py       # LangGraph stream → 터미널 노드 이벤트 렌더러
└── commands.py        # 슬래시 명령 dispatcher
res/
└── suggestions.yaml   # 카테고리(에이전트명)별 추천 질문 시드
tests/
├── test_cli_suggestions.py
├── test_cli_streaming.py
├── test_cli_commands.py
└── test_cli_app.py
```

기존 모듈(`src/main.py`, `src/state.py`, `src/registry.py`, 모든 노드/에이전트, `evals/`)은 변경하지 않는다.

### 의존성

| 패키지 | 용도 | 비고 |
|--------|------|------|
| `prompt_toolkit` | 인터랙티브 입력, FuzzyCompleter, 키바인딩 | 신규 추가. fuzzy 매칭 라이브러리 별도 불필요 |
| `pyyaml` | suggestions.yaml 파싱 | 기존 의존성 재사용 |

### 동작 흐름

```
[시작]
 ├─ load_suggestions(res/suggestions.yaml)
 ├─ build_graph()                        # 기존 함수 재사용
 ├─ setup_logging(level=WARNING)         # @log_node 출력 억제
 └─ REPL 루프
     ├─ session.prompt("질문> ")          # fuzzy 자동 제안 활성
     ├─ if 슬래시 명령 → commands.dispatch
     ├─ else:
     │    ├─ for chunk in app.stream(state, stream_mode="updates"):
     │    │    └─ streaming.render(node_name, delta)
     │    └─ chat_history = final["chat_history"]
     └─ /exit | EOF | KeyboardInterrupt(빈 입력) → 종료
```

## 추천 질문 (Suggestions)

### YAML 스키마

```yaml
# res/suggestions.yaml
math:
  - "3과 7을 더하고 그 결과에 5를 곱해주세요"
  - "100을 3으로 나눠줘"
translate:
  - "Hello, how are you?를 한국어로 번역해주세요"
  - "안녕하세요를 영어로 번역"
sql:
  - "직원 수를 알려줘"
  - "이번 달 매출 합계는?"
  - "연봉이 5천만원 이상인 직원은 몇 명인가요?"
```

규칙:

- 최상위 키 = 카테고리. 일반적으로 `registry.agent_names`와 일치해야 한다.
- 미스매치 키는 로딩 시 **WARNING 로그**만 남기고 그대로 사용한다 (실패 아님 — 새 카테고리 점진 도입 가능).
- 누락 또는 빈 파일은 빈 추천으로 동작한다 (자유 입력만 가능, 시작 헤더에 추천 미노출).

### 로딩

`suggestions.py`:

```python
def load_suggestions(path: Path) -> dict[str, list[str]]:
    """suggestions.yaml을 로드하여 카테고리: [질문...] dict로 반환."""
```

시작 시 1회 호출하여 in-memory 캐시. 실시간 watch는 하지 않는다.

### Fuzzy Completer

`prompt_toolkit.completion.FuzzyCompleter`를 사용한다 (별도 라이브러리 불필요).

```python
from prompt_toolkit.completion import FuzzyCompleter, WordCompleter

flat: list[str] = [s for items in suggestions.values() for s in items]
meta: dict[str, str] = {s: agent for agent, items in suggestions.items() for s in items}

base = WordCompleter(
    flat,
    ignore_case=True,
    sentence=True,        # 단어 경계가 아닌 입력 전체로 매칭 (한글/공백 자연스러움)
    match_middle=True,    # substring 매칭 허용
    meta_dict=meta,       # 메뉴 우측에 카테고리 라벨 표시
)
completer = FuzzyCompleter(base)
```

### 시작 헤더

REPL 시작 시 1회, 카테고리별 첫 2개 정도를 미리보기로 출력한다:

```
사용 가능한 추천 질문 (입력 중 자동 제안)
  math      · 3과 7을 더하고 5를 곱해줘
  translate · Hello를 한국어로 번역해줘
  sql       · 이번 달 매출 합계는?

명령: /list <agent>  /reset  /exit  /help
질문>
```

### 입력 중 동작

- 사용자가 타이핑을 시작하면 prompt_toolkit이 자동으로 매칭 메뉴를 표시한다.
- ↑/↓ 또는 Tab으로 후보 이동 / 선택.
- 후보 선택 시 입력란에 **텍스트가 채워지고** 커서가 끝에 위치 → 사용자가 편집 가능.
- Enter로 전송. 후보 메뉴가 열려 있어도 직접 입력한 텍스트로 그대로 보낼 수 있다.

## 슬래시 명령

`commands.py`의 단순 dispatch 테이블 기반.

| 명령 | 동작 |
|------|------|
| `/exit`, `/quit` | REPL 종료 |
| `/reset` | `chat_history`를 빈 리스트로 초기화 |
| `/list` | 모든 카테고리의 추천 질문 출력 |
| `/list <agent>` | 특정 카테고리만 출력 |
| `/help` | 명령 일람 출력 |

알 수 없는 슬래시 명령은 `Unknown command: /xxx (try /help)` 안내 후 프롬프트 복귀.

명령 처리는 LangGraph 호출 **전에** 분기한다. 명령 자체는 chat_history나 그래프 상태에 영향을 주지 않는다 (`/reset` 제외).

## 스트리밍 렌더링

### 호출 방식

`app.invoke()` 대신 `app.stream(state, stream_mode="updates")`. `updates` 모드는 노드 실행 직후 변경된 state delta만 yield하므로 노드 이벤트 단위 표시에 정확히 맞다.

```python
def run_turn(app, user_input: str, chat_history: list[BaseMessage]):
    state = {
        "messages": [HumanMessage(content=user_input)],
        "next_agent": "",
        "chat_history": chat_history,
    }
    final = None
    for chunk in app.stream(state, stream_mode="updates"):
        for node_name, delta in chunk.items():
            renderer.on_node_update(node_name, delta)
        final = chunk
    return final
```

### 출력 포맷

- ANSI 색상 사용 (가독성). 이모지 사용하지 않음.
- 노드 진입 시 `▸ <node> …`를 개행 없이 출력 → 완료 시 `\r`로 같은 줄을 덮어써서 `▸ <node> … done (X.XXs)` + 개행.

```
▸ query_rewriter … done (0.42s)
    rewritten: 이번 달 매출 합계는?
▸ router … done (0.61s)
    next_agent: sql
▸ sql_agent … done (2.13s)
    tools: list_tables, execute_sql
▸ response_generator … done (0.84s)

─────────────────────────────────────
이번 달 매출 합계는 1,234만원입니다.
─────────────────────────────────────
질문>
```

### 노드별 표시 정보

| 노드 | 표시 내용 |
|------|-----------|
| `query_rewriter` | rewritten 메시지 (변경 없으면 `no change`) |
| `router` | `next_agent` + reason 일부 |
| 모든 `*_agent` (math/translate/sql) | 호출된 tool 이름 목록 (delta의 messages에서 `tool_calls` 추출). tool 미사용 시 표시 없음 |
| `response_generator` | 별도 표시 없음. 최종 답변은 구분선 안에 별도 출력 |

`streaming.py`에 `NodeRenderer` 클래스를 두고 노드명 → 포맷 함수 dict를 보유한다. 신규 노드 추가 시 dict에 한 줄 등록하면 된다. 등록되지 않은 노드는 `▸ <node> … done` 만 출력.

### 로깅 충돌 회피

기존 `@log_node`의 INFO 출력은 인터랙티브 터미널을 어지럽힌다. `src/cli/app.py` 시작 시 `setup_logging(level=logging.WARNING)`으로 호출하여 억제한다. `--verbose` 플래그로 INFO 복원할 수 있도록 한다.

## chat_history 인계

`response_generator_node`는 매 턴 종료 시 `chat_history`에 `(HumanMessage, AIMessage)` 두 개를 누적한다 (`operator.add` 리듀서). CLI는 매 turn 마지막 chunk에서 `final["response_generator"]["chat_history"]`를 보관하여 다음 invoke의 입력으로 그대로 전달한다.

```python
chat_history: list[BaseMessage] = []
while True:
    user_input = session.prompt("질문> ")
    if is_command(user_input):
        chat_history = handle_command(user_input, chat_history)
        continue
    final = run_turn(app, user_input, chat_history)
    chat_history = extract_chat_history(final, fallback=chat_history)
```

`/reset`은 `chat_history` 리스트만 빈 것으로 교체한다. 그래프는 stateless이므로 재빌드 불필요.

## 종료 처리

| 트리거 | 동작 |
|--------|------|
| `/exit`, `/quit` | 정상 종료 |
| EOF (Ctrl+D) | 정상 종료 |
| Ctrl+C, 프롬프트 대기 중 | 종료 |
| Ctrl+C, turn 실행 중 | 현재 turn 중단, 프롬프트 복귀, chat_history는 유지 |

prompt_toolkit의 `KeyboardInterrupt` / `EOFError` 처리 패턴을 그대로 사용한다.

## 테스트 전략

| 모듈 | 방식 |
|------|------|
| `cli/suggestions.py` | TDD 단위 테스트 — YAML 로딩, 누락 카테고리 경고, 빈 파일 처리 |
| `cli/streaming.py` | TDD 단위 테스트 — 노드별 포맷터에 mock delta 주입, ANSI 제거 후 문자열 비교 |
| `cli/commands.py` | TDD 단위 테스트 — `/exit`, `/reset`, `/list`, `/list math`, 미지 명령 분기 |
| `cli/prompt.py` | 자동 테스트 제외 — 수동 smoke test |
| `cli/app.py` | 통합 테스트 1개 — graph mock으로 1턴 실행 후 chat_history 인계 검증 |

`superpowers:test-driven-development` 스킬에 따라 Red → Green → Commit 사이클로 진행한다. 각 모듈 단위 테스트가 통과한 직후 commit (CLAUDE.md atomic-commit 원칙).

## 점진 도입 (커밋 단위)

1. `chore: prompt_toolkit 의존성 추가`
2. `feat(cli): suggestions YAML 로더 + 단위 테스트`
3. `feat(cli): 슬래시 명령 dispatcher + 단위 테스트`
4. `feat(cli): 노드 이벤트 스트리밍 렌더러 + 단위 테스트`
5. `feat(cli): prompt_toolkit 세션 + fuzzy completer (수동 smoke)`
6. `feat(cli): REPL 루프 + chat_history 인계 통합 테스트` — `python -m src.cli` 동작 시작
7. `chore: res/suggestions.yaml 시드 데이터 추가`
8. `docs: README에 인터랙티브 CLI 사용법 추가`

각 커밋은 단독으로 그린 빌드. 6번까지는 추천 데이터 없이도 자유 입력으로 동작하므로 7번이 늦게 합류해도 무방하다.

## 기존 코드와의 호환성

- `src/main.py`, `src/state.py`, `src/registry.py`, 모든 노드/에이전트 — **변경 없음**
- `evals/` — **변경 없음** (CLI는 graph만 소비, 평가 시스템과 독립)
- 신규 디렉토리 `src/cli/`만 추가, 삭제/이동 없음

## 미해결 이슈 (Open Questions)

없음. 모든 결정 항목이 본 문서에 반영되었다.
