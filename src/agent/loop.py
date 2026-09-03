"""The agent loop, written by hand. No framework.

This is the whole idea behind every agent framework, in one file:

    while not done and within limits:
        1. send the conversation + tool schemas to the model
        2. model replies with either a final answer, or a request to call a tool
        3. if tool: run it, append the result to the conversation
        4. repeat

LangGraph, CrewAI, the OpenAI Agents SDK, Bedrock AgentCore's "managed harness" — all of
them are this loop plus persistence, retries, streaming, and multi-agent coordination.
Read ADR-0003 for why this is being written by hand before adopting LangGraph in week 3.

Run:
    python -m src.agent.loop "Do you encrypt customer data at rest?"
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from dotenv import load_dotenv
from rich.console import Console

from src.agent.bedrock_client import BedrockClient, Usage
from src.agent.tools import TOOL_REGISTRY, TOOL_SPECS

load_dotenv()
console = Console()

SYSTEM_PROMPT = """\
You are a security compliance analyst at a software company. Your job is to answer security \
questionnaire questions sent by an enterprise prospect's security team.

Rules you must follow:
1. Answer ONLY from the company's own policy documents. Use the search_policies tool first.
2. Never invent a policy. If the documents do not cover the question, say so explicitly and \
set confidence to "low".
3. Every answer must cite the source filename you got it from.
4. Map the answer to a NIST 800-53 control ID, and verify that ID with get_control_info \
before you use it.
5. Write the answer the way a security analyst would: direct, specific, no marketing language.

When you have everything you need, reply with ONLY a JSON object, no prose around it:
{
  "answer": "<2-4 sentence answer for the questionnaire>",
  "citation": "<source filename, and the section heading if known>",
  "control_id": "<NIST 800-53 control ID>",
  "confidence": "high" | "medium" | "low",
  "gap": "<if evidence is missing or partial, what is missing; otherwise null>"
}
"""


def run_agent(question: str, verbose: bool = True) -> dict[str, Any]:
    client = BedrockClient()
    usage = Usage()

    max_steps = int(os.environ.get("MAX_AGENT_STEPS", 8))
    max_tokens_run = int(os.environ.get("MAX_TOKENS_PER_RUN", 20000))

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": f"Questionnaire question: {question}"}]}
    ]

    last_tool_call: tuple[str, str] | None = None
    stop_note = "completed"

    for step in range(1, max_steps + 1):
        # --- GUARDRAIL 1: token budget ------------------------------------------------
        # Checked BEFORE the call, so a runaway loop cannot spend past the cap.
        if usage.total >= max_tokens_run:
            stop_note = f"token budget exceeded ({usage.total} >= {max_tokens_run})"
            break

        if verbose:
            console.print(f"[dim]--- step {step} ---[/dim]")

        response = client.converse(
            messages=messages,
            system=SYSTEM_PROMPT,
            tools=TOOL_SPECS,
        )
        usage.add(response.get("usage", {}))

        stop_reason = response["stopReason"]
        assistant_msg = response["output"]["message"]
        messages.append(assistant_msg)

        if stop_reason == "max_tokens":
            # Not a normal path. Means maxTokens is too low or the model is rambling.
            stop_note = "model hit max_tokens mid-response"
            break

        if stop_reason != "tool_use":
            # The model produced a final answer.
            text = "".join(
                block.get("text", "") for block in assistant_msg.get("content", [])
            )
            if verbose:
                console.print(f"[green]final answer[/green]\n{text}")
            return {
                "result": _parse_json_answer(text),
                "raw": text,
                "steps": step,
                "usage": usage,
                "stop": stop_note,
            }

        # --- The model asked for one or more tools ------------------------------------
        tool_results = []
        for block in assistant_msg["content"]:
            if "toolUse" not in block:
                continue
            tool_use = block["toolUse"]
            name = tool_use["name"]
            args = tool_use["input"]

            # --- GUARDRAIL 2: repeated identical call -------------------------------
            # The classic infinite loop: bad tool result -> model retries the exact same
            # call forever. Detect it and tell the model to change approach.
            signature = (name, json.dumps(args, sort_keys=True))
            if signature == last_tool_call:
                result = (
                    "You already made this exact tool call and got the same result. "
                    "Do not repeat it. Either try different search terms, or answer with "
                    'confidence "low" and describe the gap.'
                )
                if verbose:
                    console.print(
                        f"[yellow]repeated call blocked:[/yellow] {name}({args})"
                    )
            else:
                if verbose:
                    console.print(f"[cyan]tool[/cyan] {name}({args})")
                try:
                    result = TOOL_REGISTRY[name](**args)
                except KeyError:
                    # Model hallucinated a tool that does not exist.
                    result = f"ERROR: no tool named '{name}'. Available: {list(TOOL_REGISTRY)}"
                except TypeError as exc:
                    # Model called a real tool with wrong arguments.
                    result = f"ERROR: bad arguments for '{name}': {exc}"
                last_tool_call = signature

            tool_results.append(
                {
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"text": result}],
                        "status": "success",
                    }
                }
            )

        # Tool results go back as a USER message. This trips up everyone the first time.
        messages.append({"role": "user", "content": tool_results})
    else:
        # --- GUARDRAIL 3: step cap ----------------------------------------------------
        stop_note = f"hit max steps ({max_steps}) without a final answer"

    if verbose:
        console.print(f"[red]stopped:[/red] {stop_note}")
    return {
        "result": None,
        "raw": None,
        "steps": max_steps,
        "usage": usage,
        "stop": stop_note,
    }


def _parse_json_answer(text: str) -> dict[str, Any] | None:
    """Models wrap JSON in markdown fences roughly half the time. Strip and parse.

    Week 2 replaces this with a real structured-output tool call, which removes the
    parsing problem entirely. Doing it the fragile way once is instructive.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        return None


def main() -> None:
    if len(sys.argv) < 2:
        console.print('Usage: python -m src.agent.loop "your question here"')
        raise SystemExit(1)

    question = " ".join(sys.argv[1:])
    out = run_agent(question)

    console.rule("run summary")
    console.print(
        f"steps: {out['steps']}  |  {out['usage'].summary()}  |  stop: {out['stop']}"
    )
    if out["result"]:
        console.print_json(data=out["result"])
    elif out["raw"]:
        console.print("[yellow]Could not parse JSON. Raw output above.[/yellow]")


if __name__ == "__main__":
    main()
