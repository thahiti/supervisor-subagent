from src.agents.math_agent import math_wrapper
from src.agents.registry import registry
from src.agents.translate_agent import translate_wrapper

registry.register("math", math_wrapper)
registry.register("translate", translate_wrapper)

__all__ = ["math_wrapper", "translate_wrapper", "registry"]
