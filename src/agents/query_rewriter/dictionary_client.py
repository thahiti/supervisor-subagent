"""토큰 딕셔너리 클라이언트: 토큰 키를 정의 값으로 매핑한다."""

from abc import ABC, abstractmethod


class DictionaryClient(ABC):
    """토큰 딕셔너리 조회 인터페이스.

    외부 API 연동 시 이 클래스를 상속하여 구현한다.
    """

    @abstractmethod
    def lookup(self, keys: list[str]) -> dict[str, str]:
        """키 리스트에 대한 정의를 조회한다.

        Args:
            keys: 조회할 토큰 키 리스트.

        Returns:
            {키: 정의} 딕셔너리. 조회 실패한 키는 빈 문자열("")로 매핑.
        """


class MockDictionaryClient(DictionaryClient):
    """테스트용 Mock 딕셔너리 클라이언트.

    생성 시 전달받은 딕셔너리에서 정의를 조회한다.
    존재하지 않는 키는 빈 문자열을 반환한다.
    """

    def __init__(self, data: dict[str, str]) -> None:
        self._data = data

    def lookup(self, keys: list[str]) -> dict[str, str]:
        """키 리스트에 대한 정의를 조회한다."""
        return {key: self._data.get(key, "") for key in keys}
