"""
read_cache.py - Content-Addressed Read Cache with Context Residency Awareness.

Pillar 1 of the Hardened Production Architecture.
Distinguishes physical disk caching from active LLM context residency:
- Physical disk hash unchanged + present in active context -> Reference receipt (cache hit).
- Physical disk hash changed or context evicted -> Re-hydrate content into turn.
Supports single-pass binary read and precise line/byte range slicing.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from src.runtime.run_state_ledger import AgentRunState

_MAX_FULL_READ_BYTES = 512 * 1024  # 512 KB safe ceiling for unconstrained reads


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
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        display_path: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """Read a file with context-residency awareness and optional range extraction.

        Returns (content_or_receipt, is_resident_hit).
        """
        # Mutual exclusivity check
        has_line_range = start_line is not None or end_line is not None
        has_byte_range = offset is not None or limit is not None
        if has_line_range and has_byte_range:
            return (
                "Error: Cannot specify both line-range (start_line/end_line) and "
                "byte-range (offset/limit) parameters simultaneously.",
                False,
            )

        # Line range validation
        if start_line is not None and start_line < 1:
            return f"Error: start_line must be >= 1 (received {start_line}).", False
        if end_line is not None and end_line < 1:
            return f"Error: end_line must be >= 1 (received {end_line}).", False
        if start_line is not None and end_line is not None and start_line > end_line:
            return (
                f"Error: start_line ({start_line}) cannot be greater than end_line ({end_line}).",
                False,
            )

        # Byte range validation
        if offset is not None and offset < 0:
            return f"Error: offset must be >= 0 (received {offset}).", False
        if limit is not None and limit < 0:
            return f"Error: limit must be >= 0 (received {limit}).", False

        p = Path(file_path).resolve()
        resolved = str(p)

        if not p.exists():
            return f"Error: File '{file_path}' not found.", False

        if p.is_dir():
            return f"Error: '{file_path}' is a directory, not a file.", False

        try:
            with open(p, "rb") as f:
                content_bytes = f.read()
        except Exception as exc:
            return f"Error reading '{file_path}': {exc}", False

        current_hash = hashlib.sha256(content_bytes).hexdigest()
        self._disk_hashes[resolved] = current_hash

        display_name = (display_path or str(file_path)).replace("\\", "/")

        # 1. Full unconstrained read
        if not (has_line_range or has_byte_range):
            is_resident = False
            if not force_fresh and self.state is not None:
                is_resident = self.state.is_file_resident(
                    resolved, current_hash, active_prompt_text=active_prompt_text
                )

            if is_resident:
                receipt = (
                    f"[CONTENT RESIDENT]: '{p.name}' is already resident in your active context "
                    f"(SHA-256: {current_hash[:8]}). Reference resident lines or specify line range offsets."
                )
                return receipt, True

            if self.state is not None:
                self.state.update_file_residency(resolved, current_hash)

            if len(content_bytes) > _MAX_FULL_READ_BYTES:
                sliced_bytes = content_bytes[:_MAX_FULL_READ_BYTES]
                try:
                    text = sliced_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    text = sliced_bytes.decode("latin-1", errors="replace")
                text = text.replace("\r\n", "\n").replace("\r", "\n")
                header = (
                    f"File: {display_name}\n"
                    f"Range: Bytes 0–{_MAX_FULL_READ_BYTES}\n"
                    f"Total bytes: {len(content_bytes)}\n"
                    f"Bytes returned: {len(sliced_bytes)}\n"
                    f"Truncated: true\n"
                    f"SHA-256: {current_hash}\n"
                    f"Note: File exceeds 512KB default limit. Specify start_line/end_line or offset/limit to read specific sections.\n\n"
                )
                return header + text, False

            try:
                text = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text = content_bytes.decode("latin-1", errors="replace")

            text = text.replace("\r\n", "\n").replace("\r", "\n")
            return text, False

        # 2. Byte range reading
        if has_byte_range:
            total_bytes = len(content_bytes)
            start_b = offset if offset is not None else 0
            if start_b > total_bytes:
                start_b = total_bytes
            max_len = limit if limit is not None else (total_bytes - start_b)
            end_b = min(total_bytes, start_b + max_len)
            sliced_bytes = content_bytes[start_b:end_b]
            try:
                sliced_text = sliced_bytes.decode("utf-8")
            except UnicodeDecodeError:
                sliced_text = sliced_bytes.decode("utf-8", errors="replace")

            is_truncated = end_b < total_bytes
            header = (
                f"File: {display_name}\n"
                f"Range: Bytes {start_b}–{end_b}\n"
                f"Total bytes: {total_bytes}\n"
                f"Bytes returned: {len(sliced_bytes)}\n"
                f"Truncated: {'true' if is_truncated else 'false'}\n"
                f"SHA-256: {current_hash}\n\n"
            )
            return header + sliced_text, False

        # 3. Line range reading
        try:
            full_text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            full_text = content_bytes.decode("latin-1", errors="replace")

        full_text = full_text.replace("\r\n", "\n").replace("\r", "\n")
        lines = full_text.splitlines(keepends=True)
        total_lines = len(lines)

        if total_lines == 0:
            header = (
                f"File: {display_name}\n"
                f"Range: Lines 0–0\n"
                f"Total lines: 0\n"
                f"Truncated: false\n"
                f"SHA-256: {current_hash}\n\n"
            )
            return header, False

        start_l = start_line if start_line is not None else 1
        end_l = end_line if end_line is not None else total_lines

        start_idx = max(0, start_l - 1)
        end_idx = min(total_lines, end_l)

        if start_idx >= total_lines:
            sliced_lines = []
            actual_end_reported = total_lines
        else:
            sliced_lines = lines[start_idx:end_idx]
            actual_end_reported = min(end_l, total_lines)

        sliced_text = "".join(sliced_lines)
        is_truncated = end_l < total_lines

        header = (
            f"File: {display_name}\n"
            f"Range: Lines {start_l}–{actual_end_reported}\n"
            f"Total lines: {total_lines}\n"
            f"Truncated: {'true' if is_truncated else 'false'}\n"
            f"SHA-256: {current_hash}\n\n"
        )
        return header + sliced_text, False
