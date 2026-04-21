# Tokenizer 모듈 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자연어에서 코드형 토큰(대문자+숫자+특수문자 3글자 이상)을 추출하고, 외부 딕셔너리 클라이언트로 정의를 조회하여 원문을 치환하는 tokenizer 모듈을 구현한다.

**Architecture:** tokenizer는 3단계 파이프라인으로 동작한다: (1) 정규식으로 토큰 추출, (2) 딕셔너리 클라이언트로 정의 조회, (3) 조회 성공한 토큰만 원문에서 치환. 기존 query_rewriter의 정적 TERM_DICTIONARY를 대체한다.

**Tech Stack:** Python 3.13, re (정규식), ABC (인터페이스)

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| `src/agents/query_rewriter/tokenizer.py` | 토큰 추출 + 치환 로직 |
| `src/agents/query_rewriter/dictionary_client.py` | 딕셔너리 클라이언트 인터페이스 + Mock 구현 |
| `tests/test_tokenizer.py` | tokenizer 단위 테스트 |

---

### Task 1: 토큰 추출 함수

**Files:**
- Create: `src/agents/query_rewriter/tokenizer.py`
- Create: `tests/test_tokenizer.py`

- [ ] **Step 1: 테스트 작성 — 토큰 추출**

```python
# tests/test_tokenizer.py
"""tokenizer 단위 테스트."""

from __future__ import annotations

from src.agents.query_rewriter.tokenizer import extract_tokens


class TestExtractTokens:
    def test_extracts_uppercase_with_numbers(self) -> None:
        result = extract_tokens("KPI_01의 추이를 보여줘")
        assert result == ["KPI_01"]

    def test_extracts_multiple_tokens(self) -> None:
        result = extract_tokens("ACC_RCV와 NET_PRF를 비교해줘")
        assert result == ["ACC_RCV", "NET_PRF"]

    def test_ignores_short_tokens(self) -> None:
        result = extract_tokens("AB는 제외하고 ABC_1은 포함")
        assert result == ["ABC_1"]

    def test_ignores_lowercase(self) -> None:
        result = extract_tokens("hello world abc_def")
        assert result == []

    def test_extracts_pure_uppercase(self) -> None:
        result = extract_tokens("GDP 성장률을 알려줘")
        assert result == ["GDP"]

    def test_extracts_with_special_chars(self) -> None:
        result = extract_tokens("P&L_01 보고서와 R-01 데이터")
        assert result == ["P&L_01", "R-01"]

    def test_no_duplicates(self) -> None:
        result = extract_tokens("KPI_01을 보고 KPI_01을 다시 확인")
        assert result == ["KPI_01"]

    def test_empty_string(self) -> None:
        result = extract_tokens("")
        assert result == []

    def test_no_tokens_in_plain_text(self) -> None:
        result = extract_tokens("오늘 매출을 알려주세요")
        assert result == []
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `uv run pytest tests/test_tokenizer.py::TestExtractTokens -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 구현 — extract_tokens**

```python
# src/agents/query_rewriter/tokenizer.py
"""자연어에서 코드형 토큰을 추출하고 딕셔너리 정의로 치환한다."""

import re

# 대문자, 숫자, 특수문자(_-&)의 조합으로 이루어진 3글자 이상 토큰.
# 첫 글자는 반드시 대문자여야 한다 (숫자/특수문자로 시작하는 패턴 제외).
_TOKEN_PATTERN = re.compile(r"\b([A-Z][A-Z0-9_&-]{2,})\b")


def extract_tokens(text: str) -> list[str]:
    """자연어에서 코드형 토큰을 추출하여 중복 없는 리스트로 반환한다.

    Args:
        text: 토큰을 추출할 자연어 문자열.

    Returns:
        추출된 토큰의 중복 제거 리스트 (등장 순서 유지).
    """
    matches = _TOKEN_PATTERN.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for token in matches:
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `uv run pytest tests/test_tokenizer.py::TestExtractTokens -v`
Expected: 9 passed

- [ ] **Step 5: 커밋**

```bash
git add src/agents/query_rewriter/tokenizer.py tests/test_tokenizer.py
git commit -m "feat(tokenizer): add token extraction from natural language"
```

---

### Task 2: 딕셔너리 클라이언트 (인터페이스 + Mock)

**Files:**
- Create: `src/agents/query_rewriter/dictionary_client.py`
- Modify: `tests/test_tokenizer.py`

- [ ] **Step 1: 테스트 작성 — Mock 딕셔너리 클라이언트**

`tests/test_tokenizer.py`에 추가:

```python
from src.agents.query_rewriter.dictionary_client import (
    DictionaryClient,
    MockDictionaryClient,
)


