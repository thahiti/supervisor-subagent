# Query Rewriter User-Persona 강화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 리라이터가 짧은 명사구 단답에서 응답자 어투("안내드립니다")로 표류하는 문제를 시스템 프롬프트 강화로 해결한다.

**Architecture:** 단일 파일(`src/query_rewriter/prompt.py`)의 `REWRITER_SYSTEM_PROMPT` 상수 안에 ① 도입부 페르소나, ② §2 명사구 단답 규칙, ③ 출력 형식 절 세 곳을 강화. 코드 구조, 외부 시그니처, 그래프 흐름은 변경하지 않는다. 회귀는 단위 테스트(프롬프트 빌더 어서션)와 LLM 스모크 스크립트로 검증.

**Tech Stack:** Python 3.11+, pytest, langchain-core, langchain-openai (LLM은 스모크에서만 호출)

**Spec:** [docs/superpowers/specs/2026-05-13-rewriter-user-persona-design.md](../specs/2026-05-13-rewriter-user-persona-design.md)

---

## Task 1: 회귀 스모크 스크립트를 트래킹에 추가

**Files:**
- Track: `scripts/repro_rewriter_bug.py` (이미 untracked로 존재)

이 스크립트는 spec의 §회귀 검증에서 게이트로 참조된다. 코드 변경 전에 트래킹에 올려 베이스라인 출력을 기록한다.

- [ ] **Step 1: 스크립트 존재와 실행 가능성 확인**

  Run:
  ```bash
  ls -la scripts/repro_rewriter_bug.py
  ```
  Expected: 파일 존재 (이미 만들어진 상태).

- [ ] **Step 2: 현재 베이스라인 출력 1회 캡처 (변경 전 동작 확인)**

  Run:
  ```bash
  uv run python -m scripts.repro_rewriter_bug 2>&1 | grep -v "INFO\|WARNING\|DEBUG"
  ```
  Expected:
  - `CASE 1 단발 "고객지원"`: "고객 지원에 대한 정보를 요청합니다." 류의 응답-형식 출력 (5/5)
  - `CASE 2 멀티턴`: "고객지원 부서의 평균 급여를 알려주세요." 류 정상 (5/5)
  - `CASE 3 대조군`: "상품 재고를 확인해 주세요." 류 정상 (3/3)

  CASE 1이 모두 정상이면 본 plan 자체가 불필요 — 그 경우 user에게 보고하고 중단.

- [ ] **Step 3: Commit (베이스라인 회귀 게이트 추가)**

  ```bash
  git add scripts/repro_rewriter_bug.py
  git commit -m "$(cat <<'EOF'
  chore(scripts): add rewriter response-tone reproduction smoke

  쿼리 리라이터가 짧은 명사구 단답에서 응답자 어투로 출력하는
  문제를 재현하는 스모크 스크립트를 추가한다. spec
  2026-05-13-rewriter-user-persona-design에서 회귀 게이트로 참조됨.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

  Run:
  ```bash
  git log --oneline -1
  ```
  Expected: 새 commit 메시지가 표시됨.

---

## Task 2: 프롬프트 어서션 테스트 3개를 RED 상태로 추가

**Files:**
- Modify: `tests/test_query_rewriter.py` (현재 line 164 끝, `TestPromptConfirmationRule` 클래스 다음에 새 클래스 추가)

`TestPromptConfirmationRule`(line 164-170)의 패턴을 그대로 따른다. LLM 호출 없이 프롬프트 빌더 출력 텍스트를 어서션. 세 테스트 모두 현재 프롬프트에서는 FAIL해야 한다.

- [ ] **Step 1: 새 테스트 클래스 작성**

  파일 끝(line 170 이후)에 다음 클래스를 추가:

  ```python
  class TestPromptUserPersona:
      def test_prompt_forbids_response_tone(self) -> None:
          prompt = build_rewriter_system_prompt(datetime(2026, 5, 13, 9, 0))
          # 응답자 어투 금지 어휘가 명시되어야 한다.
          assert "안내드립니다" in prompt
          # 금지의 의미가 명시되어야 한다.
          assert "사용하지" in prompt or "사용하면 안" in prompt or "금지" in prompt

      def test_prompt_includes_short_fragment_rule(self) -> None:
          prompt = build_rewriter_system_prompt(datetime(2026, 5, 13, 9, 0))
          # 명사구 단답 처리 규칙이 명시되어야 한다.
          assert "명사구 단답" in prompt or "단답" in prompt
          # 대표 예시가 들어 있어야 한다.
          assert "고객지원" in prompt or "엔지니어링" in prompt

      def test_prompt_includes_user_persona_constraint(self) -> None:
          prompt = build_rewriter_system_prompt(datetime(2026, 5, 13, 9, 0))
          # 사용자 입장 페르소나 제약이 명시되어야 한다.
          assert "사용자가 에이전트에게" in prompt
          # 질문/요청 형태 강제가 명시되어야 한다.
          assert "질문" in prompt and "요청" in prompt
  ```

- [ ] **Step 2: 테스트가 FAIL하는지 확인 (RED)**

  Run:
  ```bash
  uv run pytest tests/test_query_rewriter.py::TestPromptUserPersona -v
  ```
  Expected: 3개 모두 FAIL.
  - `test_prompt_forbids_response_tone`: AssertionError on `"안내드립니다" in prompt`
  - `test_prompt_includes_short_fragment_rule`: AssertionError on 첫 줄 (명사구 단답/단답 키워드 부재)
  - `test_prompt_includes_user_persona_constraint`: AssertionError on `"사용자가 에이전트에게" in prompt`

- [ ] **Step 3: 기존 테스트는 그대로 통과하는지 확인**

  Run:
  ```bash
  uv run pytest tests/test_query_rewriter.py -v
  ```
  Expected: 기존 11개 모두 PASS, 새 3개 FAIL.

- [ ] **Step 4: Commit (RED)**

  ```bash
  git add tests/test_query_rewriter.py
  git commit -m "$(cat <<'EOF'
  test(query-rewriter): add failing user-persona assertion tests

  프롬프트 빌더 출력에 응답자 어투 금지, 명사구 단답 처리 규칙,
  사용자 입장 페르소나 제약이 포함되는지 확인하는 어서션 테스트
  3개를 추가한다. 현재 프롬프트에서는 모두 FAIL — 후속 commit이
  프롬프트를 강화해 GREEN으로 전환한다.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 3: 프롬프트 강화 — 페르소나·단답 규칙·출력 형식

