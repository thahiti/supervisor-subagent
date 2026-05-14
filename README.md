# Supervisor-Subagent

LangGraph 기반의 멀티 에이전트 시스템. Router가 사용자 요청을 분석하여 가장 적합한 전문 Subagent에게 한 번 위임하고, 결과를 페르소나가 적용된 최종 답변으로 정리한다.

## Architecture

```
[START] → [query_rewriter] → [router] ─┬→ [math_agent]          ─┐
                                       ├→ [translate_agent]      │
                                       ├→ [sql_agent]            ├→ [response_generator] → [END]
                                       ├→ [templated_sql_agent]  │
                                       ├→ [tool_call_agent]      │
                                       └→ [response_generator] (FINISH)
```

- **query_rewriter** — 사용자 쿼리에 시간 표현 해석(예: "지난주" → `2026-04-27~2026-05-03`), 대화 맥락 보충, 용어 사전 치환을 적용해 명확한 형태로 재작성한다.
- **router** — 단발성 라우팅. 사용자 요청을 분석해 가장 적합한 워커 하나만 선택하고, 적합한 워커가 없으면 `FINISH`로 곧바로 답변 생성 단계로 넘긴다.
- **subagents** — `math`, `translate`, `sql`, `templated_sql`, `tool_call` 중 선택된 하나만 실행된다.
- **response_generator** — 서브에이전트 결과를 페르소나에 맞춰 최종 답변으로 정리하고, 멀티턴 컨텍스트를 위해 `chat_history`에 한 턴(리라이팅된 사용자 질의 + 최종 출력)을 누적한다.

## Quick Start

```bash
cp .env.example .env              # OPENAI_API_KEY 설정
uv sync                           # 의존성 설치
uv run python -m src.cli          # 인터랙티브 CLI 실행 (멀티턴 + 추천)
uv run python -m res.sample_db.factory.seed  # tool_call용 multi DB 시드 (최초 1회)
uv run python -m src.main         # 5개 데모 시나리오 일괄 실행
uv run python -m evals.run        # LLM-as-Judge 평가 실행
```

데모 시나리오:
- **A** 수학 계산 (math)
- **B** 번역 (translate)
- **C** 복합 요청 — router가 주된 의도 하나만 선택
- **D** SQL 조회 (sql) — `res/sample_db/ecommerce.db` 자동 시드
- **E** 멀티턴 — 1차 응답을 `chat_history`로 인계해 "이거 다시 영어로" 같은 지시어 해석 검증
- **F** templated_sql 멀티턴 — 변수 부족 → 후보값 조회 → 실행의 3턴 시연
- **G** `tool_call` 멀티턴 — 제조업 브랜치별 머신 DB 조회 (정보 부족 → 브랜치 목록 → 머신 상태)의 3턴 시퀀스 시연

## Project Structure

```
supervisor-subagent/
├── src/
│   ├── main.py                   # 엔트리포인트 + 그래프 빌드
│   ├── state.py                  # 공유 State / WorkerState 정의
│   ├── registry.py               # 에이전트 레지스트리 (글로벌 인스턴스)
│   ├── llm.py                    # ChatOpenAI 팩토리 (모델 중앙화)
│   ├── cli/                      # 인터랙티브 REPL (멀티턴 + 추천 + 스트리밍)
│   ├── query_rewriter/           # 쿼리 전처리 (시간/맥락/용어)
│   ├── router/                   # 단발성 라우팅 노드
│   ├── response_generator/       # 페르소나 기반 최종 답변
│   ├── supervisor/               # (legacy) 반복 위임형 Supervisor
│   ├── math_agent/               # 수학 ReAct 에이전트 (add/multiply/divide)
│   ├── translate_agent/          # 한↔영 번역 (LLM 직접 호출)
│   ├── sql_agent/                # Text-to-SQL ReAct 에이전트
│   │   ├── frontend/             #   도메인 인식 레이어 (스키마 + few-shot)
│   │   └── backend/              #   도메인 무지 SQLite 실행기 (read-only)
│   ├── templated_sql_agent/       # 사전 정의 SQL 템플릿 기반 조회
│   │   ├── registry.py            #   SqlTemplate / TemplateRegistry
│   │   ├── templates.py           #   ecommerce 도메인 5개 템플릿 등록
│   │   ├── render.py              #   변수 검증 + named-param 바인딩
│   │   ├── prompt.py              #   action 분류용 시스템 프롬프트
│   │   └── agent.py               #   wrapper + 4-action 분기
│   ├── tool_call_agent/      # 함수형 도구 ReAct 기반 멀티 DB 조회 (제조업 브랜치/머신)
│   │   ├── agent.py          #   ReAct 서브그래프 + wrapper
│   │   ├── tools.py          #   4개 @tool 함수 + path 화이트리스트 + sqlite 헬퍼
│   │   └── prompt.py         #   범용 시스템 프롬프트 (도메인 어휘 없음)
│   └── logging/                  # @log_node 데코레이터 + git diff 스타일 출력
├── evals/                        # LLM-as-Judge 평가 시스템
├── res/
│   ├── test_cases.yaml           # 평가 테스트 케이스
│   ├── suggestions.yaml          # 인터랙티브 CLI 추천 질문 (카테고리=에이전트명)
│   ├── sample_db/                # ecommerce 샘플 DB (스키마 + 시드)
│   └── sample_db/factory/    # 제조업 메타DB + 3개 브랜치 DB 시드 (tool_call용)
├── tests/                        # 단위 테스트 (pytest)
├── scripts/                      # 스모크 테스트 등 보조 스크립트
└── docs/superpowers/             # 설계 문서 (specs, plans)
```