class TestMockDictionaryClient:
    def test_returns_definitions_for_known_keys(self) -> None:
        client = MockDictionaryClient({"KPI_01": "월간 매출 성장률", "ACC_RCV": "미수금 잔액"})
        result = client.lookup(["KPI_01", "ACC_RCV"])
        assert result == {"KPI_01": "월간 매출 성장률", "ACC_RCV": "미수금 잔액"}

    def test_returns_empty_string_for_unknown_keys(self) -> None:
        client = MockDictionaryClient({"KPI_01": "월간 매출 성장률"})
        result = client.lookup(["KPI_01", "UNKNOWN"])
        assert result == {"KPI_01": "월간 매출 성장률", "UNKNOWN": ""}

    def test_empty_keys_returns_empty_dict(self) -> None:
        client = MockDictionaryClient({"KPI_01": "월간 매출 성장률"})
        result = client.lookup([])
        assert result == {}

    def test_implements_interface(self) -> None:
        client = MockDictionaryClient({})
        assert isinstance(client, DictionaryClient)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `uv run pytest tests/test_tokenizer.py::TestMockDictionaryClient -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 구현 — DictionaryClient + MockDictionaryClient**

```python
# src/agents/query_rewriter/dictionary_client.py
"""토큰 딕셔너리 클라이언트: 토큰 키를 정의 값으로 매핑한다."""

from abc import ABC, abstractmethod


class DictionaryClient(ABC):
    """토큰 딕셔너리 조회 인터페이스.

    외부 API 연동 시 이 클래스를 상속하여 구현한다.
    """

    @abstractmethod
    def lookup(self, keys: list[str]) -> dict[str, str]:
        """키 리스트에 대한 정의를 조회한다.

        Args:
            keys: 조회할 토큰 키 리스트.

        Returns:
            {키: 정의} 딕셔너리. 조회 실패한 키는 빈 문자열("")로 매핑.
        """


class MockDictionaryClient(DictionaryClient):
    """테스트용 Mock 딕셔너리 클라이언트.

    생성 시 전달받은 딕셔너리에서 정의를 조회한다.
    존재하지 않는 키는 빈 문자열을 반환한다.
    """

    def __init__(self, data: dict[str, str]) -> None:
        self._data = data

    def lookup(self, keys: list[str]) -> dict[str, str]:
        """키 리스트에 대한 정의를 조회한다."""
        return {key: self._data.get(key, "") for key in keys}
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `uv run pytest tests/test_tokenizer.py::TestMockDictionaryClient -v`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/agents/query_rewriter/dictionary_client.py tests/test_tokenizer.py
git commit -m "feat(tokenizer): add DictionaryClient interface and mock implementation"
```

---

### Task 3: 토큰 치환 함수

**Files:**
- Modify: `src/agents/query_rewriter/tokenizer.py`
- Modify: `tests/test_tokenizer.py`

- [ ] **Step 1: 테스트 작성 — tokenize 함수**

`tests/test_tokenizer.py`에 추가:

```python
from src.agents.query_rewriter.tokenizer import tokenize


class TestTokenize:
    def test_replaces_known_tokens(self) -> None:
        client = MockDictionaryClient({"KPI_01": "월간 매출 성장률"})
        result = tokenize("KPI_01의 추이를 보여줘", client)
        assert result == "KPI_01(월간 매출 성장률)의 추이를 보여줘"

    def test_replaces_multiple_tokens(self) -> None:
        client = MockDictionaryClient({
            "ACC_RCV": "미수금 잔액",
            "NET_PRF": "순이익",
        })
        result = tokenize("ACC_RCV와 NET_PRF를 비교해줘", client)
        assert result == "ACC_RCV(미수금 잔액)와 NET_PRF(순이익)를 비교해줘"

    def test_skips_unknown_tokens(self) -> None:
        client = MockDictionaryClient({"KPI_01": "월간 매출 성장률"})
        result = tokenize("KPI_01과 UNKNOWN_99를 보여줘", client)
        assert result == "KPI_01(월간 매출 성장률)과 UNKNOWN_99를 보여줘"

    def test_skips_empty_value_tokens(self) -> None:
        client = MockDictionaryClient({"KPI_01": ""})
        result = tokenize("KPI_01의 추이", client)
        assert result == "KPI_01의 추이"

    def test_no_tokens_returns_original(self) -> None:
        client = MockDictionaryClient({"KPI_01": "매출"})
        result = tokenize("오늘 매출을 알려주세요", client)
        assert result == "오늘 매출을 알려주세요"

    def test_empty_string(self) -> None:
        client = MockDictionaryClient({})
        result = tokenize("", client)
        assert result == ""

    def test_duplicate_token_replaced_consistently(self) -> None:
        client = MockDictionaryClient({"KPI_01": "매출"})
        result = tokenize("KPI_01을 보고 KPI_01을 다시 확인", client)
        assert result == "KPI_01(매출)을 보고 KPI_01(매출)을 다시 확인"
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `uv run pytest tests/test_tokenizer.py::TestTokenize -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: 구현 — tokenize 함수**

`src/agents/query_rewriter/tokenizer.py`에 추가:

```python
from src.agents.query_rewriter.dictionary_client import DictionaryClient


