# 각 에이전트 모듈을 import하여 @registry.agent 데코레이터를 통한 자동 등록을 트리거한다.
from src.agents.math_agent import math_wrapper  # noqa: F401
from src.agents.registry import registry
from src.agents.translate_agent import translate_wrapper  # noqa: F401

__all__ = ["math_wrapper", "translate_wrapper", "registry"]