**Files:**
- Modify: `src/query_rewriter/prompt.py:146-210` (`REWRITER_SYSTEM_PROMPT` 상수)

Spec의 §프롬프트 변경 명세에 따라 세 곳을 한 번에 수정한다. 한 commit으로 묶는 이유: 세 변경 모두 "리라이터의 사용자-페르소나 강제"라는 같은 논리적 변경이며, 각각 한 테스트씩을 GREEN으로 전환한다.

- [ ] **Step 1: 도입부 페르소나 강화 (§1)**

  현재 (line 146-147):
  ```
  REWRITER_SYSTEM_PROMPT = """당신은 사용자 쿼리를 명확하게 재작성하는 전처리기입니다.

  ```

  변경 후:
  ```
  REWRITER_SYSTEM_PROMPT = """당신은 사용자 쿼리를 명확하게 재작성하는 **전처리기**입니다.
  출력은 반드시 **사용자가 에이전트에게 보내는 질문 또는 요청** 형태여야 합니다.
  당신은 답변자가 아닙니다. "안내드립니다", "알려드립니다", "정보를 제공합니다", "~입니다" 같은 응답자 어투를 절대 사용하지 마세요. 사용자의 입장에서 묻거나 요청하는 문장으로만 작성하세요.

  ```

- [ ] **Step 2: §2 대화 맥락 보충 절에 명사구 단답 규칙 추가**

  현재 (line 198-203 부근):
  ```
  - "이거", "그거", "저거" → 지칭하는 대상을 명시
  - "더 해줘", "다시 해줘" → 이전에 수행한 작업을 구체적으로 명시
  - "반대로 해줘" → 이전 작업의 반대 방향을 명시
  - "응", "네", "그래", "예", "보여줘" 등 확인 응답 → 직전 에이전트 메시지가 제안한 구체 행동을 명시적으로 풀어서 재작성 (예: "응" → "전체 지점 목록과 라면 제품 목록을 보여줘")
  - 새로운 독립 질문이면 맥락 보충 없이 그대로 유지
  ```

  변경 후 (확인 응답 불릿과 "새로운 독립 질문" 불릿 사이에 새 불릿 추가):
  ```
  - "이거", "그거", "저거" → 지칭하는 대상을 명시
  - "더 해줘", "다시 해줘" → 이전에 수행한 작업을 구체적으로 명시
  - "반대로 해줘" → 이전 작업의 반대 방향을 명시
  - "응", "네", "그래", "예", "보여줘" 등 확인 응답 → 직전 에이전트 메시지가 제안한 구체 행동을 명시적으로 풀어서 재작성 (예: "응" → "전체 지점 목록과 라면 제품 목록을 보여줘")
  - **명사구 단답** (예: "고객지원", "엔지니어링", "3월", "취소", "5번 상품") → chat_history에서 직전 에이전트 메시지가 어떤 변수 또는 선택지를 물었는지 찾아 완전한 질문 형태로 풀어 쓴다.
    - 예: 직전 에이전트가 "무슨 부서가 궁금하세요?"였고 사용자 입력이 "고객지원"이면 → "고객지원 부서의 평균 급여를 알려줘"
    - 직전 맥락이 없거나 단답을 매칭할 질문이 없으면 "<단답>에 대해 알려줘" 형태의 일반 질문으로 변환한다. 응답자 어투로 평서문을 생성하지 않는다.
  - 새로운 독립 질문이면 맥락 보충 없이 그대로 유지
  ```

