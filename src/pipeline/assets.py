"""The ingestion pipeline as Dagster assets.

    dagster dev -m src.pipeline.assets        # UI at localhost:3000
    dagster asset materialize -m src.pipeline.assets --select '*'

    raw_documents ─▶ parsed_documents ─▶ policy_markdown ─▶ vector_index
                            │
                            └────────▶ document_catalog

An *asset* in Dagster is a named thing that exists after a computation, rather
than a task that runs. The distinction matters here: "the vector index" is a
thing the system has, and Dagster knows it is stale when the documents beneath
it changed. A task runner would only know that a script ran.

What that buys here, concretely:

  independent steps run in parallel without being told to -- document_catalog
    and policy_markdown both depend only on parsed_documents, and Dagster ran
    them at the same time
  a failure names the stale asset rather than the exited script
  every run records how many documents were rejected and why, as metadata
    attached to the asset rather than a line in a log

What it does not buy without more configuration: skipping work. Materialising
an asset runs it, whether or not anything upstream changed. Staleness is
tracked and displayed; acting on it needs an AutomationCondition.

What it does not buy, honestly: this pipeline has four steps, runs in about
thirty seconds, and processes three documents. Dagster is 43 packages including
a web server and a database ORM. See the ADR -- this is a deliberate trade, not
a claim that the pipeline needed it.

Metadata on each asset is the part worth keeping regardless of orchestrator.
Rejected documents are surfaced as a first-class number, because a pipeline that
quietly drops two of five inputs is worse than one that fails.
"""

# No `from __future__ import annotations` in this module. It turns every
# annotation into a string, and Dagster resolves the `context` parameter's type
# at decoration time to decide what to pass -- so with it on, every asset fails
# with "Cannot annotate context parameter with type AssetExecutionContext".
from pathlib import Path

from dagster import AssetExecutionContext, Definitions, MetadataValue, asset

from src.pipeline.parse import ParsedDocument, parse, to_markdown
from src.rag.chunking import chunk_corpus, load_corpus
from src.rag.embeddings import embed_texts
from src.rag.index import VectorIndex

REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = REPO_ROOT / "pdf_data"
MARKDOWN_DIR = REPO_ROOT / "data" / "policies_real"
INDEX_NAME = "real"


@asset
def raw_documents(context: AssetExecutionContext) -> list[str]:
    """The PDFs on disk, by name.

    Deliberately a separate asset from parsing. When a run produces fewer
    documents than expected, the first question is whether the files arrived or
    whether the parser dropped them, and separating these two answers it.
    """
    paths = sorted(PDF_DIR.glob("*.pdf"))
    context.add_output_metadata(
        {
            "count": len(paths),
            "total_mb": round(sum(p.stat().st_size for p in paths) / 1e6, 2),
            "files": MetadataValue.md("\n".join(f"- {p.name}" for p in paths)),
        }
    )
    return [p.name for p in paths]


@asset(deps=[raw_documents])
def parsed_documents(context: AssetExecutionContext) -> list[ParsedDocument]:
    """Every PDF run through the heading cascade, including the failures.

    Failures are returned rather than filtered. The document_catalog asset needs
    them -- "we rejected your incident response deck because it is a slide deck"
    is something a customer has to be told, not something to drop silently.
    """
    docs = [parse(path) for path in sorted(PDF_DIR.glob("*.pdf"))]
    usable = [d for d in docs if d.usable and d.sections]
    rejected = [d for d in docs if d not in usable]

    context.add_output_metadata(
        {
            "parsed": len(docs),
            "usable": len(usable),
            "rejected": len(rejected),
            "by_method": MetadataValue.json(
                {d.path.name: d.heading_method for d in docs}
            ),
            "rejections": MetadataValue.md(
                "\n".join(
                    f"- **{d.path.name}** — {'; '.join(d.warnings)}" for d in rejected
                )
                or "none"
            ),
        }
    )
    return docs


@asset(deps=[parsed_documents])
def document_catalog(
    context: AssetExecutionContext, parsed_documents: list[ParsedDocument]
) -> list[dict]:
    """One row per document: what it is, where it came from, when it was reviewed.

    The review date is the product-relevant field. A policy last reviewed in 2018
    should not be cited to an auditor as current evidence, and enforcing that
    later requires the date to survive ingestion now.

    The content hash is what makes a re-run cheap and an audit possible: it says
    whether the file behind an answer has changed since the answer was given.
    """
    rows = [
        {
            "source": d.path.name,
            "title": d.title,
            "pages": d.pages,
            "sections": len(d.sections),
            "tables": d.tables,
            "heading_method": d.heading_method,
            "review_date": d.review_date,
            "sha256": d.sha256,
            "usable": d.usable and bool(d.sections),
            "warnings": d.warnings,
        }
        for d in parsed_documents
    ]
    undated = [r["source"] for r in rows if not r["review_date"]]
    context.add_output_metadata(
        {
            "documents": len(rows),
            "no_review_date": len(undated),
            "catalog": MetadataValue.json(rows),
        }
    )
    return rows


@asset(deps=[parsed_documents])
def policy_markdown(
    context: AssetExecutionContext, parsed_documents: list[ParsedDocument]
) -> int:
    """Usable documents written as markdown the week 2 chunker already handles.

    Converting rather than teaching the chunker about PDFs keeps every
    measurement from week 2 applicable, and keeps one parser rather than two.
    """
    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
    for existing in MARKDOWN_DIR.glob("*.md"):
        existing.unlink()

    written = 0
    for doc in parsed_documents:
        if not (doc.usable and doc.sections):
            continue
        (MARKDOWN_DIR / f"{doc.path.stem}.md").write_text(
            to_markdown(doc), encoding="utf-8"
        )
        written += 1

    context.add_output_metadata({"written": written, "path": str(MARKDOWN_DIR)})
    return written


@asset(deps=[policy_markdown])
def vector_index(context: AssetExecutionContext) -> int:
    """Embed the markdown corpus and save the index.

    The only asset here that costs money.

    An earlier version of this docstring claimed Dagster would skip this when
    the documents had not changed. It does not. `asset materialize --select`
    runs what you select, and re-running it with nothing changed re-embedded the
    whole corpus and paid $0.000148 again. Dagster *tracks* staleness and shows
    it in the lineage view; acting on it needs an AutomationCondition, which
    this pipeline does not have. Logged as MISTAKES.md entry 30.
    """
    chunks = chunk_corpus("section", load_corpus(MARKDOWN_DIR))
    result = embed_texts([c.text for c in chunks])

    index = VectorIndex(
        vectors=result.vectors,
        chunks=[
            {"source": c.source, "sections": list(c.sections), "text": c.text}
            for c in chunks
        ],
    )
    index.save(INDEX_NAME)

    tokens = [c.est_tokens for c in chunks]
    context.add_output_metadata(
        {
            "chunks": len(chunks),
            "dimensions": int(result.vectors.shape[1]),
            "input_tokens": result.input_tokens,
            "cost_usd": round(result.usd_cost, 6),
            "max_chunk_tokens": max(tokens) if tokens else 0,
        }
    )
    return len(chunks)


defs = Definitions(
    assets=[
        raw_documents,
        parsed_documents,
        document_catalog,
        policy_markdown,
        vector_index,
    ]
)
