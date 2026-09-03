"""Tools the agent can call.

Week 1 keeps these dumb on purpose:
  - search_policies() is naive keyword matching, NOT vector search.
  - get_control_info() is a hardcoded dict, NOT an ontology.

Both get replaced (week 2 = real RAG, week 4 = real control ontology). Starting naive
means you can measure how much the real versions actually help, instead of assuming.

Everything here is a plain Python function plus a JSON schema. That pairing — a callable
and a schema the model can read — is all a "tool" ever is, in any framework.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

POLICY_DIR = Path(__file__).resolve().parents[2] / "data" / "policies"

# A tiny slice of NIST SP 800-53 Rev 5. Week 4 replaces this with a real ontology
# (Question -> Control -> Evidence) loaded from a catalog.
CONTROL_CATALOG: dict[str, dict[str, str]] = {
    "SC-28": {
        "family": "System and Communications Protection",
        "title": "Protection of Information at Rest",
        "description": (
            "Protect the confidentiality and integrity of information at rest, "
            "typically via cryptographic mechanisms."
        ),
    },
    "SC-8": {
        "family": "System and Communications Protection",
        "title": "Transmission Confidentiality and Integrity",
        "description": "Protect information during transmission, typically via TLS.",
    },
    "AC-2": {
        "family": "Access Control",
        "title": "Account Management",
        "description": (
            "Define, create, enable, modify, disable, and remove system accounts; "
            "review accounts for compliance on a defined frequency."
        ),
    },
    "AC-6": {
        "family": "Access Control",
        "title": "Least Privilege",
        "description": "Allow only authorized access necessary to accomplish assigned tasks.",
    },
    "AU-2": {
        "family": "Audit and Accountability",
        "title": "Event Logging",
        "description": "Identify events the system is capable of logging and log them.",
    },
    "IA-2": {
        "family": "Identification and Authentication",
        "title": "Identification and Authentication (Organizational Users)",
        "description": "Uniquely identify and authenticate users, including MFA.",
    },
    "RA-5": {
        "family": "Risk Assessment",
        "title": "Vulnerability Monitoring and Scanning",
        "description": "Scan for vulnerabilities and remediate within defined timeframes.",
    },
    "IR-4": {
        "family": "Incident Response",
        "title": "Incident Handling",
        "description": "Implement incident handling for preparation, detection, and recovery.",
    },
}

STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "do",
    "does",
    "you",
    "your",
    "we",
    "our",
    "how",
    "what",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "at",
    "on",
    "with",
    "any",
    "have",
    "has",
    "it",
    "that",
    "this",
    "be",
    "can",
}


def search_policies(query: str, top_k: int = 3) -> str:
    """Naive keyword search over data/policies/*.md.

    MISTAKE TO EXPECT (week 2): this fails on synonyms. Ask "do you encrypt data at rest"
    and it matches. Ask "is customer information protected when stored" and it returns
    nothing useful, because no keyword overlaps. That failure is exactly why RAG needs
    embeddings, and why you should also keep BM25 around for exact IDs like "SC-28".
    """
    if not POLICY_DIR.exists():
        return "ERROR: no policy corpus found at data/policies/"

    terms = {t.strip(".,?()") for t in query.lower().split()} - STOPWORDS
    terms = {t for t in terms if len(t) > 2}

    scored: list[tuple[int, str, str]] = []
    for path in sorted(POLICY_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        # Split on markdown headings so a "chunk" is a section.
        sections = text.split("\n## ")
        for i, section in enumerate(sections):
            body = section if i == 0 else "## " + section
            score = sum(body.lower().count(term) for term in terms)
            if score > 0:
                scored.append((score, path.name, body.strip()))

    if not scored:
        return (
            f"No policy sections matched the terms {sorted(terms)}. "
            "Try different wording, or report that no evidence exists."
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, filename, body in scored[:top_k]:
        snippet = body[:700] + ("..." if len(body) > 700 else "")
        out.append(f"[source: {filename} | keyword_score={score}]\n{snippet}")
    return "\n\n---\n\n".join(out)


def get_control_info(control_id: str) -> str:
    """Look up a NIST 800-53 control by ID."""
    key = control_id.strip().upper()
    entry = CONTROL_CATALOG.get(key)
    if not entry:
        return (
            f"Unknown control '{control_id}'. "
            f"Known controls: {', '.join(sorted(CONTROL_CATALOG))}"
        )
    return json.dumps({"control_id": key, **entry}, indent=2)


# --- Tool schemas (Bedrock Converse format) -------------------------------------------
# The model never sees your Python. It sees ONLY this JSON. If the description is vague,
# the model calls the tool wrongly — prompt engineering starts here, not in the system prompt.

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "toolSpec": {
            "name": "search_policies",
            "description": (
                "Search the company's internal security policy documents for text relevant "
                "to a security questionnaire question. Returns matching sections with their "
                "source filename. Always call this before answering a factual question about "
                "what the company does."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Keywords describing what to look for, e.g. 'encryption at rest KMS'.",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "How many sections to return. Default 3.",
                        },
                    },
                    "required": ["query"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_control_info",
            "description": (
                "Look up the official title and description of a NIST SP 800-53 Rev 5 "
                "control by its ID (e.g. 'SC-28', 'AC-2'). Use this to confirm a control "
                "mapping before citing it."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "control_id": {
                            "type": "string",
                            "description": "NIST 800-53 control identifier, e.g. SC-28.",
                        }
                    },
                    "required": ["control_id"],
                }
            },
        }
    },
]

TOOL_REGISTRY: dict[str, Callable[..., str]] = {
    "search_policies": search_policies,
    "get_control_info": get_control_info,
}
