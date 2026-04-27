"""tokenizer 단위 테스트."""

from __future__ import annotations

from src.query_rewriter.dictionary_client import (
    DictionaryClient,
    MockDictionaryClient,
)
from src.query_rewriter.tokenizer import extract_tokens, tokenize


class TestExtractTokens:
    def test_extracts_uppercase_with_numbers(self) -> None:
        result = extract_tokens("KPI_01의 추이를 보여줘")
        assert result == ["KPI_01"]

    def test_extracts_multiple_tokens(self) -> None:
        result = extract_tokens("ACC_RCV와 NET_PRF를 비교해줘")
        assert result == ["ACC_RCV", "NET_PRF"]

    def test_ignores_short_tokens(self) -> None:
        result = extract_tokens("AB는 제외하고 ABC_1은 포함")
        assert result == ["ABC_1"]

    def test_ignores_lowercase(self) -> None:
        result = extract_tokens("hello world abc_def")
        assert result == []

    def test_extracts_pure_uppercase(self) -> None:
        result = extract_tokens("GDP 성장률을 알려줘")
        assert result == ["GDP"]

    def test_extracts_with_special_chars(self) -> None:
        result = extract_tokens("P&L_01 보고서와 R-01 데이터")
        assert result == ["P&L_01", "R-01"]

    def test_no_duplicates(self) -> None:
        result = extract_tokens("KPI_01을 보고 KPI_01을 다시 확인")
        assert result == ["KPI_01"]

    def test_empty_string(self) -> None:
        result = extract_tokens("")
        assert result == []

    def test_no_tokens_in_plain_text(self) -> None:
        result = extract_tokens("오늘 매출을 알려주세요")
        assert result == []


class TestMockDictionaryClient:
    def test_returns_definitions_for_known_keys(self) -> None:
        client = MockDictionaryClient({"KPI_01": "월간 매출 성장률", "ACC_RCV": "미수금 잔액"})
        result = client.lookup(["KPI_01", "ACC_RCV"])
        assert result == {"KPI_01": "월간 매출 성장률", "ACC_RCV": "미수금 잔액"}

    def test_returns_empty_string_for_unknown_keys(self) -> None:
        client = MockDictionaryClient({"KPI_01": "월간 매출 성장률"})
        result = client.lookup(["KPI_01", "UNKNOWN"])
        assert result == {"KPI_01": "월간 매출 성장률", "UNKNOWN": ""}

    def test_empty_keys_returns_empty_dict(self) -> None:
        client = MockDictionaryClient({"KPI_01": "월간 매출 성장률"})
        result = client.lookup([])
        assert result == {}

    def test_implements_interface(self) -> None:
        client = MockDictionaryClient({})
        assert isinstance(client, DictionaryClient)


class TestTokenize:
    def test_replaces_known_tokens(self) -> None:
        client = MockDictionaryClient({"KPI_01": "월간 매출 성장률"})
        result = tokenize("KPI_01의 추이를 보여줘", client)
        assert result == "KPI_01(월간 매출 성장률)의 추이를 보여줘"

    def test_replaces_multiple_tokens(self) -> None:
        client = MockDictionaryClient({
            "ACC_RCV": "미수금 잔액",
            "NET_PRF": "순이익",
        })
        result = tokenize("ACC_RCV와 NET_PRF를 비교해줘", client)
        assert result == "ACC_RCV(미수금 잔액)와 NET_PRF(순이익)를 비교해줘"

    def test_skips_unknown_tokens(self) -> None:
        client = MockDictionaryClient({"KPI_01": "월간 매출 성장률"})
        result = tokenize("KPI_01과 UNKNOWN_99를 보여줘", client)
        assert result == "KPI_01(월간 매출 성장률)과 UNKNOWN_99를 보여줘"

    def test_skips_empty_value_tokens(self) -> None:
        client = MockDictionaryClient({"KPI_01": ""})
        result = tokenize("KPI_01의 추이", client)
        assert result == "KPI_01의 추이"

    def test_no_tokens_returns_original(self) -> None:
        client = MockDictionaryClient({"KPI_01": "매출"})
        result = tokenize("오늘 매출을 알려주세요", client)
        assert result == "오늘 매출을 알려주세요"

    def test_empty_string(self) -> None:
        client = MockDictionaryClient({})
        result = tokenize("", client)
        assert result == ""

    def test_duplicate_token_replaced_consistently(self) -> None:
        client = MockDictionaryClient({"KPI_01": "매출"})
        result = tokenize("KPI_01을 보고 KPI_01을 다시 확인", client)
        assert result == "KPI_01(매출)을 보고 KPI_01(매출)을 다시 확인"
