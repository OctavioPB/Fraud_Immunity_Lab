"""
Unit tests for ml/embeddings/pii_tokenizer.py.

Verifies Hard Rule #4 compliance: PII is tokenized before any embedding or
Pinecone call. Tests use a fixed secret to ensure determinism.
"""

import pytest

from ml.embeddings.pii_tokenizer import PIITokenizer, TokenizationReport


@pytest.fixture
def tokenizer() -> PIITokenizer:
    return PIITokenizer(secret=b"test-secret-key-for-unit-tests")


class TestTokenize:
    def test_returns_tok_prefix(self, tokenizer: PIITokenizer) -> None:
        result = tokenizer.tokenize("ACC-123456")
        assert result.startswith("tok_")

    def test_deterministic(self, tokenizer: PIITokenizer) -> None:
        a = tokenizer.tokenize("ACC-123456")
        b = tokenizer.tokenize("ACC-123456")
        assert a == b

    def test_different_values_different_tokens(self, tokenizer: PIITokenizer) -> None:
        a = tokenizer.tokenize("ACC-001")
        b = tokenizer.tokenize("ACC-002")
        assert a != b

    def test_token_length(self, tokenizer: PIITokenizer) -> None:
        # tok_ prefix + 32 hex chars
        result = tokenizer.tokenize("any-value")
        assert len(result) == len("tok_") + 32


class TestIsPiiField:
    def test_account_id_is_pii(self, tokenizer: PIITokenizer) -> None:
        assert tokenizer.is_pii_field("account_id") is True

    def test_ssn_is_pii(self, tokenizer: PIITokenizer) -> None:
        assert tokenizer.is_pii_field("ssn") is True

    def test_email_is_pii(self, tokenizer: PIITokenizer) -> None:
        assert tokenizer.is_pii_field("email") is True

    def test_amount_is_not_pii(self, tokenizer: PIITokenizer) -> None:
        assert tokenizer.is_pii_field("amount") is False

    def test_case_insensitive(self, tokenizer: PIITokenizer) -> None:
        assert tokenizer.is_pii_field("ACCOUNT_ID") is True
        assert tokenizer.is_pii_field("Account_Id") is True


class TestScanValue:
    def test_detects_ssn(self, tokenizer: PIITokenizer) -> None:
        found = tokenizer.scan_value("user ssn is 123-45-6789")
        assert "ssn" in found

    def test_detects_email(self, tokenizer: PIITokenizer) -> None:
        found = tokenizer.scan_value("contact user@example.com for info")
        assert "email" in found

    def test_detects_credit_card(self, tokenizer: PIITokenizer) -> None:
        found = tokenizer.scan_value("card 4111 1111 1111 1111 used")
        assert "credit_card" in found

    def test_clean_text_returns_empty(self, tokenizer: PIITokenizer) -> None:
        found = tokenizer.scan_value("transaction amount 99.50 USD retail")
        assert found == {}

    def test_detects_iban(self, tokenizer: PIITokenizer) -> None:
        found = tokenizer.scan_value("IBAN: GB29NWBK60161331926819")
        assert "iban" in found


class TestTokenizeRecord:
    def test_account_id_is_tokenized(self, tokenizer: PIITokenizer) -> None:
        record = {"account_id": "ACC-999", "amount": 100.0}
        safe, report = tokenizer.tokenize_record(record)
        assert safe["account_id"].startswith("tok_")
        assert "account_id" in report.tokenized_fields

    def test_non_pii_fields_pass_through(self, tokenizer: PIITokenizer) -> None:
        record = {"amount": 50.0, "currency": "USD", "channel": "card_present"}
        safe, report = tokenizer.tokenize_record(record)
        assert safe["amount"] == 50.0
        assert safe["currency"] == "USD"
        assert report.tokenized_fields == []

    def test_pii_in_value_is_redacted(self, tokenizer: PIITokenizer) -> None:
        record = {"notes": "customer email is user@example.com call back"}
        safe, report = tokenizer.tokenize_record(record)
        assert safe["notes"] == "[REDACTED]"
        assert "notes" in report.detected_patterns

    def test_non_mutating(self, tokenizer: PIITokenizer) -> None:
        original = {"account_id": "ACC-123", "amount": 42.0}
        safe, _ = tokenizer.tokenize_record(original)
        assert original["account_id"] == "ACC-123"  # original unchanged
        assert safe["account_id"] != "ACC-123"

    def test_nested_dict_tokenized(self, tokenizer: PIITokenizer) -> None:
        record = {"geo": {"country": "US"}, "user": {"account_id": "ACC-777"}}
        safe, report = tokenizer.tokenize_record(record)
        assert safe["user"]["account_id"].startswith("tok_")
        assert any("account_id" in f for f in report.tokenized_fields)

    def test_report_pii_found_true(self, tokenizer: PIITokenizer) -> None:
        record = {"account_id": "ACC-111"}
        _, report = tokenizer.tokenize_record(record)
        assert report.pii_found is True

    def test_report_pii_found_false_for_clean(self, tokenizer: PIITokenizer) -> None:
        record = {"amount": 10.0, "channel": "ach"}
        _, report = tokenizer.tokenize_record(record)
        assert report.pii_found is False

    def test_extra_pii_fields_respected(self, tokenizer: PIITokenizer) -> None:
        record = {"custom_ref": "CUST-ABC123", "amount": 5.0}
        safe, report = tokenizer.tokenize_record(
            record, extra_pii_fields={"custom_ref"}
        )
        assert safe["custom_ref"].startswith("tok_")
        assert "custom_ref" in report.tokenized_fields


class TestBuildEmbeddingText:
    def test_includes_account_token(self, tokenizer: PIITokenizer) -> None:
        token = "tok_abc123"
        text = tokenizer.build_embedding_text(token, {"transaction_count": 10})
        assert "tok_abc123" in text

    def test_includes_stats(self, tokenizer: PIITokenizer) -> None:
        stats = {
            "avg_amount": 250.0,
            "transaction_count": 100,
            "currency": "EUR",
        }
        text = tokenizer.build_embedding_text("tok_xyz", stats)
        assert "250.00" in text
        assert "100" in text
        assert "EUR" in text

    def test_no_raw_account_id_in_text(self, tokenizer: PIITokenizer) -> None:
        raw_account_id = "ACC-SENSITIVE-12345"
        token = tokenizer.tokenize(raw_account_id)
        text = tokenizer.build_embedding_text(token, {"transaction_count": 5})
        assert raw_account_id not in text
