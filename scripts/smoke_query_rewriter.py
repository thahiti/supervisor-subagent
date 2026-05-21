"""query_rewriter 워크플로우 스모크.

`scripts.cli.query_rewriter.rewrite`를 공통 평가 프레임워크
(`scripts.eval.run_eval`)로 호출한다. 예제·기대값은 YAML
(`scripts/examples/rewriter.yml`)에서 로드한다. FIXED_NOW로 상대 날짜
변환은 결정적이며, MAX_RETRIES로 LLM 표현 편차를 흡수한다. 실제
LLM을 호출하므로 비결정적·유료이며 의도적으로 실행한다.

실행:
    uv run python -m scripts.smoke_query_rewriter
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from scripts.cli.query_rewriter import rewrite  # noqa: E402
from scripts.eval import load_examples, run_eval  # noqa: E402

EXAMPLES_PATH = "scripts/examples/rewriter.yml"
FIXED_NOW = "2026-04-29T14:30"
MAX_RETRIES = 3


if __name__ == "__main__":
    cases = load_examples(EXAMPLES_PATH)
    sys.exit(
        run_eval(
            cases,
            rewrite,
            now=FIXED_NOW,
            max_retries=MAX_RETRIES,
            source=EXAMPLES_PATH,
        )
    )
