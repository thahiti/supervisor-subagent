"""에이전트 레지스트리: wrapper 함수의 docstring을 기반으로 에이전트를 등록·관리한다."""

from dataclasses import dataclass
from typing import Callable

from src.state import State


@dataclass
class AgentEntry:
    """레지스트리에 등록된 에이전트 정보.

    Attributes:
        name: 라우팅 키 (예: "math", "translate")
        node_name: 그래프 노드 이름 (예: "math_agent")
        wrapper: 실제 실행할 wrapper 함수
        description: wrapper docstring에서 추출한 설명
    """

    name: str
    node_name: str
    wrapper: Callable[[State], dict]
    description: str


class AgentRegistry:
    """에이전트를 등록하고 조회하는 레지스트리."""

    def __init__(self) -> None:
        self._entries: list[AgentEntry] = []
        self._by_name: dict[str, AgentEntry] = {}

    def register(
        self,
        name: str,
        wrapper: Callable[[State], dict],
        *,
        node_name: str | None = None,
        description: str | None = None,
    ) -> None:
        """에이전트를 레지스트리에 등록한다.

        Args:
            name: 라우팅 키 (supervisor가 선택할 이름)
            wrapper: 그래프 노드로 사용할 wrapper 함수
            node_name: 그래프 노드 이름. 미지정 시 "{name}_agent"
            description: 에이전트 설명. 미지정 시 wrapper의 docstring 사용
        """
        resolved_node_name = node_name or f"{name}_agent"
        resolved_description = description or (wrapper.__doc__ or "").strip()

        if not resolved_description:
            raise ValueError(
                f"에이전트 '{name}'의 description이 없습니다. "
                "wrapper 함수에 docstring을 추가하거나 description을 직접 지정하세요."
            )

        entry = AgentEntry(
            name=name,
            node_name=resolved_node_name,
            wrapper=wrapper,
            description=resolved_description,
        )
        self._entries.append(entry)
        self._by_name[name] = entry

    @property
    def entries(self) -> list[AgentEntry]:
        """등록된 모든 에이전트 목록을 반환한다."""
        return list(self._entries)

    @property
    def agent_names(self) -> list[str]:
        """등록된 모든 에이전트의 라우팅 키 목록을 반환한다."""
        return [e.name for e in self._entries]

    def get(self, name: str) -> AgentEntry | None:
        """이름으로 에이전트를 조회한다."""
        return self._by_name.get(name)

    def build_workers_prompt(self) -> str:
        """supervisor 시스템 프롬프트에 삽입할 워커 목록 문자열을 생성한다."""
        lines: list[str] = []
        for entry in self._entries:
            lines.append(f"- **{entry.name}**: {entry.description}")
        return "\n".join(lines)


# 글로벌 레지스트리 인스턴스
registry = AgentRegistry()
