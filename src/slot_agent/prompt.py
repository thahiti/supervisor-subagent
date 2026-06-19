"""슬롯 에이전트 시스템 프롬프트 빌더 + 구조화 출력 스키마."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.slot_agent.registry import ScenarioRegistry


class SlotExtraction(BaseModel):
    """LLM이 사용자 메시지에서 추출하는 구조화 출력.

    프롬프트에 JSON 형식을 지시하는 대신 이 스키마를
    `llm.with_structured_output(SlotExtraction)`로 강제한다.
    """

    scenario_id: str | None = Field(
        default=None,
        description="가장 잘 맞는 시나리오의 id. 어떤 시나리오와도 맞지 않으면 null.",
    )
    slots: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "사용자 메시지에 이미 드러난 슬롯만 (슬롯명 → 값). "
            "메시지에 없는 슬롯은 포함하지 않는다. 없으면 빈 객체."
        ),
    )


_SYSTEM_PROMPT_TEMPLATE = """\
당신은 사전 정의된 조회 시나리오의 슬롯을 채우는 에이전트입니다.
사용자 메시지에서 어떤 시나리오에 해당하는지 고르고, 메시지에 이미 드러난
슬롯 값만 추출하세요.

## 규칙
- 슬롯 값을 임의로 추측하지 마세요. 메시지에 없으면 생략하세요.
- 디폴트("전체", "all" 등)를 임의로 적용하지 마세요.
- 어떤 시나리오와도 맞지 않으면 scenario_id를 비워 두세요(null).
- 슬롯의 후보값은 시스템이 DB에서 직접 조회합니다. 값을 지어내지 마세요.

## 추출 항목
- scenario_id: 가장 잘 맞는 시나리오의 id. 맞는 것이 없으면 null.
- slots: 메시지에 이미 드러난 슬롯만 (슬롯명 → 값). 없으면 비웁니다.

## 처리 가능한 시나리오
{catalog}
"""


def build_system_prompt(registry: ScenarioRegistry) -> str:
    """레지스트리의 시나리오 카탈로그를 반영해 시스템 프롬프트를 합성한다."""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        catalog=registry.build_catalog_for_llm()
    )
