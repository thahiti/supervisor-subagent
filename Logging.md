# Logging

## 설계 원칙

1. **어떤 노드가 실행 중인지 명확히 표시** — 복잡한 그래프 순환에서 현재 위치를 즉시 파악
2. **상태 변화를 git diff 스타일로 시각화** — 노드 실행 전후의 State 변경을 한눈에 파악
3. **LLM 응답을 원문 그대로 기록** — 요약이나 truncation 없이 디버깅에 필요한 모든 정보 보존

## 구조

```
src/logging/
├── __init__.py       # setup_logging, get_logger, log_node export
├── config.py         # 로거 설정 (포맷, 핸들러)
├── decorator.py      # @log_node 데코레이터
└── diff.py           # 상태 포맷팅 + diff 계산
```

## 로거 네이밍 체계

모든 로거는 `supervisor_subagent` 루트 아래에 계층적으로 구성된다.

```
supervisor_subagent
├── main              # 엔트리포인트
├── supervisor        # Supervisor 내부 동작
├── router.*          # 라우팅 결정
├── agent.*           # 에이전트 내부 동작
└── node.*            # @log_node 데코레이터 출력
```

이 계층 구조로 `node` 레벨을 필터링하면 데코레이터 로그만, `router` 레벨로 라우팅 결정만 선택적으로 확인할 수 있다.

## @log_node 데코레이터

모든 노드 함수에 동일한 로깅 패턴(진입 → 실행 → 완료/실패)을 노드 로직 수정 없이 적용한다.

```python
@log_node("node_name")
def some_node(state: State) -> dict:
    ...
```

**진입**: `========` 구분선으로 현재 노드 강조
**완료**: 실행 시간 + State 변화를 git diff 스타일로 출력
**실패**: `!!!` 구분선 + traceback

출력 예시:

```
------------------------------------------------------------
  [NODE_NAME] Completed (1.234s)
------------------------------------------------------------
  State:
  messages: (list[BaseMessage]) 2 messages
    [0] type: HumanMessage, content: 입력 텍스트
+   [1] type: AIMessage, content:
+       {
+         "next": "agent_a",
+         "reason": "작업 필요"
+       }
-   next_agent: (str) ''
+   next_agent: (str) 'agent_a'
  completed_agents: (list) []
------------------------------------------------------------
```

## 상태 diff 포매터

### git diff 스타일

| Prefix | 의미 |
|--------|------|
| (공백) | 변경 없음 |
| `+` | 추가된 값 |
| `-` | 제거된 값 |
| `-` / `+` 쌍 | 값이 변경됨 |

개발자가 이미 익숙한 `git diff` 시각 언어를 활용하여 학습 비용 없이 상태 변화를 파악한다. `+` marker는 기존 들여쓰기의 공백을 대체하여 정렬을 유지한다.

### 타입 정보

모든 필드에 런타임 타입이 표시된다: `(str)`, `(list[str])`, `(list[BaseMessage])` 등.

### 메시지 콘텐츠

- **JSON**: 파싱 후 pretty-print
- **일반 텍스트**: 원문 그대로 출력
- **tool_calls**: raw JSON으로 name, args, id 등 전체 출력
- **빈 콘텐츠**: 생략

## 로깅 레벨

| 레벨 | 용도 |
|------|------|
| `INFO` | 정상 실행 흐름 (LLM 호출, 노드 진입/완료, 라우팅 결정) |
| `WARNING` | 복구 가능한 문제 (JSON 파싱 실패 → FINISH 폴백, MAX_ITERATIONS 도달) |
| `ERROR` | 실패 (LLM API 오류, 도구 실행 예외, 서브그래프 실행 실패). `exc_info=True` 포함 |
