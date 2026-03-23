import logging
import sys


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
ROOT_LOGGER_NAME = "supervisor_subagent"


def setup_logging(level: int = logging.INFO) -> None:
    """프로젝트 전체 로깅을 설정한다.

    Args:
        level: 로깅 레벨 (기본: INFO)
    """
    root_logger = logging.getLogger(ROOT_LOGGER_NAME)
    root_logger.setLevel(level)

    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        root_logger.addHandler(handler)


def get_logger(component: str) -> logging.Logger:
    """컴포넌트별 로거를 반환한다.

    Args:
        component: 컴포넌트 이름 (예: "node.supervisor", "router")

    Returns:
        해당 컴포넌트의 로거
    """
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{component}")
