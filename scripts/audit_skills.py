#!/usr/bin/env python3
"""Conformance + quality audit for the Architect skill library.

Runs the same rules the pytest gate runs, and prints a quality scorecard so a
human can see which books are actually good rather than merely present.

    python scripts/audit_skills.py            # audit + scorecard
    python scripts/audit_skills.py --json     # machine-readable
    python scripts/audit_skills.py --strict   # exit 1 on any violation
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "skills"

NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
DECISION_RE = re.compile(r"^## (Decision \d|Step \d|A\d\d\b)", re.M)
FAILURE_RE = re.compile(r"^## (Failure modes|Anti-patterns that force a rewrite)", re.M)
RECEIPT_RE = re.compile(r"^## Verification receipts", re.M)

MIN_BODY = 2500
MAX_BODY = 6000
MIN_TRIGGERS = 6
MIN_DECISIONS = 2


def parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    book: dict = {"file": str(path.relative_to(ROOT.parent)), "raw_len": len(text)}
    if not text.startswith("---"):
        book["error"] = "no frontmatter"
        return book
    end = text.index("\n---", 3)
    fm, body = text[3:end], text[end + 4 :]

    def get(key: str):
        m = re.search(r"^%s:\s*(.*)$" % re.escape(key), fm, re.M)
        return m.group(1).strip().strip('"') if m else None

    book.update(
        name=get("name"),
        description=get("description") or "",
        license=get("license"),
        domain=get("  crusor-domain"),
        path=get("  crusor-path"),
        origin=get("  crusor-origin"),
        sources=get("  crusor-sources") or "",
        triggers=[t.strip() for t in (get("  crusor-triggers") or "").split(",") if t.strip()],
        verified_on=get("  crusor-verified-on"),
        body=body,
    )
    return book


def check(book: dict) -> list[str]:
    if book.get("error"):
        return [book["error"]]
    rel = Path(book["file"]).relative_to("skills").parent
    name = book["name"] or ""
    v: list[str] = []
    if name != rel.name:
        v.append(f"name {name!r} != directory {rel.name!r}")
    if not NAME_RE.match(name):
        v.append("name is not [a-z0-9-]{1,64}")
    if not name.endswith("-architect"):
        v.append("name does not end in -architect")
    if not book["description"]:
        v.append("missing description")
    elif len(book["description"]) > 1024:
        v.append(f"description {len(book['description'])} > 1024")
    if re.search(r"(?i)\bnous\b", book["description"]):
        v.append("description contains the brand-gate word 'nous'")
    if not book["license"]:
        v.append("missing license")
    if book["domain"] != rel.parts[0]:
        v.append(f"crusor-domain {book['domain']!r} != {rel.parts[0]!r}")
    if book["path"] != str(rel):
        v.append(f"crusor-path {book['path']!r} != {str(rel)!r}")
    if book["origin"] not in ("original", "adapted"):
        v.append(f"crusor-origin {book['origin']!r} not original|adapted")
    if not book["verified_on"]:
        v.append("missing crusor-verified-on")
    if len(book["triggers"]) < MIN_TRIGGERS:
        v.append(f"only {len(book['triggers'])} triggers (min {MIN_TRIGGERS})")
    if book["origin"] == "adapted":
        if "@" not in book["sources"]:
            v.append("adapted but crusor-sources has no pinned owner/repo@sha")
        # the licence may be named in crusor-sources or in the spec's own
        # `license` field; either is a valid grant record.
        if not re.search(r"(MIT|Apache-2\.0|BSD)", book["sources"] + " " + (book["license"] or "")):
            v.append("adapted but no licence is named in crusor-sources or license")
        if book["license"] not in ("MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause"):
            v.append("adapted book carries no redistributable license")

    body = book["body"]
    if len(body) < MIN_BODY:
        v.append(f"body {len(body)} < {MIN_BODY} chars (below reference resolution)")
    if len(body) > MAX_BODY:
        v.append(f"body {len(body)} > {MAX_BODY} chars (injection cap)")
    if body.count("\n") > 500:
        v.append(f"body {body.count(chr(10))} lines > 500")
    if "## When to use" not in body:
        v.append("missing '## When to use'")
    if "## When NOT to use" not in body:
        v.append("missing '## When NOT to use'")
    # Domain crowns are index books: they map branches rather than decide. They are
    # exempt from the decision count but still owe when-to-use, failures and receipts.
    is_domain_crown = len(rel.parts) == 1
    if not is_domain_crown and len(DECISION_RE.findall(body)) < MIN_DECISIONS:
        v.append(f"fewer than {MIN_DECISIONS} decision sections")
    if not FAILURE_RE.search(body):
        v.append("missing failure-modes section")
    if not RECEIPT_RE.search(body):
        v.append("missing '## Verification receipts'")
    return v


def score(book: dict) -> dict:
    """Quality rubric: 100 points, evidence-based, no judgement of taste."""
    body = book.get("body") or ""
    low = body.lower()
    numbers = len(re.findall(r"\b\d[\d,.]*\s?(ms|s|%|kb|mb|gb|rps|qps|x|days?|hours?|minutes?)\b", low))
    named = len(re.findall(r"`[^`]{2,40}`", body))
    tables = body.count("\n| ---")
    decisions = len(DECISION_RE.findall(body))
    failures = max(0, body.lower().count("\n- ") - 0)
    receipts = len(re.findall(r"^\d\. ", body.split("## Verification receipts")[-1], re.M)) if "## Verification receipts" in body else 0
    # Calibration: a book that meets the template (>=3.5 KB, 5+ decisions, 20 named
    # APIs, 4 tables, 5 receipts) scores ~85+. Maxima are reachable, not theoretical.
    parts = {
        "size": min(15, len(body) / 233),
        "decisions": min(20, decisions * 4),
        "specificity_named_api": min(15, named * 0.75),
        "quantified": min(10, numbers * 1.0),
        "tables": min(10, tables * 2.5),
        "receipts": min(15, receipts * 3),
        "density_bullets": min(15, failures / 2.7),
    }
    return {"total": round(sum(parts.values())), **{k: round(v) for k, v in parts.items()}}


def audit() -> tuple[list[dict], dict]:
    books = [parse(p) for p in sorted(ROOT.rglob("SKILL.md")) if p.parent.relative_to(ROOT).parts
             and p.parent.relative_to(ROOT).parts[0].endswith("-architect")]
    report = {"books": [], "violations": {}}
    for b in books:
        v = check(b)
        sc = score(b) if not b.get("error") else {"total": 0}
        report["books"].append({"name": b["name"], "file": b["file"], "violations": v, "score": sc,
                                "size": len(b.get("body") or ""), "domain": (b.get("domain") or "")})
        for x in v:
            report["violations"].setdefault(x.split(" ")[0], []).append(b["name"])
    return books, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--bottom", type=int, default=12)
    args = ap.parse_args()

    books, report = audit()
    bad = [b for b in report["books"] if b["violations"]]

    if args.json:
        print(json.dumps(report, indent=1))
        return 1 if (bad and args.strict) else 0

    print(f"books: {len(report['books'])}   violations: {len(bad)}   "
          f"clean: {len(report['books']) - len(bad)}")
    if bad:
        print("\nviolations")
        for b in bad:
            print(f"  {b['name']} ({b['file']})")
            for v in b["violations"]:
                print(f"      - {v}")

    by_domain: dict[str, list[int]] = {}
    for b in report["books"]:
        by_domain.setdefault(b["domain"], []).append(b["score"]["total"])
    print("\nquality by domain (rubric mean / 100)")
    for d, s in sorted(by_domain.items()):
        print(f"  {d:34} n={len(s):3}  mean={sum(s)/len(s):5.1f}  min={min(s):3}  max={max(s):3}")

    ranked = sorted(report["books"], key=lambda b: b["score"]["total"], reverse=True)
    print(f"\ntop {5}")
    for b in ranked[:5]:
        print(f"  {b['score']['total']:3}  {b['name']}  ({b['size']} chars)")
    print(f"\nbottom {args.bottom}")
    for b in ranked[-args.bottom:]:
        print(f"  {b['score']['total']:3}  {b['name']}  ({b['size']} chars)")
    return 1 if (bad and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
