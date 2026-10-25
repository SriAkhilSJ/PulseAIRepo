#!/usr/bin/env python3
"""Verify one Agent Core runtime evidence manifest and its durable journal."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Direct ``python scripts/...`` execution starts sys.path at scripts/.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime.evidence_validation import validate_turn_evidence  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a per-turn evidence manifest checksum, artifact hashes, "
            "journal chain, terminal identity, counts, and tool pairing."
        )
    )
    parser.add_argument("manifest", help="Path to <turn-id>.json")
    parser.add_argument(
        "--journal",
        help="Override the runtime_events.db path recorded in the manifest",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="also fail when capture is honest but reports missing artifacts",
    )
    args = parser.parse_args(argv)
    result = validate_turn_evidence(
        args.manifest,
        journal_path=args.journal,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    if not result.integrity_valid:
        return 1
    if args.require_complete and not result.capture_complete:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
