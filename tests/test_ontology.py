"""Ontology tests. Synthetic catalog, in-memory SQLite, no network, no cost."""

from __future__ import annotations

import json

import pytest


from src.ontology.crosswalk import SOC2_MAPPINGS
from src.ontology.crosswalk import load as load_crosswalk
from src.ontology.store import (
    connect,
    load_catalog,
    load_policy_sections,
    walk_controls,
)

MINI_CATALOG = {
    "catalog": {
        "groups": [
            {
                "id": "ac",
                "title": "Access Control",
                "controls": [
                    {
                        "id": "ac-2",
                        "title": "Account Management",
                        "props": [{"name": "label", "value": "AC-2"}],
                        "parts": [
                            {
                                "name": "statement",
                                "parts": [
                                    {"name": "a", "prose": "Define account types."},
                                    {"name": "b", "prose": "Review accounts."},
                                ],
                            }
                        ],
                        "controls": [
                            {
                                "id": "ac-2.1",
                                "title": "Automated Account Management",
                                "props": [{"name": "label", "value": "AC-2(1)"}],
                                "parts": [
                                    {"name": "statement", "prose": "Automate it."}
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
}


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "o.sqlite")
    path = tmp_path / "cat.json"
    path.write_text(json.dumps(MINI_CATALOG), encoding="utf-8")
    load_catalog(conn, path)
    return conn


def test_enhancements_are_linked_to_their_base_control(db) -> None:
    """AC-2(1) is a stricter variant of AC-2, kept as a self-reference so
    'AC-2 and everything under it' is one query rather than a string prefix
    match on the id."""
    row = db.execute("SELECT parent_id FROM control WHERE id='ac-2.1'").fetchone()
    assert row["parent_id"] == "ac-2"
    base = db.execute("SELECT parent_id FROM control WHERE id='ac-2'").fetchone()
    assert base["parent_id"] is None


def test_nested_statement_parts_are_flattened(db) -> None:
    """An OSCAL statement is a tree of lettered and numbered items. Reading only
    the top-level prose would store an empty statement for most controls."""
    row = db.execute("SELECT statement FROM control WHERE id='ac-2'").fetchone()
    assert "Define account types." in row["statement"]
    assert "Review accounts." in row["statement"]


def test_the_human_readable_label_is_kept(db) -> None:
    """'ac-2' is the id; 'AC-2' is what a questionnaire and an auditor write."""
    row = db.execute("SELECT label FROM control WHERE id='ac-2'").fetchone()
    assert row["label"] == "AC-2"


def test_policy_sections_carry_their_review_date(db, tmp_path) -> None:
    """A policy last reviewed in 2018 is not current evidence. The date has to
    survive ingestion for that to be enforceable later."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "p.md").write_text(
        "# Policy\n\n**Source:** p.pdf · **Last reviewed:** 2/22/2018\n\n"
        "## Access\n\nAccess is least privilege.\n",
        encoding="utf-8",
    )
    assert load_policy_sections(db, corpus) == 1
    row = db.execute("SELECT section, review_date FROM policy_section").fetchone()
    assert row["section"] == "Access"
    assert row["review_date"] == "2/22/2018"


def test_a_mapping_to_an_unknown_control_is_reported_not_dropped(db) -> None:
    """A typo in a control id would silently drop the mapping and understate
    coverage -- the same fail-open shape as the git-secrets bug in week 1."""
    _, unknown = load_crosswalk(db)
    assert unknown, "the mini catalog has one control, so most mappings are unknown"
    assert all("->" in u for u in unknown)


def test_every_crosswalk_criterion_maps_to_at_least_one_control() -> None:
    """A criterion with no controls behind it would report as a permanent gap
    and be indistinguishable from genuinely missing policy."""
    empty = [c for c, (_, ids) in SOC2_MAPPINGS.items() if not ids]
    assert not empty


def test_crosswalk_uses_base_controls_only() -> None:
    """Enhancement ids contain a dot. A policy that satisfies AC-2 says nothing
    about whether AC-2(1) is met, so mapping to enhancements would manufacture
    coverage."""
    with_dots = [
        (c, i) for c, (_, ids) in SOC2_MAPPINGS.items() for i in ids if "." in i
    ]
    assert not with_dots


def test_walk_controls_returns_parents_before_children() -> None:
    """The table has a self-referencing foreign key, so a child inserted before
    its parent would fail on a database that enforces them."""
    controls = walk_controls(MINI_CATALOG["catalog"]["groups"][0]["controls"], "ac")
    ids = [c.id for c in controls]
    assert ids.index("ac-2") < ids.index("ac-2.1")


# --- answer -> controls -> frameworks ---------------------------------------


def test_only_cited_sections_reach_the_control_mapping(tmp_path, monkeypatch) -> None:
    """A control reached through a passage the drafter retrieved but did not use
    is not evidenced by this answer. Counting it would inflate coverage with
    controls no citation supports."""
    import src.graph.controls as controls_mod

    conn = connect(tmp_path / "o.sqlite")
    cat = tmp_path / "c.json"
    cat.write_text(json.dumps(MINI_CATALOG), encoding="utf-8")
    load_catalog(conn, cat)
    conn.execute(
        "INSERT INTO policy_section (id, source, section, text) VALUES (1,'a.md','Cited','x')"
    )
    conn.execute(
        "INSERT INTO policy_section (id, source, section, text) VALUES (2,'a.md','Ignored','y')"
    )
    conn.executemany(
        "INSERT INTO satisfies (control_id, section_id, confidence, method) VALUES (?,?,?,?)",
        [("ac-2", 1, 0.6, "embedding"), ("ac-2.1", 2, 0.9, "embedding")],
    )
    conn.commit()
    monkeypatch.setattr(controls_mod, "connect", lambda *a, **k: conn)

    state = {
        "retrieved": [
            {"source": "a.md", "section": "Cited", "text": "x", "score": 0.5},
            {"source": "a.md", "section": "Ignored", "text": "y", "score": 0.4},
        ],
        "citations": [1],
    }
    result = controls_mod.controls_for(state)
    assert [c["label"] for c in result["controls"]] == ["AC-2"]


def test_an_answer_with_no_citations_maps_to_nothing(tmp_path, monkeypatch) -> None:
    import src.graph.controls as controls_mod

    monkeypatch.setattr(
        controls_mod, "connect", lambda *a, **k: connect(tmp_path / "o.sqlite")
    )
    result = controls_mod.controls_for({"retrieved": [], "citations": []})
    assert result == {"controls": [], "soc2": [], "unconfirmed": 0}


# --- the labelled mapping set -----------------------------------------------


def test_labelled_set_points_at_real_controls() -> None:
    """A typo'd control id in the labels would count as a permanent miss and
    quietly depress recall forever -- the same silent-zero failure the week 2
    golden set validator exists to prevent."""
    import yaml

    from src.ontology.evaluate_mapping import LABELLED_SET
    from src.ontology.store import connect as real_connect

    conn = real_connect()
    known = {r["id"] for r in conn.execute("SELECT id FROM control")}
    labels = yaml.safe_load(LABELLED_SET.read_text(encoding="utf-8"))["sections"]

    unknown = [
        (s["section"], c) for s in labels for c in s["expected"] if c not in known
    ]
    assert not unknown, f"labels reference controls not in the catalog: {unknown}"


def test_labelled_set_contains_sections_that_satisfy_nothing() -> None:
    """Without negative examples, precision cannot be measured: a mapper that
    maps everything to something would score perfectly on positives alone."""
    import yaml

    from src.ontology.evaluate_mapping import LABELLED_SET

    labels = yaml.safe_load(LABELLED_SET.read_text(encoding="utf-8"))["sections"]
    empty = [s for s in labels if s["expected"] == []]
    assert len(empty) >= 3, "need several sections whose correct answer is no control"


def test_labels_use_base_controls_only() -> None:
    """An enhancement id contains a dot. A section satisfying AC-2 says nothing
    about AC-2(1), so labelling one would make recall unreachable."""
    import yaml

    from src.ontology.evaluate_mapping import LABELLED_SET

    labels = yaml.safe_load(LABELLED_SET.read_text(encoding="utf-8"))["sections"]
    with_dots = [c for s in labels for c in s["expected"] if "." in c]
    assert not with_dots


def test_scoring_counts_a_spurious_mapping_against_precision() -> None:
    """The arithmetic itself, without embeddings: a prediction not in the labels
    must be a false positive, or the whole measurement is decorative."""
    from src.ontology.evaluate_mapping import evaluate

    labels = [
        {"section_id": 1, "section": "A", "expected": ["ac-2"]},
        {"section_id": 2, "section": "B", "expected": []},
    ]
    scores = {
        1: {"ac-2": 0.9, "pe-3": 0.8},
        2: {"ac-2": 0.7, "pe-3": 0.1},
    }
    result = evaluate(labels, scores, threshold=0.5, top_k=5)
    assert result["tp"] == 1
    assert result["fp"] == 2, "pe-3 on A and ac-2 on B are both wrong"
    assert result["precision"] == pytest.approx(1 / 3)
    assert result["recall"] == 1.0
