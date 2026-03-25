# Supervisor-Subagent

LangGraph 기반의 멀티 에이전트 시스템으로, Supervisor가 사용자 요청을 분석하고 전문 Subagent에게 작업을 위임하는 패턴을 구현한다.

## Architecture

```
[START] → [Supervisor] → (Router) ─┬→ [Math Agent]      → [Supervisor] (cycle)
                                    ├→ [Translate Agent] → [Supervisor] (cycle)
                                    └→ [END] (FINISH)
```

Supervisor는 사용자 요청을 JSON 형태로 분석하여 적절한 에이전트를 선택하고, 에이전트 실행 결과를 받아 다음 단계를 결정한다. 모든 에이전트가 완료되면 최종 응답을 반환한다.

## Quick Start

```bash
# 환경 설정
cp .env.example .env
# .env 파일에 OPENAI_API_KEY 설정

# 데모 실행
uv run python -m src.main

# 평가 실행
uv run python -m evals.run
```

## Project Structure

```
supervisor-subagent/
├── src/                          # 소스 코드
│   ├── main.py                   # 엔트리포인트 + 그래프 빌드
│   ├── state.py                  # 공유 상태 정의
│   ├── agents/                   # 에이전트 모듈
│   │   ├── registry.py           # 에이전트 레지스트리
│   │   ├── supervisor/           # Supervisor 에이전트
│   │   ├── math_agent/           # 수학 계산 에이전트
│   │   └── translate_agent/      # 번역 에이전트
│   └── logging/                  # 로깅 시스템
│       ├── config.py             # 로거 설정
│       ├── decorator.py          # @log_node 데코레이터
│       └── diff.py               # 상태 diff 포매터
├── evals/                        # 평가 시스템
│   ├── run.py                    # 평가 CLI 엔트리포인트
│   ├── runner.py                 # 테스트 실행 오케스트레이터
│   ├── judge.py                  # LLM-as-Judge
│   ├── prompts.py                # Judge 프롬프트 템플릿
│   └── types.py                  # 평가 타입 정의
├── res/                          # 테스트 리소스
│   └── test_cases.yaml           # 평가 테스트 케이스
└── pyproject.toml
```

## Documentation

| 문서 | 내용 |
|------|------|
| [Agents.md](./Agents.md) | 에이전트 아키텍처, Supervisor, Subagent, 새 에이전트 추가 방법 |
| [AgentRegistry.md](./AgentRegistry.md) | 레지스트리 API 상세, 통합 지점, 등록 메커니즘, 설계 근거 |
| [Logging.md](./Logging.md) | 로깅 시스템 설계, `@log_node` 데코레이터, git diff 스타일 상태 출력 |
| [Evaluation.md](./Evaluation.md) | LLM-as-Judge 평가 시스템, 테스트 케이스 작성법, CLI 사용법 |

## Dependencies

- `langgraph` — 그래프 기반 에이전트 오케스트레이션
- `langchain-openai` — OpenAI LLM 통합
- `langchain-core` — 메시지, 도구 등 핵심 추상화
- `python-dotenv` — 환경 변수 관리
- `pyyaml` — 테스트 케이스 YAML 파싱
