"""Verifier tests. No network, no cost.

The grounding check is pure Python and is the part that makes the verifier worth
having, so it is tested directly. The model's judgement is exercised against
adversarial drafts in scripts, not here.
"""

from __future__ import annotations

from src.rag.verify import normalise, quote_is_real, verify_answer

SOURCE = (
    "All customer data stored in production is encrypted at rest using AES-256.\n"
    "Encryption keys are managed in AWS KMS using customer-managed keys with\n"
    "automatic annual rotation."
)


def test_quote_present_in_source_is_real() -> None:
    assert quote_is_real("encrypted at rest using AES-256", SOURCE)


def test_quote_survives_reflowed_whitespace() -> None:
    """The source wraps mid-sentence. A model copying a quote returns it on one
    line, so an exact-bytes match would reject a perfectly good citation."""
    assert quote_is_real(
        "Encryption keys are managed in AWS KMS using customer-managed keys with automatic annual rotation.",
        SOURCE,
    )


def test_quote_survives_case_and_punctuation_drift() -> None:
    assert quote_is_real("ENCRYPTED AT REST USING AES-256", SOURCE)


def test_invented_quote_is_rejected() -> None:
    """The whole point. Asking a model for a quote only helps if something
    checks the quote exists -- otherwise it can fabricate a supporting sentence
    as easily as it can assert `supported: true`."""
    assert not quote_is_real("Keys are rotated every 90 days.", SOURCE)


def test_normalise_collapses_whitespace_and_case() -> None:
    assert normalise("  Hello   WORLD\n") == "hello world"


def test_no_citations_is_unsupported_without_a_model_call() -> None:
    """An answer citing nothing has nothing to check against. That is
    unsupported by definition, and saying so needs no model call."""
    verdict = verify_answer("Do you encrypt data?", "Yes, obviously.", [])
    assert verdict.supported is False
    assert verdict.input_tokens == 0
    assert verdict.unsupported_claims == ["Yes, obviously."]
