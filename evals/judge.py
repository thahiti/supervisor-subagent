import json
import logging

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from evals.prompts import JUDGE_SYSTEM_PROMPT, build_judge_user_prompt
from evals.types import EvalConfig, JudgeResult, ScoreDetail

logger = logging.getLogger("supervisor_subagent.eval.judge")


def _extract_json(text: str) -> dict:
    """텍스트에서 JSON을 추출한다."""
    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + len("```")
        end = text.index("```", start)
        text = text[start:end].strip()
    return json.loads(text)


def _parse_judge_response(raw: dict) -> JudgeResult:
    """Judge LLM 응답을 JudgeResult로 변환한다.

    Args:
        raw: 파싱된 JSON dict

    Returns:
        구조화된 JudgeResult
    """
    scores: dict[str, ScoreDetail] = {}
    for key, val in raw.get("scores", {}).items():
        scores[key] = ScoreDetail(
            score=int(val["score"]),
            reason=str(val["reason"]),
        )

    return JudgeResult(
        scores=scores,
        overall_score=float(raw.get("overall_score", 0.0)),
        summary=str(raw.get("summary", "")),
    )


def judge(
    config: EvalConfig,
    input_text: str,
    reference_answer: str,
    actual_output: str,
    criteria: list[str],
) -> JudgeResult:
    """LLM-as-Judge를 호출하여 에이전트 출력을 평가한다.

    Args:
        config: 평가 설정 (모델, temperature)
        input_text: 테스트 입력
        reference_answer: 모범 답안
        actual_output: 에이전트의 실제 출력
        criteria: 평가 기준 목록

    Returns:
        Judge 평가 결과
    """
    llm = ChatOpenAI(
        model=config["judge_model"],
        temperature=config["judge_temperature"],
    )

    user_prompt = build_judge_user_prompt(
        input_text=input_text,
        reference_answer=reference_answer,
        actual_output=actual_output,
        criteria=criteria,
    )

    logger.info("Judge 호출 (model=%s, criteria=%s)", config["judge_model"], criteria)

    try:
        response = llm.invoke([
            SystemMessage(content=JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
    except Exception:
        logger.error("Judge LLM 호출 실패", exc_info=True)
        raise

    content: str = response.content  # type: ignore[assignment]
    logger.info("Judge 응답: %s", content)

    try:
        raw = _extract_json(content)
        return _parse_judge_response(raw)
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error("Judge 응답 파싱 실패: %s", e)
        # 파싱 실패 시 모든 기준 0점 반환
        return JudgeResult(
            scores={c: ScoreDetail(score=0, reason="파싱 실패") for c in criteria},
            overall_score=0.0,
            summary=f"Judge 응답 파싱 실패: {e}",
        )