def tokenize(text: str, client: DictionaryClient) -> str:
    """자연어에서 토큰을 추출, 딕셔너리에서 정의를 조회하고, 원문을 치환한다.

    치환 형식: TOKEN → TOKEN(정의)
    조회 실패(빈 문자열)한 토큰은 치환하지 않는다.

    Args:
        text: 치환 대상 자연어 문자열.
        client: 토큰 정의를 조회할 딕셔너리 클라이언트.

    Returns:
        토큰이 정의로 치환된 문자열.
    """
    tokens = extract_tokens(text)
    if not tokens:
        return text

    definitions = client.lookup(tokens)

    result = text
    for token, definition in definitions.items():
        if definition:
            result = result.replace(token, f"{token}({definition})")

    return result
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `uv run pytest tests/test_tokenizer.py::TestTokenize -v`
Expected: 7 passed

- [ ] **Step 5: 전체 테스트 통과 확인**

Run: `uv run pytest tests/test_tokenizer.py -v`
Expected: 20 passed (ExtractTokens 9 + MockDictionaryClient 4 + Tokenize 7)

- [ ] **Step 6: 커밋**

```bash
git add src/agents/query_rewriter/tokenizer.py tests/test_tokenizer.py
git commit -m "feat(tokenizer): add tokenize function for token replacement"
```

---

### Task 4: query_rewriter와 통합

**Files:**
- Modify: `src/agents/query_rewriter/prompt.py`
- Modify: `src/agents/query_rewriter/rewriter.py`
- Modify: `src/agents/query_rewriter/__init__.py`
- Modify: `tests/test_query_rewriter.py`

- [ ] **Step 1: prompt.py 수정 — 정적 TERM_DICTIONARY 제거, dictionary를 파라미터로 받도록 변경**

```python
# src/agents/query_rewriter/prompt.py
"""쿼리 리라이터 프롬프트 정의."""

from datetime import datetime


def _format_dictionary(dictionary: dict[str, str]) -> str:
    """용어 사전을 프롬프트에 삽입할 문자열로 변환한다."""
    if not dictionary:
        return "없음"
    return "\n".join(f"- {term} → {definition}" for term, definition in dictionary.items())


def build_rewriter_system_prompt(
    now: datetime,
    dictionary: dict[str, str] | None = None,
) -> str:
    """현재 시각과 용어 사전을 반영한 쿼리 리라이터 시스템 프롬프트를 생성한다.

    Args:
        now: 현재 시각. 상대적 시간 표현 해석의 기준이 된다.
        dictionary: 용어 사전. None이면 용어 치환 규칙이 "없음"으로 표시.

    Returns:
        시스템 프롬프트 문자열.
    """
    return REWRITER_SYSTEM_PROMPT.format(
        now=now.strftime("%Y-%m-%d %H:%M (%A)"),
        dictionary=_format_dictionary(dictionary or {}),
    )


REWRITER_SYSTEM_PROMPT = """당신은 사용자 쿼리를 명확하게 재작성하는 전처리기입니다.

## 현재 시각
{now}

## 역할
아래 3가지 규칙을 적용하여 사용자의 마지막 메시지를 재작성하세요.
재작성이 불필요하면 원본 메시지를 그대로 반환하세요.

### 1. 상대적 시간 표현 → 구체적 날짜/기간
- "오늘" → 현재 날짜
- "어제" → 현재 날짜 - 1일
- "지난주" → 직전 월요일~일요일 기간
- "이번 주" → 이번 주 월요일~오늘
- "지난달" → 직전 달 1일~말일
- "이번 달" → 이번 달 1일~오늘
- "최근 N일" → 오늘 기준 N일 전~오늘

### 2. 대화 맥락 보충
이전 대화 내용을 참고하여 모호한 지시어를 구체적으로 바꿔주세요:
- "이거", "그거", "저거" → 지칭하는 대상을 명시
- "더 해줘", "다시 해줘" → 이전에 수행한 작업을 구체적으로 명시
- "반대로 해줘" → 이전 작업의 반대 방향을 명시
- 새로운 독립 질문이면 맥락 보충 없이 그대로 유지

### 3. 용어 사전 치환
아래 사전에 정의된 용어가 쿼리에 포함되면 괄호 안의 정의로 치환하세요:
{dictionary}

## 출력 형식
재작성된 쿼리만 출력하세요. 설명이나 부가 텍스트를 포함하지 마세요."""
```

- [ ] **Step 2: rewriter.py 수정 — tokenizer를 사용하여 사전 동적 구성**

