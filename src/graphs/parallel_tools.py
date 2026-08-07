# src/graphs/parallel_tools.py
"""
The tool-batch gate (D34, hermes steal #10, §46)
=================================================

HONEST PREMISE, measured (scripts/d34_parallel_tools_measure.py, §46):
langgraph's ToolNode ALREADY executes a multi-call tool batch
CONCURRENTLY — 4 x 300ms fake reads through self._node.invoke finished
in ~0.31s, not the 1.2s serial floor the v1 design assumed. So D34 is
NOT a speed feature. It is a CORRECTNESS gate — which is also hermes'
actual design: _should_parallelize_tool_batch decides concurrent vs
sequential; ToolNode alone decides NOTHING and will happily run
write_file + read_file on the SAME file at the SAME time (race
receipted: the reader gets the OLD content).

Two execution paths replace the coin flip:

1. try_parallel_batch — ELIGIBLE batches run concurrently in this
   pool (input-order results, contextvars copies, one ToolMessage per
   call, every slot filled). Same speed class as ToolNode's default,
   but with the gate's proof that nothing in the batch can touch what
   another call touches.

2. try_sequential_batch — REFUSED batches (path conflict, wildcard,
   unknown blast radius) run strictly in INPUT ORDER, one at a time.
   Deterministic: write-then-read of one file always reads the fresh
   content. Previously this shape RACED.

Eligibility is CONSERVATIVE (any doubt => sequential):
- at least 2 calls (a single call has no ordering question — ToolNode);
- no wildcard tools (execute_code / any *terminal* / ask_user /
  delegate_* — unknown or nested blast radius);
- file tools (anything with a path arg) must be pairwise DISJOINT with
  every writer: a mutating call (write_file/edit_file) conflicts with
  any other file call touching the same file; readers never conflict
  with each other. (Same principle as hermes'
  _should_parallelize_tool_batch, codified from file_state.py's
  docstring receipt.)
- every tool must be IN the wrapped registry (identity, no lookups);
  an unknown name falls to ToolNode so ITS unknown-tool error text
  stays authoritative.

Safety underneath, all already shipped: D31 snapshots once per workspace
per turn regardless of who writes first in the batch; D32's file-state
guard already serializes per-path read-modify-write; per-call exceptions
become error ToolMessages with pairing intact (same crash-net contract
as handle_tool_errors=True, §27 — exact wording differs, documented,
since ToolNode's own text is version-drift territory).

Kill-switch: PULSEAI_PARALLEL_TOOLS=off => TRUE legacy: both gates step
aside, ToolNode does what ToolNode does (concurrent, races included —
pinned loudly so nobody mistakes "off" for "serial").
"""

from __future__ import annotations

import contextvars
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import ToolMessage

FILE_PATH_TOOLS = frozenset({
    "read_file", "list_files", "search_code", "write_file", "edit_file",
})
MUTATING_TOOLS = frozenset({"write_file", "edit_file"})
WILDCARD_TOOLS = frozenset({
    "execute_code", "run_terminal", "start_terminal", "check_terminal",
    "stop_terminal", "list_terminal_processes", "cleanup_terminal_processes",
    "read_terminal_output", "ask_user",
    "delegate_to_subagent", "delegate_to_subagent_batch",
})

_MAX_WORKERS = 4


def _resolved(workspace: str, rel: Any) -> Optional[str]:
    try:
        base = Path(workspace).resolve()
        return str((base / str(rel)).resolve())
    except Exception:
        return None


def _batch_conflict(tool_calls: list[dict], workspace: str) -> bool:
    """True if any writer overlaps any other file call's target."""
    entries = []
    for tc in tool_calls:
        name = tc.get("name", "")
        if name not in FILE_PATH_TOOLS:
            continue
        rel = (tc.get("args") or {}).get("path", ".")
        entries.append((name in MUTATING_TOOLS, _resolved(workspace, rel)))
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            mut_a, pa = entries[i]
            mut_b, pb = entries[j]
            if pa is None or pb is None:
                return True  # unresolvable path => no parallel proof
            if pa == pb and (mut_a or mut_b):
                return True  # someone writes what someone else touches
    return False


