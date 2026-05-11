# templates를 먼저 import해 모든 SqlTemplate을 레지스트리에 등록시킨 뒤,
# agent를 import해 @registry.agent(description=...) 데코레이터가 자동
# 합성된 description으로 실행되도록 한다. 순서가 바뀌면 description에
# 템플릿 의도 목록이 누락된다.
from src.templated_sql_agent import templates  # noqa: F401
from src.templated_sql_agent.agent import templated_sql_wrapper

__all__ = ["templated_sql_wrapper"]