- [ ] **Step 3: ## 출력 형식 절 강화**

  현재 (line 209-210):
  ```
  ## 출력 형식
  재작성된 쿼리만 출력하세요. 설명이나 부가 텍스트를 포함하지 마세요."""
  ```

  변경 후:
  ```
  ## 출력 형식
  재작성된 쿼리만 출력하세요. 설명, 인사말, "안내드립니다" 같은 응답자 어투는 포함하지 마세요. **반드시 사용자가 에이전트에게 보내는 질문 또는 요청 형태**로만 출력하세요. 평서문/안내문/답변문 형태로 출력하면 안 됩니다."""
  ```

- [ ] **Step 4: 새 어서션 테스트가 GREEN인지 확인**

  Run:
  ```bash
  uv run pytest tests/test_query_rewriter.py::TestPromptUserPersona -v
  ```
  Expected: 3개 모두 PASS.

- [ ] **Step 5: 기존 테스트도 통과하는지 확인 (회귀 없음)**

  Run:
  ```bash
  uv run pytest tests/test_query_rewriter.py -v
  ```
  Expected: 14개 모두 PASS (기존 11 + 새 3).

- [ ] **Step 6: Commit (GREEN)**

  ```bash
  git add src/query_rewriter/prompt.py
  git commit -m "$(cat <<'EOF'
  feat(query-rewriter): enforce user-persona output in system prompt

  도입부 페르소나, §2 명사구 단답 규칙, 출력 형식 절 세 곳을 강화해
  리라이터 출력이 항상 "사용자가 에이전트에게 보내는 질문/요청"
  형태가 되도록 한다. 응답자 어투("안내드립니다", "알려드립니다"
  등)는 명시적으로 금지된다.

  Refs: docs/superpowers/specs/2026-05-13-rewriter-user-persona-design.md

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 4: 전체 단위 테스트 회귀 확인

이 task는 코드 변경 없이 다른 모듈에 의도치 않은 영향이 없는지 검증한다.

- [ ] **Step 1: 프로젝트 전체 pytest 실행**

  Run:
  ```bash
  uv run pytest -v
  ```
  Expected: 모든 테스트 PASS. 특히 다음이 통과해야 한다:
  - `tests/test_query_rewriter.py` (14개)
  - `tests/test_templated_sql_*.py` (templated_sql 관련 테스트군)
  - `tests/test_cli_*.py` (CLI 테스트군)

  실패가 있으면 fix 후 추가 commit. 모두 통과하면 commit 없이 다음 task.

---

## Task 5: LLM 스모크로 실제 행동 회귀 검증

**Files:**
- Run: `scripts/repro_rewriter_bug.py`

이 task는 단위 테스트로 잡히지 않는 LLM 행동을 측정한다. 추가 commit 없음.

- [ ] **Step 1: 스모크 스크립트 재실행**

  Run:
  ```bash
  uv run python -m scripts.repro_rewriter_bug 2>&1 | grep -v "INFO\|WARNING\|DEBUG"
  ```

  Expected:
  - **CASE 1** (단발 "고객지원", chat_history 없음): 5/5 모두 사용자가 에이전트에게 보내는 질문/요청 형태. "안내드립니다", "정보를 요청합니다", "~입니다" 같은 응답자 어투 출현 0/5.
    - 예시 허용 출력: "고객지원에 대해 알려줘", "고객지원에 대해 알려주세요"
  - **CASE 2** (멀티턴 + "고객지원"): 5/5 모두 "고객지원 부서의 평균 급여를 알려주세요." 류 유지.
  - **CASE 3** (대조군 "상품 재고 알려줘"): 3/3 모두 "상품 재고를 확인해 주세요." 류 유지.

- [ ] **Step 2: 결과 보고**

  - CASE 1이 5/5 응답자 어투 없음 → 본 plan의 목표 달성. user에게 final report.
  - 응답자 어투가 1회 이상 출현 → 해당 출력을 user에게 공유하고 추가 프롬프트 강화 또는 별도 후처리 보강 옵션을 논의.

---

## 자체 검토 체크리스트 (구현자가 마지막에 확인)

- [ ] Spec의 §프롬프트 변경 명세 3개 항목이 모두 반영됐다.
- [ ] Spec의 §테스트 추가 3개 테스트가 모두 GREEN 상태다.
- [ ] Spec의 §회귀 검증 기대값이 CASE 1/2/3 모두 충족됐다.
- [ ] 외부 시그니처 `build_rewriter_system_prompt(now, dictionary)`가 변경되지 않았다.
- [ ] `src/query_rewriter/rewriter.py` 및 그래프 코드가 변경되지 않았다.
- [ ] 4개 commit이 atomic하게 분리됐다 (베이스라인 스크립트, 실패 테스트, 프롬프트 변경, 회귀 확인은 commit 없음).
