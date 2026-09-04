"""BM25 tests. Synthetic documents, no corpus, no network, no cost."""

from __future__ import annotations

from src.rag.bm25 import BM25, tokenize

DOCS = [
    "Customer data is encrypted at rest using AES-256 with keys in AWS KMS.",
    "All traffic uses TLS 1.2 or higher. TLS 1.0 and 1.1 are disabled.",
    "Control SC-28 covers protection of information at rest.",
    "Employees complete security awareness training every year.",
]


def test_tokenizer_keeps_control_ids_and_versions_intact() -> None:
    """The whole point of adding BM25 is exact tokens. A tokenizer that splits
    'sc-28' into 'sc' and '28' throws away the only thing it was hired for."""
    assert "sc-28" in tokenize("Control SC-28 covers data")
    assert "aes-256" in tokenize("encrypted with AES-256")
    assert "1.2" in tokenize("TLS 1.2 or higher")


def test_exact_control_id_finds_its_document() -> None:
    bm25 = BM25(DOCS)
    top = bm25.top_k("SC-28", k=1)
    assert top[0][0] == 2


def test_no_overlap_scores_zero() -> None:
    """A query sharing no terms must return nothing, not a weak guess. Vector
    search always returns its five closest chunks however unrelated they are."""
    bm25 = BM25(DOCS)
    assert bm25.top_k("penguins waddle across Antarctica") == []


def test_a_shared_function_word_still_scores() -> None:
    """Documents the real behaviour, found by a test that first got this wrong.

    'penguins in Antarctica' returns a match, because 'in' happens to appear in
    one document. Inverse document frequency makes that term nearly worthless
    but not worthless, so BM25 alone cannot be trusted as an answerable/not
    signal. Fusion and the answering step have to carry that."""
    bm25 = BM25(DOCS)
    assert bm25.top_k("penguins in Antarctica") != []


def test_rare_terms_outweigh_common_ones() -> None:
    """'rest' appears in two documents, 'sc-28' in one. A query with both must
    rank the sc-28 document first -- that is inverse document frequency doing
    the job a hand-written stopword list did in week 1."""
    bm25 = BM25(DOCS)
    ranked = bm25.top_k("data at rest SC-28", k=4)
    assert ranked[0][0] == 2


def test_repeated_terms_saturate() -> None:
    """Ten mentions must not score ten times one mention. Without saturation a
    keyword-stuffed chunk beats the chunk that actually answers the question."""
    once = BM25(["encryption", "unrelated text here"]).scores("encryption")[0]
    many = BM25(["encryption " * 10, "unrelated text here"]).scores("encryption")[0]
    assert many > once
    assert many < once * 3
