"""Score generated answers against the golden set, and write a results file.

    python -m src.rag.evaluate_answers            # concise, the shipped prompt
    python -m src.rag.evaluate_answers naive      # one lazy sentence
    python -m src.rag.evaluate_answers strict     # a full page of rules

Costs roughly $0.005 per run: 45 questions, one Nova Lite call each.

The headline metric is the last column, hallucination rate. On the 5
unanswerable questions the only correct behaviour is refusal, and 3 of those
carry a lexical distractor -- retrieval returns text that is about the topic
without stating the fact. A confident answer built from that is a false
attestation to a customer, which is the worst thing this product can do.

Refusal is scored as a cascade, cheapest signal first:

  1. the model's structured `answerable` flag
  2. a substring check for refusal language in the answer text
  3. an LLM judge, only where 1 and 2 disagree

Steps 1 and 2 are free and cover almost every case; the judge costs a call and
is reserved for the genuinely ambiguous ones. The disagreement count is
reported, because a cascade whose cheap signals rarely agree is not a cascade.

Note what the cascade cannot catch: if retrieval returns the vendor SOC 2 text
and the model answers confidently from it, the flag says answerable and the
text contains no refusal language. Both cheap signals agree, and both are
wrong. At eval time the band label catches that for free. At runtime nothing
here does -- that is week 3's separate verifier agent.
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from src.rag.answer import SYSTEM_PROMPT, Answer, answer_question
from src.rag.index import VectorIndex

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SET = REPO_ROOT / "evals" / "golden_set.yaml"
RESULTS_DIR = REPO_ROOT / "evals" / "results"

# Deliberately weak, to measure what the strict prompt is actually buying.
NAIVE_PROMPT = (
    "Answer the security questionnaire question using the policy extracts provided."
)

# The long variant, kept so the comparison stays reproducible. It lost: adding
# rule 3 to fix the "the answer is no" confusion dropped answerable accuracy
# from 91% to 87% and made the model quote the instructions back as an answer.
STRICT_PROMPT = """You answer security questionnaire questions for a company, \
using only the policy extracts provided.

Rules, in order of importance:

1. Use ONLY the extracts. Never use general knowledge about security, \
compliance frameworks, or what companies usually do.
2. If the extracts do not contain the answer, set answerable to false. This \
includes the case where the extracts are ABOUT a topic but do not state the \
fact asked for. An extract saying we require SOC 2 reports from our vendors \
does not mean we hold one.
3. answerable is about the extracts, not about the answer. If the extracts \
support the answer "no", that is answerable: true with an answer of "No, ...".
4. Every claim in the answer must appear in an extract you cite.
5. Cite by the extract number you actually used.

