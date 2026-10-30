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
import sys
import traceback
import uuid
from typing import Any

from src.mcp_skills.index import SCHEME, SkillIndex, get_index

PROTOCOL_VERSION = "2024-11-05"
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
    def __init__(self, index: SkillIndex | None = None):
        self._index_override = index
        self._index: SkillIndex | None = index

    # -- index --------------------------------------------------------------

    @property
    def index(self) -> SkillIndex:
        if self._index is not None:
            return self._index
        try:
            self._index = self._index_override or get_index()
        except Exception as exc:  # pragma: no cover - defensive
            raise ToolError("LIBRARY_UNAVAILABLE", f"could not build skill index: {exc}") from exc
        return self._index

    # -- tools --------------------------------------------------------------

    def tool_defs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "skills_list",
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
                "description": "Read one or more books whole. Pass several names separated by commas.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"names": {"type": "string"}},
                    "required": ["names"],
                },
            },
            {
                "name": "skills_search",
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
            raise ToolError("INTERNAL", f"unknown tool {name!r}", tools=[t["name"] for t in self.tool_defs()])
        except ToolError as err:
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
        return [
            {"uri": SCHEME + "catalog", "name": "Skill catalog",
             "description": "Domains, book counts and one-line descriptions.",
             "mimeType": "application/json"},
            *[
                {"uri": SCHEME + d, "name": d,
                 "description": f"Domain {d}", "mimeType": "text/markdown"}
                for d in self.index.domains()
            ],
            *[
                {"uri": b.uri, "name": b.name, "description": b.description[:180],
                 "mimeType": "text/markdown",
                 "annotations": {"origin": b.origin, "verified_on": b.verified_on}}
                for b in sorted(self.index.books.values(), key=lambda x: x.name)
            ],
        ]

    def resource_templates(self) -> list[dict[str, Any]]:
        return [
            {"uriTemplate": SCHEME + "{domain}", "name": "domain",
             "description": "Books and shelves in one domain"},
            {"uriTemplate": SCHEME + "{domain}/{shelf}", "name": "shelf",
             "description": "Books on one shelf"},
            {"uriTemplate": SCHEME + "{domain}/{shelf}/{book}", "name": "book",
             "description": "One book, whole"},
        ]

    def read_resource(self, uri: str) -> dict[str, Any]:
        if not uri.startswith(SCHEME):
            raise ToolError("BAD_URI", f"expected a {SCHEME}… uri, got {uri!r}")
        path = uri[len(SCHEME):].strip("/")
        if path == "catalog":
            catalog = {
                "total": len(self.index.books),
                "domains": [
                    {"domain": d,
                     "books": sum(1 for b in self.index.books.values() if b.domain == d)}
                    for d in self.index.domains()
                ],
                "scheme": SCHEME,
                "skipped": self.index.skipped,
            }
            return {"contents": [{"uri": uri, "mimeType": "application/json",
                                  "text": json.dumps(catalog, indent=1)}]}
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

        try:
            if method == "initialize":
                return ok({
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "serverInfo": SERVER_INFO,
                })
            if method == "ping":
                return ok({})
            if method == "tools/list":
                return ok({"tools": self.tool_defs()})
            if method == "tools/call":
                return ok(self.call_tool(str(params.get("name") or ""),
                                         params.get("arguments") or {},
                                         params.get("_meta") or {}))
            if method == "resources/list":
                return ok({"resources": self.resource_defs()})
            if method == "resources/templates/list":
                return ok({"resourceTemplates": self.resource_templates()})
            if method == "resources/read":
                return ok(self.read_resource(str(params.get("uri") or "")))
            if method == "prompts/list":
                return ok({"prompts": self.prompt_defs()})
            if method == "prompts/get":
                return ok(self.get_prompt(str(params.get("name") or ""), params.get("arguments") or {}))
            if method in ("shutdown", "exit"):
                return ok({})
            return fail(-32601, f"method not found: {method}")
        except ToolError as err:
            return fail(-32000, json.dumps(err.payload()))
        except Exception:  # pragma: no cover - last resort
            cid = uuid.uuid4().hex[:8]
            print(traceback.format_exc(), file=sys.stderr)
            return fail(-32603, json.dumps({"code": "INTERNAL", "message": "unexpected error",
                                            "correlation_id": cid}))

    def serve(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                print(json.dumps({"jsonrpc": "2.0", "id": None,
                                  "error": {"code": -32700, "message": "parse error"}}), flush=True)
                continue
            response = self.handle(message)
            if response is not None:
                print(json.dumps(response), flush=True)


def main() -> None:  # pragma: no cover - process entry point
    SkillMCPServer().serve()
