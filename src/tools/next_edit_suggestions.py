"""Next Edit Suggestions (NES) — predict WHERE the user should edit next.

Inspired by Copilot's NES feature. After a user makes a change, this
module analyzes the codebase to suggest the next likely edit locations.

Uses heuristics + code analysis to predict patterns like:
- After renaming a function, suggest updating its callers
- After adding an import, suggest using the imported symbol
- After modifying a function signature, suggest updating call sites
- After adding a test, suggest running the tests
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class NESuggestion:
    """A suggested next edit location."""
    resource: str
    line: int
    column: int
    end_line: int
    end_column: int
    title: str
    description: str
    confidence: float
    category: str  # 'rename', 'import', 'signature', 'test', 'callers', 'docs'


class NextEditPredictor:
    """Predicts the next likely edit locations based on recent changes."""

    def __init__(self):
        self._lock = threading.Lock()
        self._recent_changes: list[dict] = []
        self._max_recent = 50
        self._enabled = os.environ.get("PULSEAI_NEXT_EDIT_SUGGESTIONS", "1").strip().lower() in {
            "1", "true", "yes", "on",
        }
        # Common patterns that suggest follow-up edits
        self._patterns: list[tuple[str, str, float]] = [
            (r"(?:def|function|func)\s+(\w+)", "callers", 0.7),
            (r"(?:class)\s+(\w+)", "instantiations", 0.6),
            (r"import\s+(?:\w+\.)?(\w+)", "usage", 0.5),
            (r"(?:def|function|func)\s+\w+\s*\(([^)]+)\)", "signature_update", 0.65),
            (r"(?:class)\s+\w+\s*(?:\(|:)", "inheritors", 0.5),
        ]

    @property
    def enabled(self) -> bool:
        return self._enabled

    def record_change(self, resource: str, line: int, column: int,
                      old_text: str, new_text: str, workspace: str = "") -> None:
        """Record a recent file change for prediction context."""
        if not self._enabled:
            return
        with self._lock:
            self._recent_changes.append({
                "resource": resource,
                "line": line,
                "column": column,
                "old_text": old_text,
                "new_text": new_text,
                "workspace": workspace,
                "timestamp": __import__("time").time(),
            })
            if len(self._recent_changes) > self._max_recent:
                self._recent_changes = self._recent_changes[-self._max_recent:]

    def predict_next_edits(self, workspace: str, max_suggestions: int = 5) -> list[NESuggestion]:
        """Predict likely next edit locations based on recent changes."""
        if not self._enabled:
            return []

        with self._lock:
            recent = list(self._recent_changes)

        if not recent:
            return []

        suggestions: list[NESuggestion] = []

        for change in recent[-5:]:  # Look at last 5 changes
            suggestions.extend(self._analyze_change(change, workspace))

        # Deduplicate and sort by confidence
        seen = set()
        unique: list[NESuggestion] = []
        for s in sorted(suggestions, key=lambda x: x.confidence, reverse=True):
            key = f"{s.resource}:{s.line}:{s.column}"
            if key not in seen:
                seen.add(key)
                unique.append(s)

        return unique[:max_suggestions]

    def _analyze_change(self, change: dict, workspace: str) -> list[NESuggestion]:
        """Analyze a single change to predict follow-up edits."""
        suggestions: list[NESuggestion] = []
        new_text = change.get("new_text", "")
        old_text = change.get("old_text", "")
        resource = change.get("resource", "")

        # Pattern 1: Renamed identifier -> suggest updating callers
        rename_match = re.search(r"(?:def|function|func|class)\s+(\w+)", new_text)
        if rename_match:
            old_name_match = re.search(r"(?:def|function|func|class)\s+(\w+)", old_text)
            if old_name_match and rename_match.group(1) != old_name_match.group(1):
                suggestions.append(NESuggestion(
                    resource=resource,
                    line=change["line"],
                    column=change["column"],
                    end_line=change["line"] + len(new_text.split("\n")),
                    end_column=0,
                    title=f"Update callers of '{old_name_match.group(1)}'",
                    description=f"Function renamed from '{old_name_match.group(1)}' to '{rename_match.group(1)}'",
                    confidence=0.85,
                    category="rename",
                ))

        # Pattern 2: New import -> suggest using the imported symbol
        import_match = re.search(r"import\s+(?:\w+\.)?(\w+)", new_text)
        if import_match and not re.search(r"import\s+(?:\w+\.)?(\w+)", old_text):
            symbol = import_match.group(1)
            suggestions.append(NESuggestion(
                resource=resource,
                line=change["line"] + 1,
                column=0,
                end_line=change["line"] + 2,
                end_column=0,
                title=f"Use imported '{symbol}'",
                description=f"New import of '{symbol}' — consider using it in this file",
                confidence=0.5,
                category="import",
            ))

        # Pattern 3: Modified function signature -> suggest updating call sites
        sig_match = re.search(r"def\s+\w+\s*\(([^)]+)\)", new_text)
        if sig_match:
            old_sig = re.search(r"def\s+\w+\s*\(([^)]+)\)", old_text)
            if old_sig and sig_match.group(1) != old_sig.group(1):
                func_match = re.search(r"def\s+(\w+)", new_text)
                func_name = func_match.group(1) if func_match else "function"
                suggestions.append(NESuggestion(
                    resource=resource,
                    line=change["line"],
                    column=change["column"],
                    end_line=change["line"],
                    end_column=0,
                    title=f"Update call sites of '{func_name}'",
                    description=f"Signature changed for '{func_name}' — callers may need updating",
                    confidence=0.7,
                    category="signature",
                ))

        # Pattern 4: New function/class definition -> suggest adding tests
        if re.search(r"(?:def|function|func)\s+\w+", new_text) and not re.search(r"(?:def|function|func)\s+\w+", old_text):
            suggestions.append(NESuggestion(
                resource=resource,
                line=change["line"],
                column=change["column"],
                end_line=change["line"],
                end_column=0,
                title="Add tests for new function",
                description="New function defined — consider adding unit tests",
                confidence=0.4,
                category="test",
            ))

        # Pattern 5: New class definition -> suggest adding tests and docs
        if re.search(r"class\s+\w+", new_text) and not re.search(r"class\s+\w+", old_text):
            suggestions.append(NESuggestion(
                resource=resource,
                line=change["line"],
                column=change["column"],
                end_line=change["line"],
                end_column=0,
                title="Add tests and docs for new class",
                description="New class defined — consider adding tests and documentation",
                confidence=0.45,
                category="test",
            ))

        return suggestions


# Singleton
_next_edit_predictor: NextEditPredictor | None = None
_next_edit_lock = threading.Lock()


def get_next_edit_predictor() -> NextEditPredictor:
    global _next_edit_predictor
    if _next_edit_predictor is None:
        with _next_edit_lock:
            if _next_edit_predictor is None:
                _next_edit_predictor = NextEditPredictor()
    return _next_edit_predictor
