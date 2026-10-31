"""
read_cache.py - Content-Addressed Read Cache with Context Residency Awareness.

Pillar 1 of the Hardened Production Architecture.
Distinguishes physical disk caching from active LLM context residency:
- Physical disk hash unchanged + present in active context -> Reference receipt (cache hit).
- Physical disk hash changed or context evicted -> Re-hydrate full content into turn.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from src.runtime.run_state_ledger import AgentRunState


class HardenedReadCache:
    """Read cache that distinguishes physical disk caching from model context residency."""

    def __init__(self, run_state: Optional[AgentRunState] = None):
        self.state = run_state
        self._disk_hashes: dict[str, str] = {}

    def execute_read(
        self,
        file_path: Path | str,
        active_prompt_text: str = "",
        force_fresh: bool = False,
    ) -> Tuple[str, bool]:
        """Read a file with context-residency awareness.

        Returns (content_or_receipt, is_resident_hit).
        """
        p = Path(file_path).resolve()
        resolved = str(p)

        if not p.exists():
            return f"Error: File '{file_path}' not found.", False

        if p.is_dir():
            return f"Error: '{file_path}' is a directory, not a file.", False

        try:
            content_bytes = p.read_bytes()
        except Exception as exc:
            return f"Error reading '{file_path}': {exc}", False

        current_hash = hashlib.sha256(content_bytes).hexdigest()
        self._disk_hashes[resolved] = current_hash

        # Context residency verification
        is_resident = False
        if not force_fresh and self.state is not None:
            is_resident = self.state.is_file_resident(
                resolved, current_hash, active_prompt_text=active_prompt_text
            )

        if is_resident:
            # Safe to return lightweight reference receipt
            receipt = (
                f"[CONTENT RESIDENT]: '{p.name}' is already resident in your active context "
                f"(SHA-256: {current_hash[:8]}). Reference resident lines or specify line range offsets."
            )
            return receipt, True

        # Context miss or file mutated: mark resident and inject full text
        if self.state is not None:
            self.state.update_file_residency(resolved, current_hash)

        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = content_bytes.decode("latin-1", errors="replace")

        return text, False
