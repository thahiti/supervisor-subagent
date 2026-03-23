import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from src.logging.config import get_logger
from src.logging.diff import compute_diff, format_state


def log_node(name: str) -> Callable:
    """노드 함수에 before/after 상태 로깅을 추가하는 데코레이터.

    Args:
        name: 노드 이름 (로그에 표시)

    Returns:
        데코레이터 함수

    Example:
        @log_node("supervisor")
        def supervisor_node(state: State) -> dict:
            ...
    """
    logger = get_logger(f"node.{name}")

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(state: dict, *args: Any, **kwargs: Any) -> dict:
            logger.info("=== BEFORE ===\n%s", format_state(state))

            start = time.monotonic()
            try:
                result = func(state, *args, **kwargs)
            except Exception:
                elapsed = time.monotonic() - start
                logger.error(
                    "=== ERROR === (%.3fs elapsed)",
                    elapsed,
                    exc_info=True,
                )
                raise

            elapsed = time.monotonic() - start
            logger.info("=== AFTER (%.3fs) ===\n%s", elapsed, format_state(result))
            logger.info("=== DIFF ===\n%s", compute_diff(state, result))

            return result

        return wrapper

    return decorator
