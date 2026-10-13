#!/usr/bin/env python3
"""Expose pytest failure details as GitHub check annotations and a job summary.

The Actions log-download endpoint is not always available to the local GitHub
CLI, so preserve the actionable failing test name/message in the check itself.
This script is stdlib-only and deliberately never masks pytest's exit status.
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _workflow_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    report = Path(argv[0]) if argv else Path("target-tests.xml")
    if not report.is_file():
        print(f"No pytest JUnit report was written: {report}", file=sys.stderr)
        return 0  # pytest's own step already carries the failure status.

    try:
        root = ET.parse(report).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"Could not parse pytest JUnit report: {exc}", file=sys.stderr)
        return 0

    failures: list[tuple[str, str]] = []
    for case in root.iter("testcase"):
        test_name = ".".join(part for part in (case.get("classname", ""), case.get("name", "")) if part)
        for tag in ("failure", "error"):
            for node in case.findall(tag):
                details = "\n".join(
                    part.strip() for part in (node.get("message", ""), node.text or "") if part.strip()
                )
                failures.append((test_name or "unknown test", details or tag))

    if not failures:
        return 0

    summary = [f"### Pytest failures ({len(failures)})", ""]
    for test_name, details in failures:
        text = f"{test_name}: {details}"[:5000]
        print(f"::error::{_workflow_escape(text)}")
        summary.extend([f"**{test_name}**", "", "```text", details[:5000], "```", ""])

    summary_value = os.environ.get("GITHUB_STEP_SUMMARY", "")
    summary_path = Path(summary_value) if summary_value else None
    if summary_path is not None:
        try:
            with summary_path.open("a", encoding="utf-8") as stream:
                stream.write("\n".join(summary) + "\n")
        except OSError as exc:
            print(f"Could not write GitHub step summary: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
