"""A stdio MCP server that exposes the Architect skill library.

Transport: newline-delimited JSON-RPC 2.0 over stdin/stdout (MCP stdio), the same
framing `src/tools/mcp_client.py` speaks.

Design rules carried over from the internal tools:
  * one skill directory = one node, derived from disk, never declared twice;
  * skill_view takes several books in one call;
  * architect skills are planning instruments — `skill_bundle` refuses to run in
    the executing phase, deliberate reads stay allowed;
  * never raise into the model: every failure is a code, a message and a recovery
    hint;
  * truncation is never silent.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
import uuid
from typing import Any

from src.mcp_skills.index import SCHEME, SkillIndex, get_index
from src.mcp_skills.telemetry import METRICS, log

# Supported protocol revisions, newest first. We negotiate down to whatever the
# client asked for; a client that asks for something unknown gets the newest we
# speak, and is free to close. 2026-07-28 is the revision this server is written
# against for resource caching and completion.
SUPPORTED_VERSIONS = ("2026-07-28", "2025-06-18", "2025-03-26", "2024-11-05")
PROTOCOL_VERSION = SUPPORTED_VERSIONS[0]
LEGACY_VERSION = "2024-11-05"
SERVER_INFO = {"name": "crusor-skills", "version": "1.0.0"}

MAX_VIEW_CHARS = 24_000
MAX_RESOURCE_CHARS = 8_000
MAX_SEARCH = 20

ERROR_CODES = {
    "UNKNOWN_SHELF": "no such shelf",
    "UNKNOWN_BOOK": "no such book",
    "BAD_URI": "malformed skill:// uri",
    "PHASE_DENIED": "architect skills are planning instruments",
    "BUDGET_EXCEEDED": "response budget reached",
    "SKILL_INVALID": "book could not be read",
    "UNKNOWN_TOOL": "no such tool",
    "LIBRARY_UNAVAILABLE": "skills library not readable",
    "INTERNAL": "server error",
}


class ToolError(Exception):
    """Structured, model-readable failure. Never escapes as a traceback."""

    def __init__(self, code: str, message: str, **extra: Any):
        self.code = code
        self.message = message
        self.extra = extra
        super().__init__(f"{code}: {message}")

    def payload(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


def tool_text(payload: dict | str) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}]}


def tool_error(err: ToolError) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(err.payload(), ensure_ascii=False)}],
            "isError": True}


class SkillMCPServer:
    def __init__(self, index: SkillIndex | None = None, refresh_seconds: float | None = None):
        self._index: SkillIndex | None = index
        self._pinned = index is not None  # a test-supplied index never auto-refreshes
        self._last_check = 0.0
        self._version = PROTOCOL_VERSION
        self._pending_notices: list[dict[str, Any]] = []
        self.refresh_seconds = float(
            refresh_seconds if refresh_seconds is not None
            else os.environ.get("SKILLS_MCP_REFRESH_SECONDS", "5")
        )

    # -- index --------------------------------------------------------------

    @property
    def index(self) -> SkillIndex:
        if self._index is not None:
            return self._index
        try:
            self._index = get_index()
        except Exception as exc:
            raise ToolError("LIBRARY_UNAVAILABLE", f"could not build the skill index: {exc}",
                            hint="check that skills/ exists and is readable") from exc
        return self._index

    def maybe_refresh(self) -> None:
        """Reload when a book changed on disk — a stat sweep, throttled."""
        if self._pinned or self.refresh_seconds < 0:
            return
        now = time.time()
        if now - self._last_check < self.refresh_seconds:
            return
        self._last_check = now
        try:
            current = self._index or get_index()
            if not current.is_stale():
                return
            fresh = SkillIndex.build()
        except Exception as exc:
            log("warn", "index_refresh_failed", error=str(exc))
            return
        self._index = fresh
        METRICS.index_refreshes += 1
        old_uris = set()
        self._pending_notices.append({"jsonrpc": "2.0",
                                      "method": "notifications/resources/list_changed"})
        log("info", "index_refreshed", books=len(fresh.books))

    # -- tools --------------------------------------------------------------

    READ_ONLY = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}

    def tool_defs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "skills_list",
                "annotations": dict(self.READ_ONLY),
                "description": "Browse the Architect library: shelves first, then the books on them.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "shelf": {"type": "string", "description": "shelf path, empty for the root"},
                    },
                },
            },
            {
                "name": "skill_view",
                "annotations": dict(self.READ_ONLY),
                "description": "Read one or more books whole. Pass several names separated by commas.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"names": {"type": "string"}},
                    "required": ["names"],
                },
            },
            {
                "name": "skills_search",
                "annotations": dict(self.READ_ONLY),
                "description": "Ranked search over 220 architect books, with the reason for each hit.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "skill_bundle",
                "annotations": dict(self.READ_ONLY),
                "description": ("Planning-phase selection for a task: the domain crown plus the "
                                "best-matching books. Refused while executing."),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "phase": {"type": "string", "enum": ["planning", "executing"]},
                    },
                    "required": ["task"],
                },
            },
        ]

    def call_tool(self, name: str, args: dict[str, Any], meta: dict[str, Any] | None = None) -> dict:
        self.maybe_refresh()
        try:
            if name == "skills_list":
                return tool_text(self._skills_list(str(args.get("shelf") or "")))
            if name == "skill_view":
                return tool_text(self._skill_view(str(args.get("names") or "")))
            if name == "skills_search":
                return tool_text(self._search(str(args.get("query") or ""), args.get("limit")))
            if name == "skill_bundle":
                phase = str(args.get("phase") or (meta or {}).get("phase") or "planning")
                return tool_text(self._bundle(str(args.get("task") or ""), phase))
            raise ToolError("UNKNOWN_TOOL", f"no tool named {name!r}",
                            tools=[t["name"] for t in self.tool_defs()],
                            hint="call tools/list")
        except ToolError as err:
            METRICS.record_error(err.code)
            return tool_error(err)

    def _skills_list(self, shelf: str) -> str:
        shelf = shelf.strip().strip("/")
        if shelf and not self.index.exists(shelf):
            raise ToolError("UNKNOWN_SHELF", f"no shelf at {shelf!r}",
                            domains=self.index.domains(),
                            hint="call skills_list() with no argument")
        shelves, books = self.index.children_of(shelf)
        lines = []
        if books:
            lines.append(f"Books in {shelf}/" if shelf else "Root books:")
            lines.extend(f"- {b}" for b in books)
        if shelves:
            lines.append(f"Shelves in {shelf}/" if shelf else "Shelves:")
            lines.extend(f"- {s}/" for s in shelves)
        if not lines:
            raise ToolError("UNKNOWN_SHELF", f"{shelf!r} has no children")
        return "\n".join(lines)

    def _skill_view(self, names: str) -> str:
        wanted = [n for n in (names.replace(",", " ").split()) if n]
        if not wanted:
            raise ToolError("UNKNOWN_BOOK", "no book names given",
                            hint='skill_view("rest-architect, kafka-architect")')
        rendered, missing = [], []
        for name in wanted:
            book = self.index.get(name)
            if book is None:
                missing.append(name)
                continue
            header = [f"**{book.name}**", f"_{book.path}_",
                      f"origin: {book.origin}" + (f" · {book.sources}" if book.sources else "")]
            rendered.append("\n".join(header) + "\n\n" + book.body)
        if not rendered:
            suggestions = {m: self.index.suggestions(m) for m in missing}
            raise ToolError("UNKNOWN_BOOK", f"no book named {', '.join(missing)}",
                            close_matches=suggestions,
                            hint="browse with skills_list, or search with skills_search")
        out = "\n\n---\n\n".join(rendered)
        truncated, remaining = False, []
        if len(out) > MAX_VIEW_CHARS:
            out = out[:MAX_VIEW_CHARS]
            truncated = True
            remaining = [n for n in wanted if self.index.get(n) and n not in out[:MAX_VIEW_CHARS]]
        if truncated:
            out += ("\n\n[budget reached — ask for the rest with "
                    f"skill_view(\"{', '.join(remaining[:5]) or '…'}\")]")
        if missing:
            out += f"\n\nSkipped (not found): {', '.join(missing)}"
        return out

    def _search(self, query: str, limit: Any) -> dict[str, Any]:
        if not query.strip():
            raise ToolError("INTERNAL", "query is empty", hint="pass words from the task")
        try:
            n = max(1, min(int(limit or 10), MAX_SEARCH))
        except (TypeError, ValueError):
            n = 10
        hits = self.index.search(query, limit=n)
        return {"query": query, "count": len(hits), "hits": hits}

    def _bundle(self, task: str, phase: str) -> dict[str, Any]:
        if not task.strip():
            raise ToolError("INTERNAL", "task is empty")
        if phase != "planning":
            raise ToolError("PHASE_DENIED",
                            "architect skills are planning instruments, not execution tools",
                            phase=phase,
                            allowed=["skill_view (deliberate read)", "skills_list", "skills_search"],
                            hint="call skill_bundle while writing the plan, or open books directly")
        chosen = self.index.bundle(task)
        if not chosen:
            raise ToolError("UNKNOWN_BOOK", "no book matched this task",
                            hint="try skills_search with the technology name")
        payload: dict[str, Any] = {"task": task, "phase": phase, "books": chosen}
        if not phase:
            payload["phase_assumed"] = True
        return payload

    # -- resources ----------------------------------------------------------

    def resource_defs(self) -> list[dict[str, Any]]:
        """The *listing* stays small; books are addressed, not enumerated.

        The MCP spec is explicit that resources are application-driven and that
        parameterised content belongs in resource templates. Enumerating 240
        books here produced a 98 KB `resources/list` (~26 000 tokens) for a host
        that eagerly reads it — the library's whole premise, paid before a
        single question is asked. Domains plus templates keep it at ~1.5 KB and
        every book is still readable by URI.
        """
        return [
            {"uri": SCHEME + "catalog", "name": "Skill catalog",
             "description": "Domains, book counts and one-line descriptions.",
             "mimeType": "application/json"},
            {"uri": SCHEME + "health", "name": "Server health",
             "description": "Uptime, request counts, error counts by code, index state.",
             "mimeType": "application/json"},
            *[
                {"uri": SCHEME + d, "name": d,
                 "description": f"Domain {d}: "
                                f"{sum(1 for b in self.index.books.values() if b.domain == d)} books",
                 "mimeType": "text/markdown"}
                for d in self.index.domains()
            ],
        ]

    def resource_templates(self) -> list[dict[str, Any]]:
        """Where the corpus lives: three templates, no enumeration."""
        return [
            {"uriTemplate": SCHEME + "catalog", "name": "catalog",
             "description": "Every domain with its book count"},
            {"uriTemplate": SCHEME + "{domain}", "name": "domain",
             "description": "Shelves and books in one domain"},
            {"uriTemplate": SCHEME + "{domain}/{shelf}", "name": "shelf",
             "description": "Books on one shelf"},
            {"uriTemplate": SCHEME + "{domain}/{shelf}/{book}", "name": "book",
             "description": "One book, whole — the common case"},
        ]

    def read_resource(self, uri: str) -> dict[str, Any]:
        self.maybe_refresh()
        if not uri.startswith(SCHEME):
            raise ToolError("BAD_URI", f"expected a {SCHEME}… uri, got {uri!r}")
        path = uri[len(SCHEME):].strip("/")
        if path == "health":
            health = {"server": SERVER_INFO, "protocolVersion": PROTOCOL_VERSION,
                      "index": {"books": len(self.index.books), "skipped": len(self.index.skipped),
                                "builds": max(1, self.index.builds)},
                      "metrics": METRICS.snapshot()}
            return {"contents": [{"uri": uri, "mimeType": "application/json",
                                  "text": json.dumps(health, indent=1)}]}
        if path == "catalog":
            catalog = {
                "total": len(self.index.books),
                "architect": sum(1 for b in self.index.books.values() if b.is_architect),
                "standalone": self.index.standalone(),
                "domains": [
                    {"domain": d,
                     "books": sum(1 for b in self.index.books.values() if b.domain == d)}
                    for d in self.index.domains()
                ],
                "scheme": SCHEME,
                "skipped": self.index.skipped,
            }
            result: dict[str, Any] = {"contents": [{"uri": uri, "mimeType": "application/json",
                                                   "text": json.dumps(catalog, indent=1)}]}
            if self._version >= "2025-06-18":  # caching fields exist from here on
                result.update({"ttlMs": 60_000, "cacheScope": "public"})
            return result
        book = self.index.by_path.get(path)
        if book is not None:
            text = book.body[:MAX_RESOURCE_CHARS]
            return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text,
                                  "annotations": {"name": book.name, "origin": book.origin,
                                                  "description": book.description}}]}
        if self.index.exists(path):
            shelves, books = self.index.children_of(path)
            listing = [f"- {s}/" for s in shelves] + [f"- {b}" for b in books]
            return {"contents": [{"uri": uri, "mimeType": "text/markdown",
                                  "text": "\n".join(listing)}]}
        raise ToolError("BAD_URI", f"no node at {uri!r}",
                        domains=self.index.domains(),
                        hint="start at skill://catalog")

    # -- completion ---------------------------------------------------------

    def complete(self, params: dict[str, Any]) -> dict[str, Any]:
        """Argument auto-completion for the resource templates and prompts.

        Cheap here because the index is in memory: a host can offer real book and
        shelf names instead of making the model guess a path.
        """
        ref = params.get("ref") or {}
        argument = params.get("argument") or {}
        name = str(argument.get("name") or "")
        value = str(argument.get("value") or "").lower()
        uri = str(ref.get("uri") or "")

        if ref.get("type") == "ref/prompt":
            values = ["plan_with_skills"]
        elif name in ("book", "name"):
            values = [b.name for b in self.index.books.values()]
        elif name == "domain":
            values = list(self.index.domains())
        elif name in ("shelf", "path"):
            values = list(self.index.domains())
            for d in self.index.domains():
                shelves, _ = self.index.children_of(d)
                values.extend(f"{d}/{s}" for s in shelves)
        else:
            # infer from the uri the client is completing
            parts = uri[len(SCHEME):].strip("/").split("/") if uri.startswith(SCHEME) else []
            if len(parts) <= 1:
                values = self.index.domains()
            elif len(parts) == 2:
                shelves, _ = self.index.children_of(parts[0])
                values = [f"{parts[0]}/{s}" for s in shelves]
            else:
                _shelves, books = self.index.children_of("/".join(parts[:2]))
                values = books
        values = [v for v in values if value in v.lower()]
        return {"completion": {"values": sorted(values)[:100],
                               "total": len(values), "hasMore": len(values) > 100}}

    # -- prompts ------------------------------------------------------------

    def prompt_defs(self) -> list[dict[str, Any]]:
        return [{
            "name": "plan_with_skills",
            "description": "Plan a task with the architect books for its domain.",
            "arguments": [{"name": "task", "required": True}],
        }]

    def get_prompt(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        task = str(args.get("task") or "")
        if name != "plan_with_skills":
            raise ToolError("INTERNAL", f"unknown prompt {name!r}",
                            prompts=[p["name"] for p in self.prompt_defs()])
        chosen = self.index.bundle(task) if task else []
        names = [c["name"] for c in chosen]
        text = [
            "You are planning: " + (task or "(no task given)"),
            "",
            "Read these books whole before writing the plan, and add any others you need:",
            *[f"- {c['name']} — {c['reason']}" for c in chosen],
        ]
        return {
            "description": f"Plan with {', '.join(names) or 'the library'}",
            "messages": [{
                "role": "user",
                "content": {"type": "text", "text": "\n".join(text)},
            }],
        }

    # -- protocol -----------------------------------------------------------

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        params = message.get("params") or {}
        msg_id = message.get("id")
        if msg_id is None and method and method.startswith("notifications/"):
            return None

        def ok(result: Any) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}

        def fail(code: int, msg: str) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": msg}}

        start = time.time()
        while_serving = True
        try:
            if method == "initialize":
                asked = str(params.get("protocolVersion") or "")
                agreed = asked if asked in SUPPORTED_VERSIONS else PROTOCOL_VERSION
                self._version = agreed
                log("info", "initialize", client_version=asked or None, agreed=agreed)
                return ok({
                    "protocolVersion": agreed,
                    "capabilities": {"tools": {}, "resources": {"listChanged": True},
                                     "prompts": {}, "completions": {}},
                    "serverInfo": SERVER_INFO,
                    "instructions": ("Architect skill library. Planning phase: call "
                                     "skill_bundle(task) once, or read the injected books. "
                                     "Execution phase: open books deliberately with skill_view."),
                })
            if method == "completion/complete":
                return ok(self.complete(params))
            if method == "ping":
                return ok({})
            if method == "tools/list":
                return ok({"tools": self.tool_defs()})
            if method == "tools/call":
                tool_name = str(params.get("name") or "")
                METRICS.tools[tool_name] += 1
                return ok(self.call_tool(tool_name, params.get("arguments") or {},
                                         params.get("_meta") or {}))
            if method == "resources/list":
                return ok({"resources": self.resource_defs()})
            if method == "resources/templates/list":
                return ok({"resourceTemplates": self.resource_templates()})
            if method == "resources/read":
                uri = str(params.get("uri") or "")
                METRICS.resources[uri.split("/")[2] if uri.count("/") > 2 else uri] += 1
                return ok(self.read_resource(uri))
            if method == "prompts/list":
                return ok({"prompts": self.prompt_defs()})
            if method == "prompts/get":
                return ok(self.get_prompt(str(params.get("name") or ""), params.get("arguments") or {}))
            if method in ("shutdown", "exit"):
                return ok({})
            return fail(-32601, f"method not found: {method}")
        except ToolError as err:
            METRICS.record_error(err.code)
            return fail(-32000, json.dumps(err.payload()))
        except Exception:  # pragma: no cover - last resort
            cid = uuid.uuid4().hex[:8]
            print(traceback.format_exc(), file=sys.stderr)
            METRICS.record_error("INTERNAL")
            log("error", "internal_error", correlation_id=cid, method=method)
            return fail(-32603, json.dumps({"code": "INTERNAL", "message": "unexpected error",
                                            "correlation_id": cid}))
        finally:
            METRICS.requests += 1
            elapsed = (time.time() - start) * 1000
            if elapsed > 500:
                log("warn", "slow_request", method=method, ms=round(elapsed, 1))

    def drain_notices(self) -> list[dict[str, Any]]:
        notices, self._pending_notices = self._pending_notices, []
        return notices

    def serve(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                METRICS.record_error("PARSE_ERROR")
                print(json.dumps({"jsonrpc": "2.0", "id": None,
                                  "error": {"code": -32700, "message": "parse error"}}), flush=True)
                continue
            response = self.handle(message)
            if response is not None:
                print(json.dumps(response), flush=True)
            for notice in self.drain_notices():
                print(json.dumps(notice), flush=True)


def main() -> None:  # pragma: no cover - process entry point
    SkillMCPServer().serve()
