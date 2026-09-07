"""NIST SP 800-53 to SOC 2 Trust Services Criteria, and what that buys.

    python -m src.ontology.crosswalk load
    python -m src.ontology.crosswalk answer CC6.1     # what do we have for this?
    python -m src.ontology.crosswalk gaps             # SOC 2 criteria with no policy

The payoff, which is the reason this table exists at all:

    a buyer sends a SOC 2 questionnaire asking about CC6.1
        -> CC6.1 crosswalks to AC-2, AC-3, AC-6, IA-2, IA-5
        -> those controls are satisfied by these policy sections
        -> we already answered a NIST questionnaire from those same sections

One answer, written once, serving two frameworks. Without the crosswalk the same
policy text has to be found again for every framework a customer asks about, and
"we answered this already, in different words" is invisible.

**Provenance, stated plainly.** AICPA publishes an official 800-53 mapping, and
it is not freely redistributable. This table is hand-built from the control
statements on both sides: about forty mappings covering the Common Criteria and
the Availability and Confidentiality categories. It is deliberately incomplete
and every row is marked `hand-built`, because a crosswalk presented as
authoritative when it is not is worse than none -- someone would rely on it in an
audit. A production system licenses the AICPA mapping or the Secure Controls
Framework, and that is an ADR-0013 consequence, not a detail.
"""

from __future__ import annotations

import sqlite3
import sys

from rich.console import Console

from src.ontology.store import connect

console = Console()

FRAMEWORK = "SOC2"

# criterion -> (description, [nist control ids])
#
# Only base controls. Each row is a judgement made by reading both statements,
# and the descriptions are paraphrases of the criteria rather than quotations of
# AICPA's copyrighted text.
SOC2_MAPPINGS: dict[str, tuple[str, list[str]]] = {
    # CC1 -- Control Environment
    "CC1.1": ("Commitment to integrity and ethical values", ["pm-1", "ps-8", "pl-4"]),
    "CC1.3": (
        "Management establishes structures and authority",
        ["pm-1", "pm-2", "ps-2"],
    ),
    "CC1.4": ("Commitment to competence", ["at-2", "at-3", "ps-3"]),
    "CC1.5": ("Individuals held accountable for responsibilities", ["ps-8", "pl-4"]),
    # CC2 -- Communication and Information
    "CC2.1": ("Relevant quality information is obtained and used", ["pm-9", "ca-7"]),
    "CC2.2": ("Internal communication of security responsibilities", ["at-2", "pl-4"]),
    "CC2.3": ("Communication with external parties", ["ir-6", "sa-9"]),
    # CC3 -- Risk Assessment
    "CC3.1": ("Objectives specified to enable risk identification", ["pm-9", "ra-3"]),
    "CC3.2": ("Risks to objectives are identified and analysed", ["ra-3", "ra-5"]),
    "CC3.3": ("Potential for fraud is considered", ["ra-3", "au-6"]),
    "CC3.4": ("Changes that could affect the system are assessed", ["ra-3", "cm-4"]),
    # CC4 -- Monitoring Activities
    "CC4.1": (
        "Evaluations are performed to confirm controls operate",
        ["ca-2", "ca-7"],
    ),
    "CC4.2": ("Deficiencies are communicated and remediated", ["ca-5", "ra-5"]),
    # CC5 -- Control Activities
    "CC5.1": ("Control activities are selected to mitigate risk", ["pl-2", "cm-2"]),
    "CC5.2": ("Control activities over technology are selected", ["cm-2", "cm-6"]),
    "CC5.3": ("Policies and procedures are deployed", ["pl-1", "pl-4"]),
    # CC6 -- Logical and Physical Access
    "CC6.1": (
        "Logical access security protects information assets",
        ["ac-2", "ac-3", "ac-6", "ia-2", "ia-5"],
    ),
    "CC6.2": ("Registration and authorisation of new users", ["ac-2", "ia-4"]),
    "CC6.3": (
        "Access is modified and removed as roles change",
        ["ac-2", "ps-4", "ps-5"],
    ),
    "CC6.4": ("Physical access to facilities is restricted", ["pe-2", "pe-3"]),
    "CC6.5": ("Data and software are disposed of securely", ["mp-6"]),
    "CC6.6": ("External threats to the system are mitigated", ["sc-7", "si-4"]),
    "CC6.7": (
        "Data in transit and on removable media is protected",
        ["sc-8", "sc-28", "mp-5"],
    ),
    "CC6.8": ("Unauthorised or malicious software is prevented", ["si-3", "cm-7"]),
    # CC7 -- System Operations
    "CC7.1": ("Configuration and vulnerabilities are monitored", ["cm-8", "ra-5"]),
    "CC7.2": ("The system is monitored for anomalies", ["au-6", "si-4"]),
    "CC7.3": ("Security events are evaluated for incident status", ["ir-4", "ir-5"]),
    "CC7.4": ("Identified incidents are responded to", ["ir-4", "ir-6", "ir-8"]),
    "CC7.5": ("The entity recovers from identified incidents", ["ir-4", "cp-10"]),
    # CC8 -- Change Management
    "CC8.1": (
        "Changes are authorised, designed, tested and approved",
        ["cm-3", "cm-4", "sa-10"],
    ),
    # CC9 -- Risk Mitigation
    "CC9.1": ("Risk mitigation activities for business disruption", ["cp-2", "ra-3"]),
    "CC9.2": (
        "Risks from vendors and business partners are managed",
        ["sa-9", "sr-3", "sr-6"],
    ),
    # A -- Availability
    "A1.1": ("Capacity is managed to meet objectives", ["cp-2", "sc-5"]),
    "A1.2": (
        "Backup, recovery and environmental protections",
        ["cp-9", "cp-10", "pe-13"],
    ),
    "A1.3": ("Recovery procedures are tested", ["cp-4"]),
    # C -- Confidentiality
    "C1.1": (
        "Confidential information is identified and maintained",
        ["sc-28", "mp-4", "ra-2"],
    ),
    "C1.2": ("Confidential information is disposed of", ["mp-6", "si-12"]),
}