def is_eligible(
    tool_calls: list[dict],
    tools_by_name: dict,
    workspace: str,
) -> bool:
    """Conservative batch gate (see module docstring)."""
    if not tool_calls or len(tool_calls) < 2:
        return False
    for tc in tool_calls:
        name = tc.get("name", "")
        if name in WILDCARD_TOOLS:
            return False
        if name not in tools_by_name:
            return False  # never execute what we cannot identify
    if _batch_conflict(tool_calls, workspace):
        return False
    return True


def _run_one(tools_by_name: dict, tc: dict, config) -> ToolMessage:
    """One call -> exactly one ToolMessage (pairing is sacred, §27)."""
    name = tc.get("name", "")
    try:
        tool = tools_by_name[name]
        result = tool.invoke(dict(tc.get("args") or {}), config=config)
        if isinstance(result, ToolMessage):
            # Normalize provider-required fields (rare for our string tools).
            result.tool_call_id = result.tool_call_id or tc["id"]
            result.name = result.name or name
            return result
        if not isinstance(result, str):  # Command/ddict-shaped: ours never
            result = str(result)       # return Command; stringified honestly
        return ToolMessage(content=result, tool_call_id=tc["id"], name=name)
    except Exception as exc:
        return ToolMessage(
            content=(
                f"⛔ Error executing tool `{name}`: "
                f"{type(exc).__name__}: {exc}"
            ),
            tool_call_id=tc["id"],
            name=name,
            status="error",
        )


def try_parallel_batch(
    tool_calls: list[dict],
    tools_by_name: dict,
    config,
    workspace: str,
) -> Optional[list[ToolMessage]]:
    """None => not ours (kill-switch, single call, or refused by the gate —
    the caller then asks try_sequential_batch or ToolNode). Otherwise the
    ordered ToolMessages, every slot filled, order = input order."""
    if os.environ.get("PULSEAI_PARALLEL_TOOLS", "").strip().lower() == "off":
        return None
    if not is_eligible(tool_calls, tools_by_name, workspace):
        return None

    results: list[ToolMessage | None] = [None] * len(tool_calls)
    workers = max(1, min(_MAX_WORKERS, len(tool_calls)))

    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="pulseai-tools"
    ) as pool:
        future_to_index = {}
        for index, tc in enumerate(tool_calls):
            ctx = contextvars.copy_context()
            future_to_index[
                pool.submit(ctx.run, _run_one, tools_by_name, tc, config)
            ] = index
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except Exception as exc:  # paranoia-grade: _run_one never
                tc = tool_calls[index]  # raises; slots must never go missing
                results[index] = ToolMessage(
                    content=(f"⛔ Parallel worker failed for "
                             f"`{tc.get('name', '')}`: {exc!r}"),
                    tool_call_id=tc["id"],
                    name=tc.get("name", ""),
                    status="error",
                )
    # Belt-and-braces: a None slot is a broken pairing — fill, never drop.
    for index, r in enumerate(results):
        if r is None:
            tc = tool_calls[index]
            results[index] = ToolMessage(
                content=f"⛔ Parallel batch produced no result for `{tc.get('name', '')}`.",
                tool_call_id=tc["id"],
                name=tc.get("name", ""),
                status="error",
            )
    return [r for r in results if r is not None]  # all filled by now


def try_sequential_batch(
    tool_calls: list[dict],
    tools_by_name: dict,
    config,
    workspace: str,
) -> Optional[list[ToolMessage]]:
    """The OTHER half of the gate (D34v2): a multi-call batch we refused
    to parallelize must NOT fall into ToolNode's concurrent default —
    that default RACES conflicting calls (measured §46). Run it strictly
    in input order, one call at a time.

    None => caller hands the batch to ToolNode: single call (no ordering
    question), unknown tool name (ToolNode owns that error text), or
    kill-switch (true legacy, races included)."""
    if os.environ.get("PULSEAI_PARALLEL_TOOLS", "").strip().lower() == "off":
        return None
    if not tool_calls or len(tool_calls) < 2:
        return None
    for tc in tool_calls:
        if tc.get("name", "") not in tools_by_name:
            return None  # ToolNode's own unknown-tool path stays canonical
    if is_eligible(tool_calls, tools_by_name, workspace):
        return None  # the parallel path above already claimed it
    return [_run_one(tools_by_name, tc, config) for tc in tool_calls]
