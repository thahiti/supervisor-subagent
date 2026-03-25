# Supervisor-Subagent

LangGraph 기반의 멀티 에이전트 시스템으로, Supervisor가 사용자 요청을 분석하고 전문 Subagent에게 작업을 위임하는 패턴을 구현한다.

## Architecture

```
[START] → [Supervisor] → (Router) ─┬→ [Agent A] → [Supervisor] (cycle)
                                    ├→ [Agent B] → [Supervisor] (cycle)
                                    └→ [END] (FINISH)
```

Supervisor는 사용자 요청을 JSON 형태로 분석하여 적절한 에이전트를 선택하고, 에이전트 실행 결과를 받아 다음 단계를 결정한다. 모든 작업이 완료되면 최종 응답을 반환한다.

## Quick Start

```bash
cp .env.example .env    # OPENAI_API_KEY 설정
uv run python -m src.main       # 데모 실행
uv run python -m evals.run      # 평가 실행
```

## Project Structure

```
supervisor-subagent/
├── src/
│   ├── main.py                   # 엔트리포인트 + 그래프 빌드
│   ├── state.py                  # 공유 상태 정의
│   ├── agents/                   # 에이전트 모듈
│   │   ├── registry.py           # 에이전트 레지스트리
│   │   └── supervisor/           # Supervisor + Subagent 구현
│   └── logging/                  # 로깅 시스템
├── evals/                        # LLM-as-Judge 평가 시스템
├── res/                          # 평가 테스트 케이스 (YAML)
└── pyproject.toml
```

## Documentation

| 문서 | 내용 |
|------|------|
| [Agents.md](./Agents.md) | Supervisor·Subagent 아키텍처, State 설계, 구현 패턴 |
| [AgentRegistry.md](./AgentRegistry.md) | 레지스트리 API, 등록 메커니즘, 프로젝트 통합 지점 |
| [Logging.md](./Logging.md) | `@log_node` 데코레이터, git diff 스타일 상태 출력 |
| [Evaluation.md](./Evaluation.md) | LLM-as-Judge 평가, 테스트 케이스 작성법, CLI |

## Dependencies

- `langgraph` — 그래프 기반 에이전트 오케스트레이션
- `langchain-openai` — OpenAI LLM 통합
- `langchain-core` — 메시지, 도구 등 핵심 추상화
- `python-dotenv` — 환경 변수 관리
- `pyyaml` — 테스트 케이스 YAML 파싱
