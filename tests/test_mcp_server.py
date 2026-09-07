"""MCP server tests. Ontology queries only -- no model calls."""

from __future__ import annotations

import asyncio
import json

from src.mcp_server import server


def test_every_tool_is_registered() -> None:
    """A tool that fails to register is invisible to the client and silent."""
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == set(server.tool_names())


def test_every_tool_has_a_description_the_model_can_act_on() -> None:
    """Week 1 measured this: a vague tool description ('Searches things.') cost
    2.2x the tokens for the same answer. The description is the interface."""
    for tool in asyncio.run(server.mcp.list_tools()):
        assert tool.description and len(tool.description) > 80, tool.name


def test_an_unknown_control_returns_an_error_not_an_exception() -> None:
    """A tool that raises gives the model a stack trace. A tool that returns an
    error object gives it something it can tell the user."""
    result = json.loads(server.lookup_control("ZZ-99"))
    assert "error" in result


def test_control_labels_are_accepted_the_way_people_write_them() -> None:
    """The catalog stores AC-02; a questionnaire says AC-2. Requiring the padded
    form would make the tool fail on every realistic input."""
    padded = json.loads(server.lookup_control("AC-02"))
    unpadded = json.loads(server.lookup_control("AC-2"))
    assert padded.get("label") == unpadded.get("label") == "AC-02"


def test_coverage_reports_gaps_not_just_totals() -> None:
    result = json.loads(server.control_coverage())
    assert result["controls_total"] > 300
    assert result["controls_without_policy"] > 0
    assert result["by_family"], "a total with no breakdown is not a gap report"