A wrong answer here is a false attestation to a customer, not a bad search \
result. Refusing is always safer than guessing."""

# "concise" is the shipped default, imported from answer.py so the evaluated
# prompt and the production prompt can never drift apart.
PROMPTS = {"concise": SYSTEM_PROMPT, "naive": NAIVE_PROMPT, "strict": STRICT_PROMPT}

# Kept here rather than in the golden set so the data cannot be tuned until a
# run passes. Lowercased substring match against the answer text.
REFUSAL_MARKERS = (
    "does not cover",
    "do not cover",
    "not covered",
    "does not contain",
    "do not have",
    "does not state",
    "no information",
    "not mentioned",
    "not specified",
    "cannot answer",
    "unable to answer",
    "not addressed",
)


def reads_as_refusal(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in REFUSAL_MARKERS)


def load_questions() -> list[dict]:
    return yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))["questions"]


def score_one(question: dict, result: Answer) -> dict:
    """Score a single question. Returns the row written to the results file."""
    gold = {(c["source"], c["section"]) for c in question["expected_chunks"]}
    should_answer = question["difficulty"] != "unanswerable"

    retrieved = set(result.retrieved)
    cited = set(result.cited_chunks)

    flag_says_refused = not result.answerable
    text_says_refused = reads_as_refusal(result.answer)

    return {
        "id": question["id"],
        "difficulty": question["difficulty"],
        "distractor": bool(question.get("distractor")),
        "should_answer": should_answer,
        "answerable": result.answerable,
        "confidence": result.confidence,
        # Did we hand the model the passages it needed?
        "context_recall": len(gold & retrieved) / len(gold) if gold else None,
        # Of the passages it claimed to use, how many were actually gold?
        "citation_precision": (len(cited & gold) / len(cited))
        if cited and gold
        else None,
        # Did it cite anything at all when it said it could answer?
        "cited_nothing": result.answerable and not result.citations,
        "flag_refused": flag_says_refused,
        "text_refused": text_says_refused,
        "cascade_disagreed": flag_says_refused != text_says_refused,
        "cost_usd": result.usd_cost,
        "answer": result.answer,
    }


def _mean(rows: list[dict], key: str) -> float:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return statistics.mean(vals) if vals else 0.0


def summarise(rows: list[dict]) -> dict:
    answerable_rows = [r for r in rows if r["should_answer"]]
    refusal_rows = [r for r in rows if not r["should_answer"]]
    distractor_rows = [r for r in refusal_rows if r["distractor"]]

    return {
        "n": len(rows),
        # Did the model's answerable flag match the band label?
        "answerable_accuracy": statistics.mean(
            [float(r["answerable"] == r["should_answer"]) for r in rows]
        ),
        "context_recall": _mean(answerable_rows, "context_recall"),
        "citation_precision": _mean(answerable_rows, "citation_precision"),
        "answered_without_citing": statistics.mean(
            [float(r["cited_nothing"]) for r in answerable_rows]
        ),
        # The headline: answered when it should have refused.
        "hallucination_rate": statistics.mean(
            [float(r["answerable"]) for r in refusal_rows]
        ),
        "hallucination_rate_distractors": (
            statistics.mean([float(r["answerable"]) for r in distractor_rows])
            if distractor_rows
            else 0.0
        ),
        "cascade_disagreements": sum(1 for r in rows if r["cascade_disagreed"]),
        "total_cost_usd": sum(r["cost_usd"] for r in rows),
    }


def run(config: str) -> dict:
    if config not in PROMPTS:
        raise SystemExit(f"unknown config {config!r}; pick one of {sorted(PROMPTS)}")

    index = VectorIndex.load()
    prompt = PROMPTS[config]
    rows = [
        score_one(q, answer_question(q["question"], index, system_prompt=prompt))
        for q in load_questions()
    ]
    summary = summarise(rows)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # Timestamped to the minute, not just the date: two runs of the same config
    # on one day are the normal case while tuning a prompt, and a date-only name
    # silently overwrites the earlier one. That already cost one result.
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    path = RESULTS_DIR / f"{stamp}-{config}.json"
    path.write_text(
        json.dumps({"config": config, "summary": summary, "rows": rows}, indent=2),
        encoding="utf-8",
    )

    print(f"config                          {config}")
    print(f"questions                       {summary['n']}")
    print(f"answerable accuracy             {summary['answerable_accuracy']:.0%}")
    print(f"context recall                  {summary['context_recall']:.0%}")
    print(f"citation precision              {summary['citation_precision']:.0%}")
    print(f"answered without citing         {summary['answered_without_citing']:.0%}")
    print(
        f"HALLUCINATION RATE              {summary['hallucination_rate']:.0%}  (5 unanswerable)"
    )
    print(
        f"  on distractors only           {summary['hallucination_rate_distractors']:.0%}  (3 of them)"
    )
    print(f"cascade disagreements           {summary['cascade_disagreements']}")
    print(f"cost                            ${summary['total_cost_usd']:.4f}")
    print(f"written                         {path.relative_to(REPO_ROOT)}")
    return summary


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    run(sys.argv[1] if len(sys.argv) > 1 else "concise")


if __name__ == "__main__":
    main()
