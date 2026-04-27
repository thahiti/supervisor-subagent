# 각 에이전트 모듈을 import하여 @registry.agent 데코레이터를 통한 자동 등록을 트리거한다.
from src.math_agent import math_wrapper  # noqa: F401
from src.registry import registry  # noqa: F401
from src.sql_agent import sql_wrapper  # noqa: F401
from src.translate_agent import translate_wrapper  # noqa: F401

__all__ = ["math_wrapper", "sql_wrapper", "translate_wrapper", "registry"]
