# Ontology data sources

Both files under `data/ontology/` are gitignored — one is 10 MB of public data, the other is
derived from it.

## NIST SP 800-53 Rev 5 catalog

    curl -sSL -o data/ontology/nist_800-53_rev5_catalog.json \
      https://raw.githubusercontent.com/usnistgov/oscal-content/main/nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json

NIST's own OSCAL release — the authoritative machine-readable form, not a scraped table.
Loaded version: **5.2.0**, 20 families, 324 base controls, 1,196 including enhancements.
The version matters: a control mapped under Rev 5 is not necessarily the same control in Rev 4.

## SOC 2 Trust Services Criteria crosswalk

Hand-built, in `src/ontology/crosswalk.py`. AICPA publishes an official mapping and it is not
freely redistributable, so this covers ~37 criteria mapped by reading the control statements
on both sides. Every row is stored with a `hand-built:` prefix in its note.

A production system licenses the AICPA mapping or the Secure Controls Framework. See ADR-0013.

## Rebuilding

    python -m src.ontology.store load          # catalog + policy sections
    python -m src.ontology.map propose         # embed and link, ~$0.002
    python -m src.ontology.crosswalk load      # SOC 2 edges
