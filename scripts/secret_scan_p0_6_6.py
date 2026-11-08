"""Scan files for credential material before committing evidence.

Heuristics: known key prefixes, assignment of secret-looking env vars to
non-empty values, bearer tokens, private key blocks, and long random-looking
base64/hex blobs in suspicious context. Prints every hit with file:line.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo")

PATTERNS = [
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("nvidia_key", re.compile(r"\bnvapi-[A-Za-z0-9_\-]{20,}")),
    ("groq_key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("bearer", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}")),
    ("secret_assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|credential)\b\s*[:=]\s*[\"']?([A-Za-z0-9_\-./+]{12,})[\"']?"
    )),
    ("env_key_value", re.compile(
        r"(?i)\b(?:OPENAI|ANTHROPIC|GEMINI|GROQ|CUSTOM|NVIDIA|OPENROUTER|DEEPSEEK)_(?:API_)?KEY\s*=\s*[^\s\"']{8,}"
    )),
]

# Values that look like secrets but are documented placeholders.
ALLOW = re.compile(
    r"(?i)(?:your[_-]?api[_-]?key|xxx+|placeholder|example|redacted|dummy|fake|test[_-]?key|"
    r"not[_-]?a[_-]?real|<[^>]+>|\$\{[^}]+\}|token[_-]?budget|token_budget|max_tokens|tokens_|"
    r"cancel|prompt_sha|sha256|hash|reject|unknown|none|null)"
)


def scan(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"{path}: unreadable: {exc}"]
    hits: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        for name, pattern in PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0)
                if ALLOW.search(value):
                    continue
                # Ignore hits that are clearly diagnostics about the scanner itself.
                hits.append(f"{path.relative_to(ROOT)}:{number}: {name}: {value[:60]}")
    return hits


def main(argv: list[str]) -> int:
    targets: list[Path] = []
    for raw in argv:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        if candidate.is_dir():
            targets.extend(p for p in candidate.rglob("*") if p.is_file())
        else:
            targets.append(candidate)
    all_hits: list[str] = []
    for path in targets:
        all_hits.extend(scan(path))
    if all_hits:
        print(f"SECRET SCAN: {len(all_hits)} potential hit(s)")
        for hit in all_hits[:200]:
            print("  " + hit)
        return 1
    print(f"SECRET SCAN: clean across {len(targets)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
