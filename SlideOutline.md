# 멀티 에이전트 시스템의 공통 구조 설계

> Slide Outline — 외부 기술 발표용 (엔지니어 대상)
> 4개 파트: **Supervisor-Subagent 아키텍처** · **Registry** · **Evaluation** · **Logging**

---

## Part 0. 도입

---

### Slide 0-1. 표지

**멀티 에이전트 시스템의 공통 구조 설계**
Supervisor-Subagent Architecture · Registry · Evaluation · Logging

---

### Slide 0-2. 발표 목표

본 발표는 LangGraph 기반 멀티 에이전트 시스템을 운영 가능한 수준으로 구축하기 위해
해결해야 하는 네 가지 구조적 문제를 다룬다.

1. 에이전트 간 **컨텍스트 격리**를 어떻게 보장하는가
2. 에이전트 추가 시 **수정 지점을 최소화**하는 등록 구조는 무엇인가
3. LLM 출력의 **품질을 자동으로 측정**하는 방법은 무엇인가
4. 그래프 순환 구조에서 **실행 상태를 추적**하는 방법은 무엇인가

---

### Slide 0-3. 아젠다

```
┌────────────────────────────────────────────────────┐
│                                                    │
│  Part 1.  Supervisor-Subagent 아키텍처             │
│           컨텍스트 격리와 상태 분리                  │
│                                                    │
│  Part 2.  Agent Registry                           │
│           단일 등록 지점을 통한 에이전트 관리         │
│                                                    │
│  Part 3.  Evaluation (LLM-as-Judge)                │
│           자동화된 품질 평가 파이프라인               │
│                                                    │
│  Part 4.  Logging                                  │
│           그래프 실행 상태의 구조적 추적              │
│                                                    │
└────────────────────────────────────────────────────┘
```

---

## Part 1. Supervisor-Subagent 아키텍처

---

### Slide 1-1. 시스템 구조 개요

본 시스템은 두 가지 역할로 구성된다.

- **Supervisor**: 사용자 요청을 분석하고 적절한 에이전트를 선택하는 오케스트레이터
- **Subagent**: 특정 도메인 작업을 수행하는 전문 에이전트

```
[START] → [Supervisor] → (Router) ──┬── [Agent A] → [Supervisor]
                                    ├── [Agent B] → [Supervisor]
                                    └── [END] (FINISH)
```