## State

| 필드 | 타입 | 리듀서 | 역할 |
|------|------|--------|------|
| `messages` | `list[BaseMessage]` | `add_messages` | 단일 invocation 내의 메시지 흐름 |
| `next_agent` | `str` | 없음 | 라우터가 결정한 다음 워커 (또는 `FINISH`) |
| `chat_history` | `list[BaseMessage]` | `operator.add` | 호출자가 인계하는 큐레이션된 과거 대화. 한 턴 종료 시 `(HumanMessage, AIMessage)` 2개가 누적 |

서브그래프는 별도의 `WorkerState`(메시지만 보유)를 사용하여 `tool_calls`/`ToolMessage` 같은 내부 메시지가 메인 그래프를 오염시키지 않도록 격리한다.

## Subagents

| 에이전트 | 패턴 | 도구 / 데이터 |
|---------|------|--------------|
| `math` | ReAct | `add`, `multiply`, `divide` |
| `translate` | LLM 직접 호출 | 한↔영 번역 |
| `sql` | ReAct (frontend/backend 분리) | `execute_sql`, `list_tables`, `get_schema` (read-only SQLite) |
| `templated_sql` | LLM 직접 호출 + 분기 | 정적 등록 `SqlTemplate` 카탈로그, lookup_sql, `SqlExecutor` 재활용 |
| `tool_call` | ReAct | `list_branches`, `get_branch_db_path`, `list_machines`, `get_machine_status` (factory 메타DB + 브랜치별 sqlite, read-only) |

새 에이전트 추가는 wrapper 함수에 `@registry.agent("name")` 데코레이터 한 줄과 docstring만으로 끝난다 — 그래프 빌드 코드, 라우터 프롬프트, 라우터 분기 모두 자동으로 반영된다. 자세한 메커니즘은 [AgentRegistry.md](./AgentRegistry.md) 참조.

## SQL Agent: Frontend / Backend 분리

`sql_agent`는 도메인 인식 책임(`frontend/`)과 안전한 실행 책임(`backend/`)을 분리한다.

- **Frontend** — 시스템 프롬프트에 스키마 + few-shot을 주입하고, Backend를 감싼 LangChain `@tool`을 LLM에 바인딩한다.
- **Backend (`SqlExecutor`)** — 도메인을 모르는 SQLite read-only 실행기. **3중 안전망**으로 보호된다:
  1. `safety.validate_select_only` — SELECT 외 키워드 거부
  2. SQLite URI `mode=ro` — 커넥션 레벨 read-only
  3. `busy_timeout` / query timeout — 무한 대기 방지
- **자동 시드** — DB 파일이 없으면 `res/sample_db/seed.py`로 ecommerce 샘플(직원/부서/고객/제품/주문)을 즉시 생성한다.

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

```bash
uv run python -m src.cli --verbose                 # INFO 로그 노출
uv run python -m src.cli --suggestions path.yaml   # 다른 추천 파일 사용
```

## Documentation

| 문서 | 내용 |
|------|------|
| [Agents.md](./Agents.md) | Supervisor·Subagent 아키텍처, State 설계, 구현 패턴 |
| [AgentRegistry.md](./AgentRegistry.md) | 레지스트리 API, 등록 메커니즘, 프로젝트 통합 지점 |
| [Logging.md](./Logging.md) | `@log_node` 데코레이터, git diff 스타일 상태 출력 |
| [Evaluation.md](./Evaluation.md) | LLM-as-Judge 평가, 테스트 케이스 작성법, CLI |

설계 spec과 implementation plan은 `docs/superpowers/{specs,plans}/`에 보관한다.

## Dependencies

- `langgraph` — 그래프 기반 에이전트 오케스트레이션
- `langchain-openai` — OpenAI LLM 통합 (`gpt-4o-mini` 기본, `src/llm.py`에서 중앙 관리)
- `langchain-core` — 메시지, 도구 등 핵심 추상화
- `python-dotenv` — 환경 변수 관리
- `pyyaml` — 평가 테스트 케이스 YAML 파싱
- `prompt_toolkit` — 인터랙티브 CLI 입력, fuzzy 자동완성

요구 Python: `>=3.11`
