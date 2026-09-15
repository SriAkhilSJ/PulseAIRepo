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
- no wildcard tools (execute_code / any *terminal* / clarify /
  delegate_* — unknown blast radius, or clarify BLOCKS the batch on the
  user's answer);
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

Kill-switch: CRUSORAI_PARALLEL_TOOLS=off => TRUE legacy: both gates step
aside, ToolNode does what ToolNode does (concurrent, races included —
pinned loudly so nobody mistakes "off" for "serial").
"""

from __future__ import annotations

import contextvars
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, ToolMessage

FILE_PATH_TOOLS = frozenset({
    "read_file", "list_files", "search_files", "search_code",
    "write_file", "edit_file",
})
MUTATING_TOOLS = frozenset({"write_file", "edit_file"})
WILDCARD_TOOLS = frozenset({
    "execute_code", "run_terminal", "start_terminal", "check_terminal",
    "stop_terminal", "list_terminal_processes", "cleanup_terminal_processes",
    "read_terminal_output", "scaffold_nextjs", "clarify", "todo_list",
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


# Hermes arg discipline (tools/arg_coercion.py — schema-guided, conservative,
# "originals kept whenever a repair is not unambiguous"). The model's training
# prior names file-tool arguments differently than our schemas (field
# 2026-09-06: read_file {'file_path': ...} died in schema validation BEFORE
# any guard could help; the fallback cost a terminal round trip). Repair ONLY
# a REQUIRED parameter that is missing while EXACTLY ONE known alias is
# present and that alias is not itself a schema parameter of the tool.
_ARG_ALIASES: dict[str, tuple[str, ...]] = {
    "path": ("file_path", "filepath", "file", "path_str"),
    "content": ("text", "file_contents", "new_content", "body"),
    "command": ("cmd", "shell_command", "bash_command"),
    "query": ("search_query",),
    "old_string": ("old_text", "find", "search"),
    "new_string": ("new_text", "replace", "replacement"),
    "url": ("link",),
    "cwd": ("working_dir", "working_directory"),
}


def _required_params(tool) -> set:
    try:
        schema = getattr(tool, "args_schema", None)
        fields = getattr(schema, "model_fields", None)
        if fields:
            return {n for n, f in fields.items() if f.is_required()}
    except Exception:
        pass
    try:
        return set(getattr(tool, "args", {}) or {})
    except Exception:
        return set()


def coerce_tool_arg_aliases(tool, args: dict) -> dict:
    """Rename model-dialect keys onto the tool's real parameter names."""
    try:
        required = _required_params(tool)
        schema_params = set(getattr(tool, "args", {}) or {})
        missing = required - set(args)
        for canonical in list(missing):
            for alias in _ARG_ALIASES.get(canonical, ()):
                if alias in args and alias not in schema_params:
                    args[canonical] = args.pop(alias)
                    print(
                        f"[tools] {getattr(tool, 'name', '?')}: argument "
                        f"'{alias}' -> '{canonical}' (model dialect)",
                        flush=True,
                    )
                    break
    except Exception:
        pass  # coercion is best-effort; never blocks dispatch
    return args


def _run_one(tools_by_name: dict, tc: dict, config) -> ToolMessage:
    """One call through the unified durable middleware chokepoint."""
    name = tc.get("name", "")
    args = dict(tc.get("args") or {})
    tool = None
    try:
        tool = tools_by_name[name]
        args = coerce_tool_arg_aliases(tool, args)
        from src.runtime.tool_middleware import execute_tool_transaction
        outcome = execute_tool_transaction(
            name=name, args=args, tool_call_id=tc["id"], config=config,
            invoke=lambda: tool.invoke(args, config=config),
        )
        return ToolMessage(
            content=outcome.content, tool_call_id=tc["id"], name=name,
            status="error" if outcome.status == "error" else "success",
        )
    except Exception as exc:
        # Intent-persistence failure lands here BEFORE invoke() and therefore
        # guarantees no side effect. Result-persistence failure is surfaced
        # loudly so the loop stops rather than compounding unaudited work.
        text = str(exc)
        lowered = text.lower()
        if isinstance(exc, (TypeError, ValueError)) or any(
            marker in lowered for marker in (
                "unexpected keyword", "missing required", "required argument",
                "invalid arguments", "validation",
            )
        ):
            # Hermes teaching-error discipline: the schema IS the repair
            # manual. Name the expected arguments so the very next call
            # is correct (field 2026-09-06: read_file('file_path') cost a
            # whole terminal round trip to recover).
            expected = sorted((_required_params(tool) if tool else set()) or ())
            return ToolMessage(
                content=(
                    f"Error: {name} was called with wrong arguments: {text}\n"
                    f"Expected arguments: {expected}. Fix the argument "
                    f"names/types and call {name} again."
                ),
                tool_call_id=tc["id"], name=name, status="error",
            )
        return ToolMessage(
            content=f"⛔ Tool not executed or runtime halted: {exc}",
            tool_call_id=tc["id"], name=name, status="error",
        )

def repair_tool_call_ids(tool_calls: list[dict]) -> tuple[list[dict], bool]:
    """hermes _uniquify_tool_call_ids (message_sanitization.py, #58327
    loss class): models occasionally reuse or omit call ids inside ONE
    batch — a reused id silently loses the later call's result, because
    results pair by id and a duplicate pair collapses. Repair
    deterministically (sha256 of name:args:index -> call_<12hex>, hermes'
    own scheme) so prompt-cache prefixes stay byte-stable, and return
    (repaired_calls, changed). No-op (identity, False) when ids are
    already unique and present."""
    if len(tool_calls) < 2:
        return tool_calls, False
    import hashlib
    import json as _json

    seen: set[str] = set()
    # #14 (external review): the seed used the POSITIONAL index — reordering
    # the same calls changed every repaired id, defeating the byte-stable
    # prefix claim. Seed on the per-signature OCCURRENCE instead: distinct
    # calls are reorder-stable (occurrence 0); duplicated identical calls
    # (pathological — the D36 sanitizer collapses them) get 0,1,2... in
    # appearance order, which is the only assignable distinction.
    signature_occurrence: dict[str, int] = {}
    changed = False
    repaired: list[dict] = []
    for tc in tool_calls:
        cid = str(tc.get("id") or "").strip()
        if not cid or cid in seen:
            signature = (
                f"{tc.get('name', '')}:"
                f"{_json.dumps(tc.get('args', {}), sort_keys=True)}"
            )
            occurrence = signature_occurrence.get(signature, 0)
            signature_occurrence[signature] = occurrence + 1
            seed = f"{signature}:{occurrence}"
            cid = "call_" + hashlib.sha256(
                seed.encode("utf-8", errors="replace")
            ).hexdigest()[:12]
            changed = True
        seen.add(cid)
        new_tc = dict(tc)
        new_tc["id"] = cid
        repaired.append(new_tc)
    if not changed:
        return tool_calls, False
    return repaired, True


def repair_tool_call_name(tool_name: str, valid_names: set[str]) -> Optional[str]:
    """hermes agent_runtime_helpers.repair_tool_call (#33007): repair a
    mismatched tool name (case, separators, CamelCase, ``_tool`` suffixes
    twice so ``TodoTool_tool`` reduces fully, then fuzzy match) before
    aborting. Returns the repaired name if in valid_names, else None.

    Field receipt (owner log 2026-09-08): the model emitted `terminal` —
    hermes' own shell tool name (terminal_tool.py:1358 `name="terminal"`) —
    into crusor's `run_terminal`-named toolset, then `Bash`, and both fell
    through to ToolNode's terse unknown-name error; the turn flailed and
    died unverified. Same repair, same position (before validation).
    """
    from difflib import get_close_matches
    if not tool_name:
        return None
    # VolcEngine api/plan leaks XML attribute fragments into tool_use.name
    # (`terminal" parameter="command" ...`); trim at the first quote/angle
    # bracket. Do NOT split on whitespace: "write file" must reach `_norm`
    # -> "write_file" (hermes test_space_to_underscore).
    for _xml_sep in ('"', "'", "<", ">"):
        _idx = tool_name.find(_xml_sep)
        if _idx > 0:
            tool_name = tool_name[:_idx]
    if not tool_name:
        return None

    _norm = lambda s: s.lower().replace("-", "_").replace(" ", "_")  # noqa: E731
    _camel_snake = lambda s: re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()  # noqa: E731

    def _strip_tool_suffix(s: str):
        lc = s.lower()
        return next(
            (s[: -len(sfx)].rstrip("_-")
             for sfx in ("_tool", "-tool", "tool") if lc.endswith(sfx)),
            None,
        )

    # Cheap fast-paths first.
    lowered = tool_name.lower()
    if lowered in valid_names:
        return lowered
    normalized = _norm(tool_name)
    if normalized in valid_names:
        return normalized
    cands: set[str] = {tool_name, lowered, normalized, _camel_snake(tool_name)}
    for _ in range(2):  # strip trailing tool-suffix up to twice (TodoTool_tool)
        extra: set[str] = set()
        for c in cands:
            stripped = _strip_tool_suffix(c)
            if stripped:
                extra.update((stripped, _norm(stripped), _camel_snake(stripped)))
        cands |= extra
    for c in cands:
        if c and c in valid_names:
            return c
    matches = get_close_matches(lowered, valid_names, n=1, cutoff=0.7)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Text-tool-call repair (Hermes-pattern: never trust the model's output FORMAT)
# ---------------------------------------------------------------------------
# Some providers (notably sarvam-105b) intermittently emit tool calls as TEXT
# in the assistant content instead of structured `tool_calls`:
#   <tool_call>write_file
#   <arg_key>path</arg_key>
#   <arg_value>components/ui/x.tsx</arg_value>
#   <arg_key>content</arg_key>
#   <arg_value>...code...</arg_value>
# When that happens the runtime sees plain text (no tool_calls), the loop
# finalizes on an empty deliverable, and the run stalls. This parser converts
# that text back into real structured tool calls so the loop can execute —
# the same "repair what the model fumbled" stance as repair_tool_call_ids.
import json as _tc_json
import re as _tc_re


def _coerce_arg_value(raw: str):
    """Interpret a text arg value: JSON for numbers/arrays/objects, else str."""
    s = raw.strip()
    if not s:
        return ""
    if s[0] in "{[\"0123456789-ntf" or s in ("true", "false", "null"):
        try:
            return _tc_json.loads(s)
        except Exception:
            return raw  # keep original (unstripped) for code strings
    return raw


def parse_text_tool_calls(content: str) -> list[dict]:
    """Parse text-dialect <tool_call> blocks into structured tool-call dicts.

    Two dialects (field 2026-09-10: a custom-tier model leaked both):
    - sarvam-style: ``<tool_call>NAME <arg_key>k</arg_key> <arg_value>v</arg_value></tool_call>``
    - hermes' ACP bridge dialect (agent/acp_openai_bridge.py
      TOOL_CALL_BLOCK_RE): ``<tool_call>{"name": ..., "arguments": {...}|"..."}</tool_call>``.
    Blocks matching neither shape are skipped; the caller decides whether
    the text may EXECUTE (repair_text_tool_calls' grace law).
    """
    if not isinstance(content, str) or "<tool_call>" not in content:
        return []
    import hashlib
    calls: list[dict] = []
    for block in content.split("<tool_call>")[1:]:
        block = block.split("</tool_call>")[0]
        # name = text before the FIRST <arg_key> (keep the full block for the
        # pair scan so the first arg is not lost — re.split would eat its tag).
        first_tag = _tc_re.search(r"<arg_key>", block)
        if first_tag:
            name_blob = block[: first_tag.start()]
        else:
            name_blob = block
        name_lines = [ln for ln in name_blob.splitlines() if ln.strip()]
        name = name_lines[-1].strip() if name_lines else ""
        if not name:
            continue
        if not first_tag:
            # hermes _parse_tool_call shape: the block body is JSON — either
            # {"name": ..., "arguments": {...}} or the full OpenAI
            # {"id","type","function":{"name","arguments"}} envelope.
            try:
                obj = _tc_json.loads(name_blob if not name_lines or len(name_lines) > 1
                                     else "".join(name_lines))
            except Exception:
                continue  # neither dialect: stays prose
            fn = obj.get("function") if isinstance(obj, dict) else None
            if not isinstance(fn, dict):
                fn = obj if isinstance(obj, dict) else None
            if not isinstance(fn, dict):
                continue
            fn_name = fn.get("name")
            if not isinstance(fn_name, str) or not fn_name.strip():
                continue
            name = fn_name.strip()
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = _tc_json.loads(args)
                except Exception:
                    args = {"__raw_arguments__": args}
            if not isinstance(args, dict):
                args = {"__raw_arguments__": args}
            provided_id = obj.get("id") if isinstance(obj, dict) else None
            cid = (provided_id.strip() if isinstance(provided_id, str) and provided_id.strip()
                   else "call_txt_" + hashlib.sha256(
                       f"{name}:{_tc_json.dumps(args, sort_keys=True)}:{len(calls)}".encode()
                   ).hexdigest()[:12])
            calls.append({"name": name, "args": args, "id": cid})
            continue
        pairs = _tc_re.findall(
            r"<arg_key>(.*?)</arg_key>\s*<arg_value>(.*?)</arg_value>",
            block, _tc_re.DOTALL,
        )
        args = {k.strip(): _coerce_arg_value(v) for k, v in pairs}
        cid = "call_txt_" + hashlib.sha256(
            f"{name}:{_tc_json.dumps(args, sort_keys=True)}:{len(calls)}".encode()
        ).hexdigest()[:12]
        calls.append({"name": name, "args": args, "id": cid})
    return calls


def _strip_consumed_blocks(content: str) -> str:
    """hermes extract_tool_calls_from_text's cleanup: consumed <tool_call>
    blocks are removed from the displayed text; surrounding prose stays."""
    parts: list[str] = []
    cursor = 0
    while True:
        start = content.find("<tool_call>", cursor)
        if start == -1:
            parts.append(content[cursor:])
            break
        end = content.find("</tool_call>", start)
        if end == -1:  # unterminated block: consume to the end (it never renders)
            break
        parts.append(content[cursor:start])
        cursor = end + len("</tool_call>")
    return "\n".join(p.strip() for p in parts if p and p.strip()).strip()


def repair_text_tool_calls(message, allow: bool = True):
    """Return a new AIMessage with parsed tool_calls if `message` is an
    AIMessage carrying <tool_call> text but no structured tool_calls.
    Otherwise returns the message unchanged.

    `allow=False` (field 2026-09-09 @7a7111b9): the call was made with NO
    tools bound — the D40 budget-grace call or ask mode. Hermes' grace law
    is that a model which keeps hallucinating tool calls still cannot act:
    no tools are bound, echoed names get catalog-rejected for one bounded
    lap, then the loop finalizes on text. The unconditional repair broke
    that law — post-grace the model's TEXT tool calls were parsed and
    EXECUTED (Get-ChildItem, `dir -R`, read_file, search_code — the run's
    ❌❌❌ tail), turning the budget stop into a zombie that kept paying
    provider calls. When disallowed the dialect text stays prose and
    should_continue finalizes the turn.

    Mixed emission (field 2026-09-10: structured calls AND text blocks in
    one message — the text blocks previously stayed as displayed prose and
    their actions never ran): hermes' bridge extracts from the text
    regardless; parsed blocks dedupe against the structured set by
    (name, args) and the leftovers APPEND. Consumed blocks are stripped
    from the displayed content either way (hermes: the raw markup never
    renders); surrounding prose is kept, hermes-cleaned-text style.
    """
    if not allow:
        return message
    if not isinstance(message, AIMessage):
        return message
    content = getattr(message, "content", "")
    if not isinstance(content, str) or "<tool_call>" not in content:
        return message
    parsed = parse_text_tool_calls(content)
    if not parsed:
        return message
    cleaned = _strip_consumed_blocks(content)
    structured = list(getattr(message, "tool_calls", None) or [])
    if structured:
        def _key(call: dict) -> tuple:
            args = call.get("args", call.get("arguments", {}))
            try:
                normalized = _tc_json.dumps(args, sort_keys=True, default=str)
            except Exception:
                normalized = str(args)
            return (str(call.get("name", "")), normalized)

        existing = {_key(tc) for tc in structured}
        leftovers = [tc for tc in parsed if _key(tc) not in existing]
        if not leftovers:
            return message.model_copy(update={"content": cleaned}) if hasattr(message, "model_copy") else message
        return AIMessage(
            content=cleaned,
            tool_calls=[*structured, *leftovers],
            id=getattr(message, "id", None),
            additional_kwargs=getattr(message, "additional_kwargs", {}) or {},
        )
    return AIMessage(content=cleaned, tool_calls=parsed, id=getattr(message, "id", None))


def run_durable_batch_sequential(
    tool_calls: list[dict], tools_by_name: dict, config
) -> list[ToolMessage]:
    """Known calls through the durable transaction path in input order."""
    return [_run_one(tools_by_name, tc, config) for tc in tool_calls]


def try_parallel_batch(
    tool_calls: list[dict],
    tools_by_name: dict,
    config,
    workspace: str,
) -> Optional[list[ToolMessage]]:
    """None => not ours (kill-switch, single call, or refused by the gate —
    the caller then asks try_sequential_batch or ToolNode). Otherwise the
    ordered ToolMessages, every slot filled, order = input order."""
    if os.environ.get("CRUSORAI_PARALLEL_TOOLS", "").strip().lower() == "off":
        return None
    if not is_eligible(tool_calls, tools_by_name, workspace):
        return None

    results: list[ToolMessage | None] = [None] * len(tool_calls)
    workers = max(1, min(_MAX_WORKERS, len(tool_calls)))

    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="crusorai-tools"
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
    if os.environ.get("CRUSORAI_PARALLEL_TOOLS", "").strip().lower() == "off":
        return None
    if not tool_calls or len(tool_calls) < 2:
        return None
    for tc in tool_calls:
        if tc.get("name", "") not in tools_by_name:
            return None  # ToolNode's own unknown-tool path stays canonical
    if is_eligible(tool_calls, tools_by_name, workspace):
        return None  # the parallel path above already claimed it
    return [_run_one(tools_by_name, tc, config) for tc in tool_calls]
