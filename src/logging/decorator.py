import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from src.logging.config import get_logger
from src.logging.diff import format_changes, format_state_pretty


def log_node(name: str) -> Callable:
    """노드 함수에 상태 변화 로깅을 추가하는 데코레이터.

    노드 진입 시 현재 처리 중인 노드를 명확히 표시하고,
    처리 완료 후 현재 상태와 변경 사항을 구조적으로 출력한다.

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
            logger.info(
                "\n%s\n  [%s] Processing started\n%s",
                "=" * 60, name.upper(), "=" * 60,
            )

            start = time.monotonic()
            try:
                result = func(state, *args, **kwargs)
            except Exception:
                elapsed = time.monotonic() - start
                logger.error(
                    "\n%s\n  [%s] Failed (%.3fs)\n%s",
                    "!" * 60, name.upper(), elapsed, "!" * 60,
                    exc_info=True,
                )
                raise

            elapsed = time.monotonic() - start

            logger.info(
                "\n%s\n"
                "  [%s] Completed (%.3fs)\n"
                "%s\n"
                "  State:\n%s\n"
                "\n"
                "  Changes:\n%s\n"
                "%s",
                "-" * 60,
                name.upper(),
                elapsed,
                "-" * 60,
                format_state_pretty(state | result),
                format_changes(state, result),
                "-" * 60,
            )

            return result

        return wrapper

    return decorator