LangGraph의 `StateGraph`는 순환(cycle)을 허용하므로 Supervisor → Agent → Supervisor 루프를 네이티브로 표현할 수 있다. 이 패턴은 LangGraph 공식 문서에서 [Supervisor Pattern](https://docs.langchain.com/oss/python/langgraph/workflows-agents)으로 정의하고 있다.

---

### Slide 1-2. 설계 동기: Context Pollution 문제

단일 에이전트 구조에서는 모든 중간 메시지가 하나의 컨텍스트에 누적된다.

```
┌───────────────────────────────────────────────────────┐
│  단일 에이전트 — 하나의 컨텍스트에 모든 이력이 누적    │
│                                                       │
│  [User 질문]                                          │
│  [Math tool_call: add(3,7)]                           │
│  [ToolMessage: 10]                                    │
│  [Math tool_call: multiply(10,5)]                     │
│  [ToolMessage: 50]            ← 도구 중간 결과         │
│  [Math 최종 답변]                                      │
│  [Translate system prompt]    ← 무관한 도메인           │
│  [Translate 결과]                                      │
│                                                       │
│  문제:                                                │
│  - 번역 시 수학 도구 호출 이력이 컨텍스트에 잔존       │
│  - Supervisor 판단 시 모든 중간 메시지를 처리해야 함    │
└───────────────────────────────────────────────────────┘
```

Liu et al.(2024)의 연구에 따르면, LLM은 컨텍스트 중간에 위치한 정보에 대한 활용 능력이 30% 이상 저하된다.

> 출처: [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172) (TACL 2024)

---

### Slide 1-3. 해법: 서브그래프를 통한 컨텍스트 격리

Supervisor-Subagent 구조는 각 에이전트에게 독립된 컨텍스트 윈도우를 제공한다.

```
┌───────────────────────────────────────────────────────┐
│  Supervisor-Subagent — 격리된 컨텍스트 윈도우          │
│                                                       │
│  ┌─ Supervisor Context ──────────────────────┐        │
│  │  [User 질문]                               │        │
│  │  [Math 최종 결과 요약]   ← 최종 결과만      │        │
│  │  [Translate 최종 결과]   ← 최종 결과만      │        │
│  └───────────────────────────────────────────┘        │
│                                                       │
│  ┌─ Math Subagent Context (격리) ────────────┐        │
│  │  [User 질문]                               │        │
│  │  [tool_call: add(3,7)]                     │        │
│  │  [ToolMessage: 10]                         │        │
│  │  [tool_call: multiply(10,5)]               │        │
│  │  [ToolMessage: 50]                         │        │
│  │  → Supervisor에게는 최종 결과만 반환        │        │
│  └───────────────────────────────────────────┘        │
│                                                       │
│  ┌─ Translate Subagent Context (격리) ───────┐        │
│  │  [User 질문]                               │        │
│  │  [번역 결과]                               │        │
│  │  → 수학 도구 이력이 존재하지 않음           │        │
│  └───────────────────────────────────────────┘        │
└───────────────────────────────────────────────────────┘
```

> 출처: [LangGraph — How to use subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)

---

### Slide 1-4. 구현: State와 WorkerState 분리

```python
# 메인 그래프 State — Supervisor가 사용
class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    next_agent: str
    plan: str
    completed_agents: list[str]

# 서브그래프 State — 각 Agent가 내부적으로 사용
class WorkerState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
```

```
격리 메커니즘:

  State.messages                  WorkerState.messages
  ┌──────────────┐               ┌──────────────────────┐
  │ User 질문    │──── 전달 ────▶│ User 질문            │
  │              │               │ [tool_call: add]     │
  │              │               │ [ToolMessage: 10]    │
  │              │               │ [tool_call: mul]     │
  │              │               │ [ToolMessage: 50]    │
  │ [수학 결과]  │◀── 최종만 ────│ [최종 답변]          │
  └──────────────┘               └──────────────────────┘

  Supervisor는                   서브그래프 내부의
  중간 tool_call을               tool_call, ToolMessage는
  전혀 볼 수 없음                메인 그래프에 전달되지 않음
```

`WorkerState.messages`와 `State.messages`가 동일한 키를 공유하므로 LangGraph가 자동으로 상태를 전달한다. `next_agent`, `plan`, `completed_agents`는 서브그래프에 전달되지 않는다.

---

### Slide 1-5. 컨텍스트 격리의 효과

```
┌────────────────────────┬──────────────────────────────┐
│  효과                   │  설명                        │
├────────────────────────┼──────────────────────────────┤
│  추론 정확도 향상       │  무관한 정보 제거로           │
│                        │  LLM이 핵심 작업에 집중       │
├────────────────────────┼──────────────────────────────┤
│  토큰 효율성            │  각 에이전트가 필요한         │
│                        │  컨텍스트만 소비              │
├────────────────────────┼──────────────────────────────┤
│  Context Rot 방지       │  짧은 컨텍스트 여러 개가      │
│                        │  긴 컨텍스트 하나보다 효과적   │
├────────────────────────┼──────────────────────────────┤
│  모듈성                 │  각 에이전트를 독립적으로     │
│                        │  테스트 및 교체 가능           │
├────────────────────────┼──────────────────────────────┤
│  확장성                 │  에이전트 추가 시 기존        │
│                        │  에이전트의 컨텍스트에 영향 없음│
└────────────────────────┴──────────────────────────────┘
```

> 출처: [Redis — Context Rot Explained](https://redis.io/blog/context-rot/),
> [Anthropic — Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

---

### Slide 1-6. 실증: Anthropic 멀티 에이전트 연구 시스템

Anthropic은 Lead Agent + Subagent 구조의 멀티 에이전트 연구 시스템을 발표했다.

```
┌───────────────────────────────────────────────────────┐
│  Anthropic Multi-Agent Research System                │
│                                                       │
│  Lead Agent (Claude Opus 4)                           │
│    ├── Subagent 1 (Claude Sonnet 4) → 검색 태스크 A   │
│    ├── Subagent 2 (Claude Sonnet 4) → 검색 태스크 B   │
│    └── Subagent 3 (Claude Sonnet 4) → 검색 태스크 C   │
│                                                       │
│  설계 원칙:                                            │
│  - 각 서브에이전트 = 독립 컨텍스트 윈도우               │
│  - 서브에이전트는 stateless (매 호출 시 깨끗한 상태)    │
│  - 중간 과정이 아닌 압축된 결과만 Lead에게 반환         │
│                                                       │
│  성과:                                                 │
│  - 단일 에이전트 대비 90.2% 성능 향상                  │
│  - 토큰 사용량이 성능 분산의 80%를 설명                 │
└───────────────────────────────────────────────────────┘
```

> 출처: [Anthropic — How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)

---

### Slide 1-7. 안전 장치

Supervisor에는 두 가지 안전 장치가 구현되어 있다.

```
┌────────────────────────┬──────────────────────────────┐
│  장치                   │  동작                        │
├────────────────────────┼──────────────────────────────┤
│  JSON 파싱 실패 처리    │  파싱 실패 시 next_agent를   │
│                        │  "FINISH"로 설정하여 안전 종료│
├────────────────────────┼──────────────────────────────┤
│  MAX_ITERATIONS = 5     │  completed_agents 수가       │
│                        │  5 이상이면 강제 종료하여     │
│                        │  무한 루프 방지               │
└────────────────────────┴──────────────────────────────┘
```

```python
# JSON 파싱 실패 시 안전 종료
except (json.JSONDecodeError, ValueError):
    return {"next_agent": "FINISH", "plan": plan}

# 최대 반복 횟수 제한
if len(completed) >= MAX_ITERATIONS:
    return END
```

---

## Part 2. Agent Registry

---

### Slide 2-1. 문제 정의

에이전트를 하나 추가할 때 일반적으로 세 곳을 수정해야 한다.

```
┌───────────────────────────────────────────────────────┐
│  에이전트 1개 추가 시 수정이 필요한 지점:              │
│                                                       │
│  ① 그래프 빌드 코드   →  노드 + 엣지 추가             │
│  ② Supervisor 프롬프트 →  에이전트 설명 추가           │
│  ③ 라우터 함수        →  if-elif 분기 추가             │
│                                                       │
│  에이전트 N개 → 관리 비용 3N (선형 증가)               │
│  하나라도 누락 시 → 라우팅 실패 또는 프롬프트 누락     │
└───────────────────────────────────────────────────────┘
```

이 분산된 수정 지점은 에이전트 수가 늘어날수록 누락 위험이 높아진다.

---

### Slide 2-2. 해법: 단일 등록 지점

데코레이터 한 줄로 세 가지 관심사를 동시에 해결한다.

```python
@registry.agent("math")
def math_wrapper(state: State) -> dict:
    """수학 계산을 수행합니다.
    덧셈, 곱셈, 나눗셈 등의 계산이 필요할 때 사용합니다."""
    ...
```

```
@registry.agent("math")
        │
        ├──→  그래프 노드 자동 등록
        ├──→  Supervisor 프롬프트에 설명 자동 삽입
        └──→  라우터 분기 자동 생성
```

---

### Slide 2-3. 내부 구조

```
┌── AgentEntry ─────────────────────────────┐
│  name        : "math"        (라우팅 키)   │
│  node_name   : "math_agent"  (그래프 노드) │
│  wrapper     : math_wrapper  (실행 함수)   │
│  description : "수학 계산…"  (프롬프트용)   │
└───────────────────────────────────────────┘

┌── AgentRegistry ──────────────────────────┐
│  _entries : [AgentEntry, ...]  순서 보존    │
│  _by_name : {"math": entry}   O(1) 조회    │
│                                            │
│  .build_workers_prompt()  → Supervisor 용   │
│  .get(name)               → 라우터 용       │
│  .entries                 → 그래프 빌드 용   │
└───────────────────────────────────────────┘
```

리스트(`_entries`)는 등록 순서를 보존하여 그래프 빌드와 프롬프트 생성 시 순회에 사용하고, 딕셔너리(`_by_name`)는 라우터에서 매 라우팅마다 O(1) 조회를 보장한다.

---

### Slide 2-4. 소비자 3곳, 생산자 1곳

```
                  ┌──────────────┐
                  │   Registry   │
                  └──────┬───────┘
           ┌─────────────┼──────────────┐
           ▼             ▼              ▼
  ┌────────────┐  ┌────────────┐  ┌──────────┐
  │ 그래프 빌드 │  │ Supervisor │  │   Evals  │
  │ (main.py)  │  │ (프롬프트  │  │ (wrapper │
  │ 노드 순회  │  │  + 라우터) │  │  직접 호출)│
  └────────────┘  └────────────┘  └──────────┘
```

```python
# 1. 그래프 빌드 — 레지스트리 순회로 노드/엣지 자동 생성
for entry in registry.entries:
    graph.add_node(entry.node_name, entry.wrapper)

# 2. Supervisor — 프롬프트 동적 생성
workers = registry.build_workers_prompt()

# 3. 라우터 — if-elif 체인 제거
entry = registry.get(next_agent)
return entry.node_name if entry else END
```

---

### Slide 2-5. 등록 트리거 메커니즘

`@registry.agent` 데코레이터는 모듈 import 시점에 실행된다.

```
Python 인터프리터 시작
    │
    ▼
import src.agents          ←── __init__.py
    │
    ├── from .math_agent import math_wrapper
    │       └── @registry.agent("math") 실행 → 등록 완료
    │
    └── from .translate_agent import translate_wrapper
            └── @registry.agent("translate") 실행 → 등록 완료
    │
    ▼
registry.entries = [math, translate]   ← 사용 준비 완료
```

글로벌 인스턴스(`registry = AgentRegistry()`)는 Python 모듈 시스템의 특성상 프로세스 내에서 싱글턴으로 동작한다.

---

### Slide 2-6. 에이전트 추가 절차

```
수정이 필요한 파일:
  1. src/agents/new_agent/agent.py 생성
     → @registry.agent("name") + docstring 작성
  2. src/agents/__init__.py에 import 한 줄 추가

수정이 불필요한 파일:
  - main.py (그래프 빌드)
  - supervisor.py (프롬프트, 라우터)
  - evals/ (평가 시스템)
```

Open-Closed Principle: 확장에는 열려 있고, 기존 코드의 수정에는 닫혀 있다.

---

### Slide 2-7. 대안 비교

| 접근법 | 장점 | 단점 | 적합 사례 |
|--------|------|------|----------|
| **데코레이터 기반** (본 프로젝트) | 간결한 등록, 정의 시점 자동화 | import 순서 의존 | 단일 패키지 내 에이전트 |
| **entry_points** (setuptools) | 서드파티 패키지 확장 가능 | 패키징 구성 필요 | 프레임워크, 에코시스템 |
| **명시적 등록** | 완전한 제어, 조건부 등록 | 코드 장황 | 런타임 동적 등록 |

본 프로젝트는 에이전트가 모두 단일 패키지 내에 존재하므로 데코레이터 기반이 적합하다. 서드파티 플러그인 확장이 필요해지면 [entry_points](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)로 전환할 수 있다.

---

## Part 3. Evaluation (LLM-as-Judge)

---

### Slide 3-1. 문제 정의

LLM 출력의 품질 평가에는 두 가지 차원이 있다.

```
┌───────────────────────────────────────────────────────┐
│  입력: "3과 7을 더해주세요"                             │
│                                                       │
│  출력 A: "3+7=10입니다"         → 정확하지만 간결      │
│  출력 B: "3+7=10. 풀이: …"     → 정확하고 과정 포함    │
│  출력 C: "결과는 11입니다"      → 부정확                │
│                                                       │
│  Rule-based:  A=✓  B=✓  C=✗    정답 일치만 검증 가능   │
│  LLM Judge:   A=7  B=9  C=2    풀이 과정의 품질도 평가 │
└───────────────────────────────────────────────────────┘
```

정답 검증은 규칙 기반으로 가능하지만, 풀이 과정의 논리성(`step_reasoning`)이나 번역의 자연스러움(`naturalness`)은 LLM 판단이 필요하다.

---

### Slide 3-2. 파이프라인 구조

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  YAML    │     │  Agent   │     │  Judge   │     │  Report  │
│ 테스트   │────▶│ Wrapper  │────▶│  LLM     │────▶│ PASS /   │
│ 케이스   │     │ 직접 호출 │     │ (gpt-4o) │     │ FAIL     │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
     ↑                                                   │
     │              pass_threshold: 7.0                   │
     └────────────── Exit code: 0 or 1 ──────────────────┘
                     (CI 품질 게이트)
```

실행 흐름: YAML 테스트 케이스 로드 → 에이전트 실행 → Judge LLM 채점 → PASS/FAIL 판정 → CI 연동

---

### Slide 3-3. 핵심 설계: wrapper 직접 호출

전체 그래프(Supervisor → Agent)를 실행하지 않고 wrapper를 직접 호출한다.

```
전체 파이프라인 실행                 격리된 평가
User → Supervisor → Agent →         User → Agent (직접 호출)
       Supervisor → END

Supervisor 라우팅 오류 시            Agent만 독립적으로 테스트
→ Agent 평가 결과가 오염됨           → 정확한 품질 측정
```

```python
entry = registry.get("math")
result = entry.wrapper(state)    # Supervisor 우회, Agent만 실행
```

Registry가 wrapper 참조를 보관하므로 평가 시스템이 Supervisor를 우회하여 에이전트를 직접 호출할 수 있다.

---

### Slide 3-4. 테스트 케이스 스키마

```yaml
eval_config:
  judge_model: "gpt-4o"
  judge_temperature: 0.0
  pass_threshold: 7.0
  agent_criteria:
    math: [correctness, step_reasoning]
    translate: [correctness, fluency, naturalness]

test_cases:
  - id: "math_chained"
    target_agent: "math"
    input: "3과 7을 더하고 5를 곱해주세요"
    reference_answer: "3+7=10, 10×5=50"
```

평가 기준 결정 우선순위:

```
① 케이스 레벨 eval_criteria       (override)
     ↓ 미지정 시
② agent_criteria[target_agent]    (에이전트 유형별 기본값)
     ↓ 미지정 시
③ ["correctness"]                 (fallback)
```

---

### Slide 3-5. Judge 응답 구조

Judge LLM이 반환하는 JSON:

```json
{
  "scores": {
    "correctness":    {"score": 9, "reason": "핵심 수치 일치"},
    "step_reasoning": {"score": 8, "reason": "중간 과정이 명확함"}
  },
  "overall_score": 8.5,
  "summary": "정확하고 논리적인 풀이"
}
```

판정 로직:

```
overall_score >= 7.0  →  PASS
overall_score <  7.0  →  FAIL
JSON 파싱 실패        →  모든 기준 0점 처리 (실패를 숨기지 않음)
```

---

### Slide 3-6. CLI 및 CI 연동

```bash
uv run python -m evals.run                          # 전체 실행
uv run python -m evals.run --filter math             # ID 필터
uv run python -m evals.run --agent translate          # 에이전트 필터
```

출력 예시:

```
============================================================
  EVALUATION RESULTS (judge: gpt-4o)
============================================================

[1/6] math_simple_add .................. PASS (9.0, 2.3s)
  ✓ correctness     : 9/10
  ✓ step_reasoning  : 9/10

[2/6] translate_formal ................. FAIL (6.5, 1.8s)
  ✓ correctness     : 8/10
  ✗ formality       : 5/10

------------------------------------------------------------
  SUMMARY: 5/6 passed | threshold: 7.0 | time: 12.3s
------------------------------------------------------------
  Exit code: 1
```

Exit code `0`(전체 통과) / `1`(하나 이상 실패)로 CI/CD 품질 게이트에 직접 연동 가능하다.

---

### Slide 3-7. 대안 비교 및 알려진 한계

| 방식 | 강점 | 약점 | 적합 사례 |
|------|------|------|----------|
| **LLM-as-Judge** (본 프로젝트) | 유연한 기준, 자연어 평가 | 위치 편향, API 비용 | 추론 과정, 번역 품질 |
| Rule-based | 결정적, 무비용 | 품질 판단 불가 | 정답 매칭, 형식 검증 |
| Human-in-the-Loop | 가장 정확한 판단 | 느림, 확장 불가 | 캘리브레이션 |

알려진 한계와 완화 방안:

```
┌────────────────────────┬──────────────────────────────┐
│  한계                   │  완화 방안                    │
├────────────────────────┼──────────────────────────────┤
│  위치 편향              │  단일 출력 채점 방식 사용     │
│  (position bias)       │  (비교가 아닌 절대 평가)      │
├────────────────────────┼──────────────────────────────┤
│  점수 경계 불안정       │  7.0 임계값으로 이진 판정     │
│                        │  (PASS/FAIL)                  │
├────────────────────────┼──────────────────────────────┤
│  자기 강화 편향         │  에이전트(gpt-4o-mini)와      │
│                        │  Judge(gpt-4o) 모델 분리      │
└────────────────────────┴──────────────────────────────┘
```

> 출처: [Judging the Judges: Position Bias Study](https://arxiv.org/abs/2406.07791),
> [A Survey on LLM-as-a-Judge](https://arxiv.org/abs/2411.15594)

---

## Part 4. Logging

---

### Slide 4-1. 문제 정의

멀티 에이전트 시스템에서 디버깅 시 세 가지 질문에 동시에 답해야 한다.

```
실행 흐름:
Supervisor → Math → Supervisor → Translate → Supervisor → END

질문:
  1. 현재 어떤 노드가 실행 중인가
  2. State가 어떻게 변경되었는가
  3. LLM이 무엇을 응답했는가
```

일반적인 로깅으로는 이 세 질문에 동시에 답하기 어렵다.

```
[INFO] Processing...           ← 어떤 노드인지 불명확
[INFO] Done.                   ← 무엇이 변경되었는지 불명확
[INFO] LLM response: {...}     ← 구조화되지 않은 긴 텍스트
```

---

### Slide 4-2. 설계 원칙

```
┌───────────────────────────────────────────────────┐
│                                                   │
│  ① 현재 위치 식별                                 │
│     ========== [SUPERVISOR] ==========            │
│     구분선으로 현재 노드를 명확히 표시              │
│                                                   │
│  ② 상태 변화 시각화                               │
│     -  next_agent: (str) ''                       │
│     +  next_agent: (str) 'math'                   │
│     git diff 형식으로 변경 전후를 대조              │
│                                                   │
│  ③ LLM 응답 보존                                  │
│     JSON → pretty-print                           │
│     일반 텍스트 → 원문 그대로                      │
│     요약이나 truncation 없이 전체 기록              │
│                                                   │
└───────────────────────────────────────────────────┘
```

---

### Slide 4-3. @log_node 데코레이터

모든 노드에 동일한 로깅 패턴을 노드 로직 수정 없이 적용한다.

```python
@log_node("supervisor")
def supervisor_node(state: State) -> dict:
    ...  # 노드 로직 변경 없음
```

```
┌──────────────────────────────────────────────────┐
│  ① 진입   →  ========== [SUPERVISOR] ==========  │
│                                                  │
│  ② 실행   →  원래 함수 실행 + 시간 측정           │
│                                                  │
│  ③-A 성공 →  ---------- Completed (1.2s) ------  │
│              State diff 출력                      │
│                                                  │
│  ③-B 실패 →  !!!!!!!!!! Failed (0.3s) !!!!!!!!!  │
│              Traceback 전체 출력 (exc_info=True)  │
└──────────────────────────────────────────────────┘
```

---

### Slide 4-4. git diff 스타일 State 시각화

실제 출력 예시:

```
------------------------------------------------------------
  [SUPERVISOR] Completed (1.234s)
------------------------------------------------------------
  State:
  messages: (list[BaseMessage]) 2 messages
    [0] type: HumanMessage, content: 3과 7을 더해주세요
+   [1] type: AIMessage, content:
+       {
+         "next": "math",
+         "reason": "수학 계산 필요"
+       }
-   next_agent: (str) ''
+   next_agent: (str) 'math'
  completed_agents: (list) []
------------------------------------------------------------
```

```
┌──────────┬──────────────────────────┐
│  Prefix  │  의미                    │
├──────────┼──────────────────────────┤
│  (공백)   │  변경 없음               │
│  +       │  추가된 값               │
│  -       │  제거된 값               │
│  -/+     │  값이 변경됨 (이전/이후)  │
└──────────┴──────────────────────────┘
```

모든 필드에 런타임 타입이 표시된다: `(str)`, `(list[BaseMessage])`, `(list[str])`.

---

### Slide 4-5. 로거 계층 구조

```
supervisor_subagent              ← 루트
├── main                         ← 엔트리포인트
├── supervisor                   ← Supervisor 내부 동작
├── router.*                     ← 라우팅 결정
│   ├── router.supervisor
│   └── router.math
├── agent.*                      ← 에이전트 내부 동작
│   ├── agent.math
│   └── agent.translate
└── node.*                       ← @log_node 데코레이터 출력
    ├── node.supervisor
    ├── node.math_agent_internal
    └── node.math_tool_executor
```

계층 구조를 활용한 선택적 필터링:

```python
# 라우팅 결정만 확인
logging.getLogger("supervisor_subagent.router").setLevel(DEBUG)

# 나머지는 WARNING 이상만
logging.getLogger("supervisor_subagent").setLevel(WARNING)
```

---

### Slide 4-6. 콘텐츠 포맷팅

```
┌────────────────┬──────────────────────────────┐
│  콘텐츠 타입    │  처리 방식                    │
├────────────────┼──────────────────────────────┤
│  JSON          │  파싱 후 들여쓰기 출력        │
│  일반 텍스트    │  원문 그대로 출력             │
│  tool_calls    │  raw JSON (name, args, id)   │
│  빈 콘텐츠     │  생략                         │
└────────────────┴──────────────────────────────┘
```

로깅 레벨 설계:

```
┌──────────┬────────────────────────────────────────┐
│  레벨     │  용도                                  │
├──────────┼────────────────────────────────────────┤
│  INFO    │  정상 실행 흐름                          │
│          │  (LLM 호출, 노드 진입/완료, 라우팅 결정)  │
├──────────┼────────────────────────────────────────┤
│  WARNING │  복구 가능한 문제                        │
│          │  (JSON 파싱 실패 → FINISH, MAX_ITERATIONS)│
├──────────┼────────────────────────────────────────┤
│  ERROR   │  실패 (exc_info=True 포함)               │
│          │  (LLM API 오류, 도구 실행 예외)           │
└──────────┴────────────────────────────────────────┘
```

---

### Slide 4-7. 대안 비교

| 방식 | 강점 | 약점 | 적합 사례 |
|------|------|------|----------|
| **git diff 스타일** (본 프로젝트) | 터미널 가독성, 학습 비용 없음 | 로그 분석 도구 비호환 | 개발 단계 디버깅 |
| JSON 구조화 로깅 | Datadog/ELK 통합 용이 | 터미널 가독성 낮음 | 프로덕션 환경 |
| [LangSmith](https://www.langchain.com/langsmith/observability) 트레이싱 | UI 시각화, 토큰 추적 | 외부 서비스 의존 | 프로덕션 모니터링 |

프로덕션 환경에서는 git diff 스타일과 구조화 로깅 또는 LangSmith를 병행하는 것이 권장된다.

---

## Part 5. 마무리

---

### Slide 5-1. 모듈 간 연결 구조

```
                  ┌──────────────┐
                  │   Registry   │
                  └──────┬───────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
  ┌────────────┐  ┌────────────┐  ┌──────────┐
  │  Logging   │  │ Supervisor │  │Evaluation│
  │            │  │            │  │          │
  │ @log_node  │  │  프롬프트  │  │ wrapper  │
  │ 데코레이터 │  │  + 라우터  │  │ 직접 호출 │
  └────────────┘  └────────────┘  └──────────┘
```

- **Registry**가 에이전트 메타데이터의 단일 진실 공급원(Single Source of Truth)
- **Logging**이 Registry에 등록된 노드를 데코레이터로 관찰
- **Evaluation**이 Registry에서 wrapper를 조회하여 직접 테스트
- 세 모듈 모두 에이전트 추가 시 자동으로 확장되며 기존 코드 수정이 불필요

---

### Slide 5-2. 요약

```
┌────────────────────────────────────────────────────────┐
│                                                        │
│  Supervisor-Subagent                                   │
│  → 서브그래프를 통한 컨텍스트 격리                       │
│    추론 정확도, 토큰 효율성, 모듈성 확보                 │
│                                                        │
│  Registry                                              │
│  → 데코레이터 기반 단일 등록 지점                        │
│    에이전트 추가 시 수정 지점 최소화 (OCP)               │
│                                                        │
│  Evaluation                                            │
│  → LLM-as-Judge 자동 품질 평가                          │
│    CI/CD 품질 게이트로 활용 가능                         │
│                                                        │
│  Logging                                               │
│  → git diff 스타일 상태 추적                             │
│    그래프 순환 구조에서의 디버깅 지원                     │
│                                                        │
└────────────────────────────────────────────────────────┘
```

---

### Slide 5-3. Q&A