def load(conn: sqlite3.Connection) -> tuple[int, list[str]]:
    """Insert the crosswalk, skipping any control id not in the catalog.

    Unknown ids are returned rather than ignored: a typo in a control id here
    would silently drop a mapping and quietly understate coverage, which is the
    same fail-open shape as MISTAKES entry 3.
    """
    known = {row["id"] for row in conn.execute("SELECT id FROM control")}
    rows, unknown = [], []
    for criterion, (note, control_ids) in SOC2_MAPPINGS.items():
        for control_id in control_ids:
            if control_id not in known:
                unknown.append(f"{criterion} -> {control_id}")
                continue
            rows.append((control_id, FRAMEWORK, criterion, f"hand-built: {note}"))

    conn.executemany(
        "INSERT OR REPLACE INTO crosswalk (control_id, framework, criterion, note) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows), unknown


def answer_for(conn: sqlite3.Connection, criterion: str) -> None:
    """What policy do we hold for one SOC 2 criterion?

    Two joins: criterion -> controls -> policy sections. This is the query the
    whole ontology exists to make possible, and it is the reason a dictionary of
    eight controls could never have served.
    """
    rows = conn.execute(
        """
        SELECT c.label, c.title, p.source, p.section, s.confidence, s.confirmed_by
        FROM crosswalk x
        JOIN control c ON c.id = x.control_id
        LEFT JOIN satisfies s ON s.control_id = c.id
        LEFT JOIN policy_section p ON p.id = s.section_id
        WHERE x.framework = ? AND x.criterion = ?
        ORDER BY c.label, s.confidence DESC
        """,
        (FRAMEWORK, criterion.upper()),
    ).fetchall()

    if not rows:
        console.print(f"[yellow]{criterion} is not in the crosswalk[/yellow]")
        return

    note = conn.execute(
        "SELECT note FROM crosswalk WHERE framework = ? AND criterion = ? LIMIT 1",
        (FRAMEWORK, criterion.upper()),
    ).fetchone()
    console.print(f"\n[bold]{criterion.upper()}[/bold] — {note['note']}\n")

    covered = uncovered = 0
    for r in rows:
        if r["section"]:
            covered += 1
            mark = (
                "[green]confirmed[/green]"
                if r["confirmed_by"]
                else "[yellow]proposed[/yellow]"
            )
            console.print(
                f"  {r['label']:<7} {r['title'][:30]:<32} {r['section'][:30]:<32} "
                f"{r['confidence']:.3f} {mark}"
            )
        else:
            uncovered += 1
            console.print(
                f"  {r['label']:<7} {r['title'][:30]:<32} [red]no policy[/red]"
            )
    console.print(
        f"\n  {covered} mapped section(s), {uncovered} control(s) with no policy"
    )


def gaps(conn: sqlite3.Connection) -> None:
    """SOC 2 criteria where no mapped control has any policy behind it."""
    rows = conn.execute(
        """
        SELECT x.criterion,
               MIN(x.note) AS note,
               COUNT(DISTINCT x.control_id) AS controls,
               COUNT(DISTINCT s.control_id) AS covered
        FROM crosswalk x
        LEFT JOIN satisfies s ON s.control_id = x.control_id
        WHERE x.framework = ?
        GROUP BY x.criterion ORDER BY covered ASC, x.criterion
        """,
        (FRAMEWORK,),
    ).fetchall()

    empty = [r for r in rows if r["covered"] == 0]
    console.print(
        f"\n[bold]SOC 2 readiness[/bold] over {len(rows)} criteria in the crosswalk\n"
        f"  {len(empty)} criteria have no policy behind any mapped control\n"
    )
    for r in rows:
        bar = "[green]" if r["covered"] else "[red]"
        console.print(
            f"  {bar}{r['criterion']:<7}[/]  {r['covered']}/{r['controls']} controls covered"
            f"   {r['note'].replace('hand-built: ', '')[:46]}"
        )


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "gaps"
    conn = connect()

    if command == "load":
        count, unknown = load(conn)
        console.print(
            f"loaded {count} crosswalk edges over {len(SOC2_MAPPINGS)} criteria"
        )
        if unknown:
            console.print(f"[red]{len(unknown)} unknown control ids:[/red] {unknown}")
    elif command == "answer" and len(sys.argv) > 2:
        answer_for(conn, sys.argv[2])
    elif command == "gaps":
        gaps(conn)
    else:
        console.print(__doc__)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
