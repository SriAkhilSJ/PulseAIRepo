#!/usr/bin/env python3
"""Generate the cacheable TypeScript protocol-name contract from v2 JSON.

The JSON manifest is the source of truth for version, names, and identity keys.
Rich per-frame payload interfaces stay handwritten and are pinned against the
same generated name unions. Run with --check in CI to detect drift.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "src" / "bridge" / "protocol_v2.json"
OUTPUT = (
    ROOT
    / "desktop"
    / "vscode"
    / "src"
    / "vs"
    / "workbench"
    / "contrib"
    / "pulseai"
    / "common"
    / "pulseAIProtocol.generated.ts"
)


def _quoted(values: list[str]) -> str:
    return "\n".join(f"\t'{value}'," for value in values)


def render(data: dict) -> str:
    version = int(data["protocol"])
    modes = list(data["execution_modes"])
    methods = list(data["client_methods"])
    events = list(data["server_events"])
    identities = list(data["identity_fields"])
    approval = str(data["approval_identity_field"])
    return f"""/*---------------------------------------------------------------------------------------------
 * GENERATED FILE — scripts/generate_bridge_protocol.py
 * Source: src/bridge/protocol_v2.json
 * Do not edit by hand.
 *--------------------------------------------------------------------------------------------*/

export const PULSE_AI_PROTOCOL_VERSION = {version} as const;

export const PULSE_AI_EXECUTION_MODES = [
{_quoted(modes)}
] as const;
export type PulseExecutionMode = (typeof PULSE_AI_EXECUTION_MODES)[number];

export const PULSE_AI_CLIENT_METHODS = [
{_quoted(methods)}
] as const;
export type PulseClientMethodName = (typeof PULSE_AI_CLIENT_METHODS)[number];

export const PULSE_AI_SERVER_EVENTS = [
{_quoted(events)}
] as const;
export type PulseServerEventName = (typeof PULSE_AI_SERVER_EVENTS)[number];

export const PULSE_AI_IDENTITY_FIELDS = [
{_quoted(identities)}
] as const;
export type PulseIdentityField = (typeof PULSE_AI_IDENTITY_FIELDS)[number];

export const PULSE_AI_APPROVAL_IDENTITY_FIELD = '{approval}' as const;
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rendered = render(data)
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"stale generated protocol: {OUTPUT}")
            return 1
        print(f"protocol generated file is current: {OUTPUT}")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
