"""In-memory index of the Architect library.

Built once (~40 ms for 220 books) from `SkillManager`, then every fetch is a dict
lookup — no filesystem walk per request, no second parser, no manifest to drift.

Mapping rule: a skill directory is a node. `skills/<domain>/<shelf>/<book>/SKILL.md`
becomes `skill://<domain>/<shelf>/<book>`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEME = "skill://"
DOMAIN_SUFFIX = "-architect"


@dataclass(frozen=True)
class Book:
    """One skill, as the MCP layer sees it."""

    name: str
    path: str  # e.g. desktop-architect/platform-architect/desktop-ipc-architect
    body: str
    description: str = ""
    triggers: tuple[str, ...] = ()
    origin: str = "original"
    sources: str = ""
    verified_on: str = ""

    @property
    def shelf(self) -> str:
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""

    @property
    def domain(self) -> str:
        return self.path.split("/", 1)[0]

    @property
    def is_architect(self) -> bool:
        """Architect books live under a `<domain>-architect/` root and are gated by phase."""
        return self.domain.endswith(DOMAIN_SUFFIX)

    @property
    def uri(self) -> str:
        return SCHEME + self.path


@dataclass
class SkillIndex:
    """Books keyed by name, plus the tree they hang on."""

    books: dict[str, Book] = field(default_factory=dict)
    by_path: dict[str, Book] = field(default_factory=dict)
    skipped: list[dict[str, str]] = field(default_factory=list)

    # -- construction -------------------------------------------------------

    @classmethod
    def build(cls) -> "SkillIndex":
        from src.agents.skill_manager import SkillManager

        index = cls()
        manager = SkillManager()
        for skill in manager.list_skills():
            name = str(skill.get("name") or "")
            path = str(skill.get("path") or "")
            if not name or not path:
                index.skipped.append({"path": path, "reason": "missing name or path"})
                continue
            book = Book(
                name=name,
                path=path,
                body=str(skill.get("instruction") or ""),
                description=str(skill.get("description") or ""),
                triggers=tuple(skill.get("triggers") or ()),
                origin=str((skill.get("metadata") or {}).get("crusor-origin") or "original"),
                sources=str((skill.get("metadata") or {}).get("crusor-sources") or ""),
                verified_on=str((skill.get("metadata") or {}).get("crusor-verified-on") or ""),
            )
            if not book.body:
                index.skipped.append({"path": path, "reason": "empty body"})
                continue
            index.books[name] = book
            index.by_path[path] = book
        return index

    # -- tree ---------------------------------------------------------------

    def domains(self) -> list[str]:
        return sorted({b.domain for b in self.books.values()})

    def children_of(self, path: str) -> tuple[list[str], list[str]]:
        """(sub-shelves, books) directly or indirectly below `path`."""
        path = path.strip("/")
        prefix = path + "/" if path else ""
        shelves: set[str] = set()
        books: list[str] = []
        for book in self.books.values():
            if not book.path.startswith(prefix):
                continue
            rest = book.path[len(prefix):]
            if "/" in rest:
                shelves.add(rest.split("/", 1)[0])
            else:
                books.append(book.name)
        return sorted(shelves), sorted(books)

    def exists(self, path: str) -> bool:
        path = path.strip("/")
        if path in self.by_path:
            return True
        prefix = path + "/"
        return any(b.path.startswith(prefix) for b in self.books.values())

    # -- fetch --------------------------------------------------------------

    def get(self, name: str) -> Book | None:
        return self.books.get(name.strip())

    def suggestions(self, name: str, limit: int = 5) -> list[str]:
        """Close matches by token overlap — used by UNKNOWN_BOOK responses."""
        tokens = {t for t in re.split(r"[-_/]", name.lower()) if len(t) > 2}
        if not tokens:
            return []
        scored = []
        for book in self.books.values():
            hay = {t for t in re.split(r"[-_/]", book.name.lower()) if t}
            overlap = len(tokens & hay)
            if overlap:
                scored.append((overlap, book.name))
        return [n for _, n in sorted(scored, key=lambda x: (-x[0], x[1]))[:limit]]

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        words = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if len(w) > 2]
        if not words:
            return []
        hits = []
        for book in self.books.values():
            triggers = " , ".join(book.triggers).lower()
            name = book.name.lower()
            desc = book.description.lower()
            matched = []
            score = 0.0
            for word in set(words):
                if re.search(r"\b%s\b" % re.escape(word), triggers):
                    score += 3.0
                    matched.append(word)
                if word in name:
                    score += 2.0
                    matched.append(word)
                if re.search(r"\b%s\b" % re.escape(word), desc):
                    score += 1.0
                    matched.append(word)
            if score:
                hits.append(
                    {
                        "name": book.name,
                        "shelf": book.shelf,
                        "score": round(score, 1),
                        "why_matched": "matched: " + ", ".join(sorted(set(matched))[:6]),
                    }
                )
        return sorted(hits, key=lambda h: (-h["score"], h["name"]))[:limit]

    def bundle(self, task: str, limit: int = 3) -> list[dict[str, Any]]:
        """Planning selection: the domain crown plus the best-matching leaves."""
        hits = self.search(task, limit=limit * 4)
        chosen: list[dict[str, Any]] = []
        if hits:
            domain = self.books[hits[0]["name"]].domain
            crown = self.books.get(domain)
            if crown:
                chosen.append({"name": crown.name, "reason": "crown of the matching domain"})
        for hit in hits:
            if len(chosen) >= limit:
                break
            if any(c["name"] == hit["name"] for c in chosen):
                continue
            chosen.append({"name": hit["name"], "reason": hit["why_matched"]})
        if not chosen:
            return []
        return chosen

    def roots(self) -> Path:
        return Path(__file__).resolve().parents[2] / "skills"


_INDEX: SkillIndex | None = None


def get_index(refresh: bool = False) -> SkillIndex:
    global _INDEX
    if _INDEX is None or refresh:
        _INDEX = SkillIndex.build()
    return _INDEX
