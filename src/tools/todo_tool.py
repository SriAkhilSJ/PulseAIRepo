"""``todo_list`` -- hermes' task tool, ported from ``tools/todo_tool.py``.

Upstream shape (owned by the source, not re-invented): in-memory, revisioned
task list for multi-step work. State lives per session (upstream: on the
AIAgent; here: keyed by thread_id), is re-injected into the model context so
the list survives context trimming, and every write bumps a monotonic revision
so UI clients can reject stale updates. ONE tool: pass ``todos`` to write
(replace, or ``merge=true`` to patch by id), omit to read; every call returns
the full list + revision + counts. Behavioral guidance lives entirely in the
tool schema description -- no prompt layer, no classifier.

The UI event (``todo.updated``) rides the same event bus the bridge already
projects, so the desktop panel reconciles atomically on ``{todos, revision}``.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
# The list is re-read after every context trim (format_for_injection), so
# unbounded content/count would defeat the compression it rides through.
MAX_TODO_CONTENT_CHARS = 4000
MAX_TODO_ITEMS = 256
_TRUNCATION_MARKER = "… [truncated]"
# Persisted as ordinary message content; the injection row carries this stable
# header so the model never mistakes it for a real user message (upstream
# TODO_INJECTION_HEADER).
TODO_INJECTION_HEADER = "[Your active task list was preserved across context compression]"
_STATUS_MARKERS = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]", "cancelled": "[~]"}
_ACTIVE_STATUSES = {"pending", "in_progress"}


class TodoStore:
    """In-memory todo list, one per session. List position is priority; items
    are ``{id, content, status, parent?}`` -- ``parent`` nests a subtask."""

    def __init__(self):
        self._items: list[dict[str, str]] = []
        self._revision = 0
        self._lock = threading.RLock()

    def _fresh_items(self, todos: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Validate, dedupe and order a whole new list (replace / restore)."""
        return self._normalize_order([self._validate(t) for t in self._dedupe_by_id(todos)])

    def write(self, todos: list[dict[str, Any]], merge: bool = False) -> list[dict[str, str]]:
        """Replace the list (default) or merge by id; returns the full list after writing."""
        with self._lock:
            before = self.read()
            if merge:
                self._merge(todos)
            else:
                self._items = self._fresh_items(todos)
            del self._items[MAX_TODO_ITEMS:]  # keep the priority head; replays can't grow unbounded
            self._sanitize_parents(self._items)
            if self._items != before:
                self._revision += 1
            return self.read()

    def _merge(self, todos: list[dict[str, Any]]) -> None:
        """Update existing items only in the fields provided; append new ones (validated)."""
        existing = {item["id"]: item for item in self._items}
        for t in self._dedupe_by_id(todos):
            item_id = str(t.get("id", "")).strip()
            if not item_id:
                continue  # can't merge without an id
            cur = existing.get(item_id)
            if cur is None:
                validated = self._validate(t)
                existing[validated["id"]] = validated
                self._items.append(validated)
                continue
            if t.get("content"):
                cur["content"] = self._cap_content(str(t["content"]).strip())
            if t.get("status") and str(t.get("status")).strip().lower() in VALID_STATUSES:
                cur["status"] = str(t["status"]).strip().lower()
            if "parent" in t:
                parent = str(t.get("parent") or "").strip()
                if parent:
                    cur["parent"] = parent
                else:
                    cur.pop("parent", None)
        # Rebuild preserving original order for existing items (first occurrence wins).
        rebuilt = {item["id"]: existing.get(item["id"], item) for item in self._items}
        self._items = self._normalize_order(list(rebuilt.values()))

    def read(self) -> list[dict[str, str]]:
        return [item.copy() for item in self._items]

    def has_items(self) -> bool:
        return bool(self._items)

    def snapshot(self) -> dict[str, Any]:
        """Full state clients can reconcile atomically."""
        return {"todos": self.read(), "revision": self._revision}

    def restore(self, todos: list[dict[str, Any]], *, revision: Any = 0) -> list[dict[str, str]]:
        """Restore a trusted snapshot without manufacturing a new revision."""
        with self._lock:
            self._items = self._fresh_items(todos)[:MAX_TODO_ITEMS]
            try:
                self._revision = max(0, int(revision or 0))
            except (TypeError, ValueError):
                self._revision = 0
            return self.read()

    def format_for_injection(self) -> str | None:
        """Render the list for post-compression injection, or None if nothing active.
        Only pending/in_progress items are injected -- finished ones make the model
        re-do work after compression. A parent is kept (with its real status marker)
        when any descendant is active so subtasks keep context."""
        with self._lock:
            if not self._items:
                return None
            children: dict[str, list[dict[str, str]]] = {}
            for item in self._items:
                if item.get("parent"):
                    children.setdefault(item["parent"], []).append(item)

            def render(item: dict[str, str], depth: int, out: list[str]) -> bool:
                kid_lines: list[str] = []
                has_active_kid = False
                for kid in children.get(item["id"], []):
                    has_active_kid |= render(kid, depth + 1, kid_lines)
                keep = item["status"] in _ACTIVE_STATUSES or has_active_kid
                if keep:
                    marker = _STATUS_MARKERS.get(item["status"], "[?]")
                    out.append(
                        f"{'  ' * depth}- {marker} {item['id']}. "
                        f"{item['content']} ({item['status']})"
                    )
                    out.extend(kid_lines)
                return keep

            lines = [TODO_INJECTION_HEADER]
            for item in self._items:
                if not item.get("parent"):
                    render(item, 0, lines)
            return "\n".join(lines) if len(lines) > 1 else None

    @staticmethod
    def _cap_content(content: str) -> str:
        """Truncate to MAX_TODO_CONTENT_CHARS keeping the head (the actionable part) + marker."""
        if len(content) > MAX_TODO_CONTENT_CHARS:
            return content[: MAX_TODO_CONTENT_CHARS - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER
        return content

    @staticmethod
    def _validate(item: dict[str, Any]) -> dict[str, str]:
        """Normalize one item to ``{id, content, status, parent?}`` (placeholders when missing)."""
        if not isinstance(item, dict):
            return {"id": "?", "content": "(invalid item)", "status": "pending"}
        item_id = str(item.get("id", "")).strip() or "?"
        content = str(item.get("content", "")).strip()
        status = str(item.get("status", "pending")).strip().lower()
        result = {
            "id": item_id,
            "content": TodoStore._cap_content(content) if content else "(no description)",
            "status": status if status in VALID_STATUSES else "pending",
        }
        parent = str(item.get("parent") or "").strip()
        if parent and parent != item_id:
            result["parent"] = parent
        return result

    @staticmethod
    def _sanitize_parents(items: list[dict[str, str]]) -> None:
        """Drop dangling parent refs and break cycles in place (such items become roots)."""
        by_id = {item["id"]: item for item in items}
        for item in items:
            if item.get("parent") and item["parent"] not in by_id:
                item.pop("parent", None)
        for item in items:
            seen, node = {item["id"]}, item
            while node.get("parent"):
                if node["parent"] in seen:
                    item.pop("parent", None)
                    break
                seen.add(node["parent"])
                node = by_id[node["parent"]]

    @staticmethod
    def _dedupe_by_id(todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse duplicate ids, keeping the last occurrence in its position."""
        last_index: dict[str, int] = {}
        for i, item in enumerate(todos):  # non-dicts get a synthetic key; _validate handles them
            key = str(item.get("id", "")).strip() if isinstance(item, dict) else f"__invalid_{i}"
            last_index[key or "?"] = i
        return [todos[i] for i in sorted(last_index.values())]

    @staticmethod
    def _normalize_order(items: list[dict[str, str]]) -> list[dict[str, str]]:
        """Lift the in_progress step ahead of any earlier pending placeholder. Nested lists
        keep authored order -- reordering would tear a subtask from its siblings."""
        statuses = [item["status"] for item in items]
        if any(item.get("parent") for item in items) or "in_progress" not in statuses:
            return items
        active_index = statuses.index("in_progress")
        if "pending" not in statuses[:active_index]:
            return items
        normalized = items.copy()
        normalized.insert(statuses.index("pending"), normalized.pop(active_index))
        return normalized


class TodoStoreRegistry:
    """Session-keyed TodoStores (upstream keeps one store on each AIAgent; our
    sessions are graph threads). Tools and the injection path share this."""

    def __init__(self):
        self._stores: dict[str, TodoStore] = {}
        self._lock = threading.RLock()

    def for_session(self, session_id: str) -> TodoStore:
        key = str(session_id or "default")
        with self._lock:
            store = self._stores.get(key)
            if store is None:
                store = TodoStore()
                self._stores[key] = store
            return store

    def clear(self, session_id: str | None = None) -> None:
        with self._lock:
            if session_id is None:
                self._stores.clear()
            else:
                self._stores.pop(str(session_id), None)


todo_stores = TodoStoreRegistry()


def todo_tool(
    todos: list[dict[str, Any]] | None = None, merge: bool = False,
    store: TodoStore | None = None, session_id: str = "default",
) -> str:
    """Write ``todos`` (replace, or ``merge`` by id) or read when None -> list + summary JSON."""
    if store is None:
        if session_id is None:
            return json.dumps({"error": "TodoStore not initialized"}, ensure_ascii=False)
        store = todo_stores.for_session(session_id)
    if todos is None:
        items = store.read()
    else:
        if isinstance(todos, str):  # LLMs sometimes send a JSON string instead of a list
            try:
                todos = json.loads(todos)
            except (json.JSONDecodeError, TypeError):
                return json.dumps({"error": "todos must be a list of objects, got unparseable string"}, ensure_ascii=False)
        if not isinstance(todos, list):
            return json.dumps({"error": f"todos must be a list, got {type(todos).__name__}"}, ensure_ascii=False)
        items = store.write(todos, merge)
    summary = {"total": len(items)}
    for status in ("pending", "in_progress", "completed", "cancelled"):
        summary[status] = sum(1 for i in items if i["status"] == status)
    return json.dumps(
        {"todos": items, "revision": store.snapshot()["revision"], "summary": summary},
        ensure_ascii=False,
    )


@tool
def todo_list(
    todos: list[dict[str, Any]] | None = None,
    merge: bool = False,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """Track a task list for multi-step work (3+ steps). Use for complex tasks with 3+ steps or when the user provides multiple tasks. For 'all N items' tasks, enumerate every instance as its own checklist item so none are silently dropped. Call with no parameters to read the current list.
List order is priority. Only ONE item in_progress at a time. Break large phases into subtasks via parent. Mark an item completed only after the work is verified done, never based on intent. If something fails, cancel it and add a revised item. Always returns the full current list."""
    session_id = "default"
    try:
        session_id = str((config or {}).get("configurable", {}).get("thread_id") or "default")
    except Exception:
        pass
    result = todo_tool(todos=todos, merge=merge, session_id=session_id)
    try:
        payload = json.loads(result)
    except Exception:
        return result
    if "error" in payload:
        return result
    # UI event: the desktop panel reconciles atomically on {todos, revision}
    # (upstream desktop feeds the same two fields from live tool events).
    try:
        from src.dashboard.event_bus import event_bus
        event_bus.emit("todo.updated", {
            "session_id": session_id,
            "todos": payload.get("todos", []),
            "revision": payload.get("revision", 0),
            "summary": payload.get("summary", {}),
        })
    except Exception:
        pass  # the tool result stands on its own; UI events never break the tool
    return result


def inject_active_todos(session_id: str) -> str | None:
    """The re-injection half of the pipeline: the session's active list, or None."""
    try:
        return todo_stores.for_session(session_id).format_for_injection()
    except Exception:
        return None  # a broken todo store must never break the request


def clear_todo_store(session_id: str) -> None:
    """Turn teardown: hermes clears the pinned list at turn end (the desktop
    "turn-end clear"); an active list must not resurrect on the next turn."""
    todo_stores.clear(session_id)


__all__ = [
    "TodoStore", "TodoStoreRegistry", "todo_stores", "todo_tool", "todo_list",
    "inject_active_todos", "clear_todo_store", "TODO_INJECTION_HEADER",
    "VALID_STATUSES", "MAX_TODO_ITEMS", "MAX_TODO_CONTENT_CHARS",
]