```python
# src/agents/query_rewriter/rewriter.py
"""쿼리 리라이터 노드: 사용자 쿼리를 명확하게 재작성한다."""

from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.query_rewriter.dictionary_client import DictionaryClient, MockDictionaryClient
from src.agents.query_rewriter.prompt import build_rewriter_system_prompt
from src.agents.query_rewriter.tokenizer import extract_tokens
from src.llm import get_chat_model
from src.logging import get_logger, log_node
from src.state import State

logger = get_logger("query_rewriter")

# 프로덕션에서는 외부 API 클라이언트로 교체한다.
_dictionary_client: DictionaryClient = MockDictionaryClient({
    "KPI_01": "월간 매출 성장률",
    "ACC_RCV": "미수금 잔액",
    "NET_PRF": "순이익(매출 - 비용)",
})


def set_dictionary_client(client: DictionaryClient) -> None:
    """딕셔너리 클라이언트를 교체한다 (테스트/프로덕션 전환용)."""
    global _dictionary_client
    _dictionary_client = client


def _find_last_human_message(state: State) -> HumanMessage | None:
    """메시지 리스트에서 마지막 HumanMessage를 찾는다."""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            return msg
    return None


@log_node("query_rewriter")
def query_rewriter_node(state: State) -> dict:
    """사용자 쿼리에 시간 해석, 맥락 보충, 용어 치환을 적용하여 재작성한다."""
    last_human = _find_last_human_message(state)
    if last_human is None:
        logger.warning("HumanMessage를 찾을 수 없음 → 건너뜀")
        return {"messages": []}

    original = last_human.content
    logger.info("원본 쿼리: %s", original)

    # 토큰 추출 → 딕셔너리 조회 → 동적 사전 구성
    tokens = extract_tokens(original)
    dictionary: dict[str, str] = {}
    if tokens:
        lookup_result = _dictionary_client.lookup(tokens)
        dictionary = {k: v for k, v in lookup_result.items() if v}
        logger.info("토큰 조회: %s → %s", tokens, dictionary)

    system_prompt = build_rewriter_system_prompt(now=datetime.now(), dictionary=dictionary)
    llm = get_chat_model()

    response = llm.invoke(
        [SystemMessage(content=system_prompt)] + list(state["messages"]),
    )

    rewritten: str = response.content  # type: ignore[assignment]
    logger.info("리라이팅 결과: %s", rewritten)

    if rewritten.strip() == original.strip():
        logger.info("변경 없음 → 원본 유지")
        return {"messages": []}

    return {"messages": [HumanMessage(content=rewritten)]}
```

- [ ] **Step 3: __init__.py 업데이트 — tokenize, DictionaryClient 추가 export**

```python
# src/agents/query_rewriter/__init__.py
from src.agents.query_rewriter.dictionary_client import DictionaryClient, MockDictionaryClient
from src.agents.query_rewriter.rewriter import query_rewriter_node
from src.agents.query_rewriter.tokenizer import extract_tokens, tokenize

__all__ = [
    "DictionaryClient",
    "MockDictionaryClient",
    "extract_tokens",
    "query_rewriter_node",
    "tokenize",
]
```

- [ ] **Step 4: tests/test_query_rewriter.py 수정 — 깨진 테스트 수정**

기존 테스트에서 `TERM_DICTIONARY`를 import하는 부분과 `build_rewriter_system_prompt`의 시그니처 변경을 반영:

```python
# tests/test_query_rewriter.py 수정사항:

# 1. import에서 TERM_DICTIONARY 제거
from src.agents.query_rewriter.prompt import (
    _format_dictionary,
    build_rewriter_system_prompt,
)

# 2. test_build_prompt_includes_dictionary_terms를 다음으로 교체:
    def test_build_prompt_includes_dictionary_terms(self) -> None:
        now = datetime(2026, 4, 20, 14, 30)
        dictionary = {"TEST_KEY": "테스트 정의"}
        prompt = build_rewriter_system_prompt(now, dictionary=dictionary)
        assert "TEST_KEY" in prompt
        assert "테스트 정의" in prompt

# 3. dictionary 없이 호출하면 "없음"이 포함되는지 확인하는 테스트 추가:
    def test_build_prompt_without_dictionary(self) -> None:
        now = datetime(2026, 4, 20, 14, 30)
        prompt = build_rewriter_system_prompt(now)
        assert "없음" in prompt
```

- [ ] **Step 5: 전체 테스트 통과 확인**

Run: `uv run pytest tests/ -v`
Expected: 전체 통과

- [ ] **Step 6: 커밋**

```bash
git add src/agents/query_rewriter/prompt.py src/agents/query_rewriter/rewriter.py src/agents/query_rewriter/__init__.py tests/test_query_rewriter.py
git commit -m "refactor(query_rewriter): replace static dictionary with tokenizer + dynamic API lookup"
```
