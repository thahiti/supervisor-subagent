"""query_rewriter + router 워크플로우 스모크.

`scripts.cli.query_rewriter_router.route_trace`를 공통 평가
프레임워크(`scripts.eval.run_eval`)로 호출한다. 실제 LLM을 호출하므로
비결정적·유료이며 의도적으로 실행한다.

실행:
    uv run python -m scripts.smoke_query_rewriter_router
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from scripts.cli._examples import ROUTER_EXAMPLES as CASES  # noqa: E402
from scripts.cli.query_rewriter_router import route_trace  # noqa: E402
from scripts.eval import run_eval  # noqa: E402


if __name__ == "__main__":
    sys.exit(run_eval(CASES, route_trace))
