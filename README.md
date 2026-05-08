# Supervisor-Subagent

LangGraph 기반의 멀티 에이전트 시스템. Router가 사용자 요청을 분석하여 가장 적합한 전문 Subagent에게 한 번 위임하고, 결과를 페르소나가 적용된 최종 답변으로 정리한다.

## Architecture

```
[START] → [query_rewriter] → [router] ─┬→ [math_agent]      ─┐
                                       ├→ [translate_agent]  ├→ [response_generator] → [END]
                                       ├→ [sql_agent]        ┘
                                       └→ [response_generator] (FINISH)
```

- **query_rewriter** — 사용자 쿼리에 시간 표현 해석(예: "지난주" → `2026-04-27~2026-05-03`), 대화 맥락 보충, 용어 사전 치환을 적용해 명확한 형태로 재작성한다.
- **router** — 단발성 라우팅. 사용자 요청을 분석해 가장 적합한 워커 하나만 선택하고, 적합한 워커가 없으면 `FINISH`로 곧바로 답변 생성 단계로 넘긴다.
- **subagents** — `math`, `translate`, `sql` 중 선택된 하나만 실행된다.
- **response_generator** — 서브에이전트 결과를 페르소나에 맞춰 최종 답변으로 정리하고, 멀티턴 컨텍스트를 위해 `chat_history`에 한 턴(리라이팅된 사용자 질의 + 최종 출력)을 누적한다.

## Quick Start

```bash
cp .env.example .env              # OPENAI_API_KEY 설정
uv sync                           # 의존성 설치
uv run python -m src.main         # 데모 실행 (시나리오 A~E)
uv run python -m evals.run        # LLM-as-Judge 평가 실행
```

데모 시나리오:
- **A** 수학 계산 (math)
- **B** 번역 (translate)
- **C** 복합 요청 — router가 주된 의도 하나만 선택
- **D** SQL 조회 (sql) — `res/sample_db/ecommerce.db` 자동 시드
- **E** 멀티턴 — 1차 응답을 `chat_history`로 인계해 "이거 다시 영어로" 같은 지시어 해석 검증

## Project Structure

```
supervisor-subagent/
├── src/
│   ├── main.py                   # 엔트리포인트 + 그래프 빌드
│   ├── state.py                  # 공유 State / WorkerState 정의
│   ├── registry.py               # 에이전트 레지스트리 (글로벌 인스턴스)
│   ├── llm.py                    # ChatOpenAI 팩토리 (모델 중앙화)
│   ├── query_rewriter/           # 쿼리 전처리 (시간/맥락/용어)
│   ├── router/                   # 단발성 라우팅 노드
│   ├── response_generator/       # 페르소나 기반 최종 답변
│   ├── supervisor/               # (legacy) 반복 위임형 Supervisor
│   ├── math_agent/               # 수학 ReAct 에이전트 (add/multiply/divide)
│   ├── translate_agent/          # 한↔영 번역 (LLM 직접 호출)
│   ├── sql_agent/                # Text-to-SQL ReAct 에이전트
│   │   ├── frontend/             #   도메인 인식 레이어 (스키마 + few-shot)
│   │   └── backend/              #   도메인 무지 SQLite 실행기 (read-only)
│   └── logging/                  # @log_node 데코레이터 + git diff 스타일 출력
├── evals/                        # LLM-as-Judge 평가 시스템
├── res/
│   ├── test_cases.yaml           # 평가 테스트 케이스
│   └── sample_db/                # ecommerce 샘플 DB (스키마 + 시드)
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

새 에이전트 추가는 wrapper 함수에 `@registry.agent("name")` 데코레이터 한 줄과 docstring만으로 끝난다 — 그래프 빌드 코드, 라우터 프롬프트, 라우터 분기 모두 자동으로 반영된다. 자세한 메커니즘은 [AgentRegistry.md](./AgentRegistry.md) 참조.

## SQL Agent: Frontend / Backend 분리

`sql_agent`는 도메인 인식 책임(`frontend/`)과 안전한 실행 책임(`backend/`)을 분리한다.

- **Frontend** — 시스템 프롬프트에 스키마 + few-shot을 주입하고, Backend를 감싼 LangChain `@tool`을 LLM에 바인딩한다.
- **Backend (`SqlExecutor`)** — 도메인을 모르는 SQLite read-only 실행기. **3중 안전망**으로 보호된다:
  1. `safety.validate_select_only` — SELECT 외 키워드 거부
  2. SQLite URI `mode=ro` — 커넥션 레벨 read-only
  3. `busy_timeout` / query timeout — 무한 대기 방지
- **자동 시드** — DB 파일이 없으면 `res/sample_db/seed.py`로 ecommerce 샘플(직원/부서/고객/제품/주문)을 즉시 생성한다.

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

요구 Python: `>=3.11`
