"""
Crusor Skills Hub
=================
The INSTALL side of the skills story: discover community Agent Skills
(agentskills.io open standard — `SKILL.md` folders) and install them into the
user's skill store with a full safety pipeline.

Sources
-------
- The bundled catalog (`skills/catalog.json`): curated entries, each pinned to
  an exact 40-char commit SHA. Presence in the catalog is the trust signal;
  installs check out exactly that commit, never a moving branch.
- Direct GitHub sources: `owner/repo`, `owner/repo@ref`, `owner/repo@ref:subdir`
  or a github.com URL. A symbolic ref is resolved to a full SHA *before*
  download and the resolved SHA is recorded in provenance; if resolution is
  impossible the install fails closed.

Safety pipeline (every install, catalog or not)
-----------------------------------------------
1. Host allow-list: only github.com / codeload.github.com / api.github.com.
2. Download caps: archive size capped, read bounded.
3. Safe extraction: no absolute paths, no `..` traversal, no symlink/hardlink
   members, file-count and byte caps; everything stays inside a temp root.
4. Skill validation: a discoverable `SKILL.md` with a non-empty body, a
   sanitized slug name, per-skill file/byte caps.
5. Collision guard: an existing skill of the same name is never silently
   overwritten — only a prior install of the SAME source can be upgraded.
6. No code execution: installing never runs anything from the skill. Skill
   scripts are data; running them stays behind the usual tool approval gates.

Conventions (match the skills family): public functions return result dicts
with an `ok` flag and never raise; the skills layer must never block a turn.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable

from src.agents.skill_manager import (
    SkillManager,
    _frontmatter_triggers,
    _parse_skill_frontmatter,
)

# ---------------------------------------------------------------------------
# Caps and allow-lists
# ---------------------------------------------------------------------------

_MAX_ARCHIVE_BYTES = 25 * 1024 * 1024      # downloaded tarball cap
_MAX_REPO_FILES = 2000                     # extracted repo-wide file cap
_MAX_SKILL_FILES = 400                     # per installed skill file cap
_MAX_SKILL_BYTES = 8 * 1024 * 1024         # per installed skill byte cap
_MAX_BODY_CHARS = 6000                     # instruction cap (bundled parity)
_MAX_NAME_CHARS = 64
_WALK_DEPTH = 6                            # SKILL.md discovery depth

_ALLOWED_HOSTS = frozenset({
    "github.com",
    "www.github.com",
    "codeload.github.com",
    "api.github.com",
})

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TRUST_TIERS = ("curated", "community")

_USER_AGENT = "CrusorAI-Skills-Hub/1.0"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_catalog_path() -> Path:
    return _repo_root() / "skills" / "catalog.json"


def _hub_root(hub_root: str | Path | None = None) -> Path:
    """Root for hub-installed skill folders + the provenance ledger."""
    if hub_root is not None:
        return Path(hub_root)
    env = os.environ.get("CRUSORAI_HUB_SKILLS_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".crusorai" / "hub-skills"


def _manager(manager: SkillManager | None = None) -> SkillManager:
    if manager is not None:
        return manager
    from src.agents.skill_manager import skill_manager
    return skill_manager


# ---------------------------------------------------------------------------
# Result helper — the skills layer never raises (fail-open house style)
# ---------------------------------------------------------------------------

def _fail(error: str, **extra: Any) -> dict:
    out: dict[str, Any] = {"ok": False, "error": error}
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Source parsing
# ---------------------------------------------------------------------------

def parse_source(source: str) -> dict:
    """Parse an install source into a structured request.

    Accepted shapes:
      - catalog name:            ``frontend-design``
      - owner/repo:              ``vercel-labs/agent-skills``
      - owner/repo@ref:          ``owner/repo@8a1541c4a3ff...`` (full SHA needs
                                 no network)
      - owner/repo@ref:subdir:   ``owner/repo@main:skills/x``
      - owner/repo:subdir:       ``owner/repo:skills/x``
      - https://github.com/owner/repo[/tree/ref[/subdir]]
    """
    raw = (source or "").strip().strip("/")
    if not raw:
        return _fail("empty install source")

    subdir = ""
    if raw.startswith(("http://", "https://")):
        try:
            from urllib.parse import urlparse
            host = urlparse(raw).netloc.lower()
        except Exception:
            return _fail(f"unparseable URL: {source!r}")
        if host not in _ALLOWED_HOSTS:
            return _fail(f"host {host!r} is not allowed (github.com only)")
        path = urlparse(raw).path.strip("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            return _fail(f"URL must point at owner/repo, got {source!r}")
        owner, repo = parts[0], re.sub(r"\.git$", "", parts[1])
        ref = ""
        if len(parts) >= 4 and parts[2] == "tree":
            ref = parts[3]
            subdir = "/".join(parts[4:])
        rest = f"{owner}/{repo}"
        if ref:
            rest += f"@{ref}"
        if subdir:
            rest += f":{subdir}"
        return parse_source(rest)

    if "/" not in raw:
        return {"ok": True, "kind": "catalog", "name": raw.lower()}

    # owner/repo[@ref][:subdir]
    m = re.match(r"^([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:@([^:/]+))?((?::)(.*))?$", raw)
    if not m:
        return _fail(
            f"cannot parse source {source!r} — expected a catalog name, "
            "'owner/repo', 'owner/repo@ref' or 'owner/repo@ref:subdir'"
        )
    owner, repo, ref, _colon, sdir = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    subdir = (sdir or "").strip().strip("/")
    if ref is not None and not ref.strip():
        return _fail(f"empty ref in {source!r}")
    return {
        "ok": True,
        "kind": "repo",
        "owner": owner,
        "repo": repo,
        "ref": (ref or "").strip(),
        "subdir": subdir,
    }


# ---------------------------------------------------------------------------
# Network (both injectable for hermetic tests)
# ---------------------------------------------------------------------------

def _check_url(url: str) -> str | None:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
    except Exception:
        return f"unparseable URL: {url!r}"
    if host not in _ALLOWED_HOSTS:
        return f"refusing to fetch from non-allowlisted host {host!r}"
    if not url.startswith("https://"):
        return f"refusing non-https fetch: {url!r}"
    return None


def default_fetcher(url: str, max_bytes: int = _MAX_ARCHIVE_BYTES) -> bytes:
    """Bounded HTTPS GET — allowlisted hosts only, hard byte cap."""
    err = _check_url(url)
    if err:
        raise ValueError(err)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (allowlisted https)
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"download exceeds the {_MAX_ARCHIVE_BYTES // (1024 * 1024)}MB cap")
    return data


def default_ref_resolver(owner: str, repo: str, ref: str) -> str | None:
    """Resolve a symbolic ref to a full 40-char SHA via the GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}"
    err = _check_url(url)
    if err:
        raise ValueError(err)
    req = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            payload = json.loads(resp.read(1024 * 1024).decode("utf-8", "replace"))
        sha = str(payload.get("sha", ""))
        return sha if _SHA_RE.match(sha) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def load_catalog(path: str | Path | None = None) -> dict:
    """Load + validate the bundled catalog. Invalid entries are dropped with
    reasons — a broken catalog entry must never block the hub."""
    p = Path(path) if path is not None else default_catalog_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _fail(f"catalog not found: {p}")
    except Exception as exc:
        return _fail(f"catalog unreadable: {exc}")

    entries: list[dict] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for item in raw.get("entries", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            rejected.append("non-object entry")
            continue
        name = str(item.get("name", "")).strip().lower()
        repo = str(item.get("repo", "")).strip()
        sha = str(item.get("sha", "")).strip().lower()
        if not _NAME_RE.match(name):
            rejected.append(f"{name or '?'}: bad name")
            continue
        if name in seen:
            rejected.append(f"{name}: duplicate")
            continue
        if not re.match(r"^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/?$", repo):
            rejected.append(f"{name}: repo must be a github.com repo root URL")
            continue
        if not _SHA_RE.match(sha):
            rejected.append(f"{name}: catalog entries require a full 40-char commit SHA")
            continue
        trust = str(item.get("trust", "curated")).strip().lower()
        if trust not in _TRUST_TIERS:
            rejected.append(f"{name}: trust must be curated|community")
            continue
        seen.add(name)
        entries.append({
            "name": name,
            "repo": repo.rstrip("/"),
            "sha": sha,
            "subdir": str(item.get("subdir", "")).strip().strip("/"),
            "description": str(item.get("description", "")).strip(),
            "category": str(item.get("category", "")).strip().lower(),
            "trust": trust,
        })
    return {"ok": True, "entries": entries, "rejected": rejected, "path": str(p)}


def search_catalog(catalog: dict, query: str, category: str = "") -> dict:
    """Keyword search over catalog entries. Every token must match somewhere
    (name / category / description); results ranked by where they matched."""
    if not catalog.get("ok"):
        return catalog
    tokens = [t.lower() for t in re.split(r"[\s,]+", query or "") if t.strip()]
    want_cat = (category or "").strip().lower()
    hits: list[tuple[int, dict]] = []
    for entry in catalog.get("entries", []):
        if want_cat and entry["category"] != want_cat:
            continue
        name = entry["name"].lower()
        cat = entry["category"].lower()
        desc = entry["description"].lower()
        repo_name = entry["repo"].rsplit("/", 1)[-1].lower()
        score = 0
        matched_all = True
        for tok in tokens:
            tok_score = 0
            if tok in name:
                tok_score += 4
            if tok in cat:
                tok_score += 2
            if tok in repo_name:
                tok_score += 2
            if tok in desc:
                tok_score += 1
            if tok_score == 0:
                matched_all = False
                break
            score += tok_score
        if matched_all and (tokens or want_cat):
            hits.append((score, entry))
    hits.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
    return {"ok": True, "results": [e for _s, e in hits[:12]], "total": len(hits)}


def catalog_categories(catalog: dict) -> list[str]:
    if not catalog.get("ok"):
        return []
    cats = sorted({e["category"] for e in catalog["entries"] if e["category"]})
    return cats


def _entry_to_source(entry: dict) -> str:
    src = f"{_owner_repo(entry['repo'])}@{entry['sha']}"
    if entry.get("subdir"):
        src += f":{entry['subdir']}"
    return src


def _owner_repo(repo_url: str) -> str:
    return repo_url.replace("https://github.com/", "").strip("/")


# ---------------------------------------------------------------------------
# Safe extraction
# ---------------------------------------------------------------------------

def _member_target(dest: Path, name: str) -> Path | None:
    """Resolve a tar member path; None if it escapes dest or is unsafe."""
    if name.startswith(("/", "\\")) or ":" in name.split("/")[0] and len(name.split("/")[0]) <= 3:
        return None
    parts = name.replace("\\", "/").split("/")
    if any(p in ("", ".") for p in parts[:-1]) or ".." in parts:
        return None
    target = dest.joinpath(*parts)
    # final containment check via resolved paths
    try:
        target.resolve().relative_to(dest.resolve())
    except (ValueError, OSError):
        return None
    return target


def safe_extract(tar_bytes: bytes, dest: Path, only_subdir: str = "") -> dict:
    """Extract a repo tarball safely: traversal-proof, capped, link-aware.

    Symlinks INSIDE the repo (relative targets that stay within the archive,
    e.g. ``CLAUDE.md -> README.md``) are common in real community repos and
    are materialized as real file copies of their target. Absolute or
    escaping links, hardlinks, and device members are rejected outright.

    ``only_subdir`` narrows extraction to one subtree BEFORE the file-count
    cap applies — curated catalogs pin skills inside large monorepos (a
    2000+-entry repo hosting a 2-file skill is normal), and the cap is a
    guard on what we EXTRACT, not a ban on big repos. Caps, traversal and
    link checks still apply to every member actually extracted; nothing
    outside the subtree is ever read into the workspace.
    """
    total_files = 0
    total_bytes = 0
    pending_links: list[tuple[Path, str]] = []
    try:
        tf = tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:*")
    except Exception as exc:
        return _fail(f"not a readable tarball: {exc}")
    with tf:
        members = tf.getmembers()
        unfiltered = len(members)
        if only_subdir:
            sub = only_subdir.strip("/")
            direct = [m for m in members if m.name.startswith(sub + "/")]
            if direct:
                # flat archive: the subtree sits at the top level already
                members = direct
            else:
                # GitHub wraps everything in <repo>-<sha>/ — anchor below it
                top = next(
                    (m.name.split("/", 1)[0] for m in members if "/" in m.name), ""
                )
                prefix = f"{top}/{sub}/" if top else f"{sub}/"
                members = [m for m in members if m.name.startswith(prefix)]
            if not members:
                return _fail(f"subdir {only_subdir!r} not found in the archive")
        if len(members) > _MAX_REPO_FILES:
            hint = (
                " — this repo is too large to install whole; install a subdirectory "
                "with 'owner/repo@<sha>:<subdir>'"
                if len(members) == unfiltered
                else ""
            )
            return _fail(f"archive has {len(members)} entries (cap {_MAX_REPO_FILES}){hint}")
        for member in members:
            if member.islnk() or member.isdev():
                return _fail(f"hardlink/device members are not allowed ({member.name!r})")
            if member.issym():
                linkname = (member.linkname or "").strip()
                if linkname.startswith("/") or (len(linkname) > 1 and linkname[1] == ":"):
                    return _fail(f"absolute symlink rejected ({member.name!r} -> {linkname!r})")
                base = (dest / member.name).parent
                resolved = (base / linkname).resolve()
                try:
                    resolved.relative_to(dest.resolve())
                except (ValueError, OSError):
                    return _fail(f"escaping symlink rejected ({member.name!r} -> {linkname!r})")
            if member.isfile() and member.size > _MAX_SKILL_BYTES:
                return _fail(f"member {member.name!r} exceeds the per-file cap")
            total_bytes += member.size
            if total_bytes > _MAX_ARCHIVE_BYTES:
                return _fail("archive exceeds the total byte cap")
        for member in members:
            target = _member_target(dest, member.name)
            if target is None:
                return _fail(f"unsafe member path rejected: {member.name!r}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.issym():
                pending_links.append((target, (member.linkname or "").strip()))
                continue
            if not member.isfile():
                return _fail(f"unsupported member type: {member.name!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                return _fail(f"unreadable member: {member.name!r}")
            with open(target, "wb") as out:
                shutil.copyfileobj(src, out, length=64 * 1024)
            total_files += 1
    # Second pass: materialize contained symlinks as real copies of their
    # target (they were validated to stay inside dest).
    for link_path, linkname in pending_links:
        base = link_path.parent
        candidate = (base / linkname).resolve()
        try:
            candidate.relative_to(dest.resolve())
        except (ValueError, OSError):
            continue
        if candidate.is_file():
            link_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidate, link_path)
    return {"ok": True, "files": total_files, "bytes": total_bytes, "root": str(dest)}


# ---------------------------------------------------------------------------
# Skill discovery + validation
# ---------------------------------------------------------------------------

def discover_skill_dirs(root: Path) -> list[Path]:
    """Find directories containing a SKILL.md, bounded depth, parent-first
    (a dir that IS a skill is not descended into for more skills)."""
    found: list[Path] = []

    def walk(dir_path: Path, depth: int) -> None:
        if depth > _WALK_DEPTH:
            return
        try:
            if (dir_path / "SKILL.md").is_file():
                found.append(dir_path)
                return
            for child in sorted(dir_path.iterdir()):
                if child.is_dir() and not child.is_symlink():
                    walk(child, depth + 1)
        except (PermissionError, OSError):
            return

    walk(root, 0)
    return found


def _skill_slug(folder: Path, frontmatter: dict) -> str:
    name = str(frontmatter.get("name", "") or "").strip().lower()
    name = re.sub(r"[^a-z0-9._-]+", "-", name).strip("-.")
    if not name or not _NAME_RE.match(name):
        name = folder.name.lower()
        name = re.sub(r"[^a-z0-9._-]+", "-", name).strip("-.")
    return name[:_MAX_NAME_CHARS]


def _folder_stats(folder: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for p in folder.rglob("*"):
        if p.is_file() and not p.is_symlink():
            files += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return files, total


# ---------------------------------------------------------------------------
# Provenance ledger
# ---------------------------------------------------------------------------

def _ledger_path(hub_root: str | Path) -> Path:
    return Path(hub_root) / "provenance.json"


def _load_ledger(hub_root: str | Path) -> dict:
    p = _ledger_path(hub_root)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {"version": 1, "skills": {}}


def _save_ledger(hub_root: str | Path, ledger: dict) -> None:
    p = _ledger_path(hub_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# Install / uninstall / list
# ---------------------------------------------------------------------------

def lint_skill_metadata(
    name: str, frontmatter: dict, body: str, triggers: list[str]
) -> list[str]:
    """Install-time metadata linter (skill_linter parity) — WARN,
    never block. The safety pipeline owns trust; this owns "will the skill
    actually be discoverable and activatable". Bad metadata silently kills
    a skill: no description -> the index shows triggers instead; no trigger
    keywords -> it never auto-activates (pull-only via skill_view)."""
    warnings: list[str] = []
    if not str(frontmatter.get("description", "") or "").strip():
        warnings.append(
            "no frontmatter 'description' — the skills index will show trigger "
            "words instead of a real summary, so the model may skip pulling it"
        )
    meaningful = [t for t in triggers if t and t != name]
    if not meaningful:
        warnings.append(
            "no trigger keywords (frontmatter keywords/triggers or a "
            "**Triggers:** line) — it will never auto-activate; load it "
            "explicitly with skill_view"
        )
    if len(body) > _MAX_BODY_CHARS:
        warnings.append(
            f"body is {len(body)} chars — the injected instruction is capped at "
            f"{_MAX_BODY_CHARS}; the rest is only visible via skill_view"
        )
    return warnings


def install_skill(
    source: str,
    *,
    catalog: dict | None = None,
    manager: SkillManager | None = None,
    hub_root: str | Path | None = None,
    fetcher: Callable[[str], bytes] | None = None,
    ref_resolver: Callable[[str, str, str], str | None] | None = None,
    pick: str = "",
) -> dict:
    """Install one community skill through the full safety pipeline.

    `fetcher` and `ref_resolver` are injectable so the whole pipeline is
    testable with zero network.
    """
    src = parse_source(source)
    if not src.get("ok"):
        return src

    trust = "community"
    sha = ""
    if src["kind"] == "catalog":
        cat = catalog if catalog is not None else load_catalog()
        if not cat.get("ok"):
            return _fail(f"catalog unavailable: {cat.get('error')}")
        entry = next((e for e in cat["entries"] if e["name"] == src["name"].lower()), None)
        if entry is None:
            return _fail(
                f"no catalog entry named {src['name']!r} — hub_search to see what's available"
            )
        trust = entry["trust"]
        owner_repo = _owner_repo(entry["repo"])
        owner, repo = owner_repo.split("/", 1)
        sha = entry["sha"]
        subdir = entry["subdir"]
        ref = sha
    else:
        owner, repo = src["owner"], src["repo"]
        subdir = src["subdir"]
        ref = src["ref"]

    fetch = fetcher or default_fetcher
    resolve = ref_resolver or default_ref_resolver

    # Resolve the exact commit — the SHA is the trust + provenance anchor.
    if not sha:
        if ref and _SHA_RE.match(ref.lower()):
            sha = ref.lower()
        elif ref:
            sha = resolve(owner, repo, ref) or ""
            if not sha:
                return _fail(
                    f"could not resolve ref {ref!r} to an exact commit — installs are "
                    "SHA-pinned; pass a full 40-char commit SHA"
                )
        else:
            sha = resolve(owner, repo, "HEAD") or ""
            if not sha:
                return _fail("could not resolve the repo's current commit — pass an explicit SHA")

    # Download + extract safely.
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{sha}"
    try:
        tar_bytes = fetch(url)
    except Exception as exc:
        return _fail(f"download failed: {exc}")
    if len(tar_bytes) > _MAX_ARCHIVE_BYTES:
        return _fail("download exceeds the size cap")

    with tempfile.TemporaryDirectory(prefix="crusor-hub-") as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        ex = safe_extract(tar_bytes, root, only_subdir=subdir)
        if not ex.get("ok"):
            return ex

        # GitHub tarballs wrap everything in a single top-level directory
        # (`<repo>-<sha>/`). Treat it as the repo root so `subdir` and skill
        # discovery are relative to what the repo actually contains.
        try:
            top = [p for p in root.iterdir()]
        except OSError as exc:
            return _fail(f"extracted archive unreadable: {exc}")
        if len(top) == 1 and top[0].is_dir() and not top[0].is_symlink():
            root = top[0]

        scan_root = root / subdir if subdir else root
        if subdir and not scan_root.resolve().is_relative_to(root.resolve()):
            return _fail(f"subdir escapes the archive root: {subdir!r}")
        if subdir and not scan_root.is_dir():
            return _fail(f"subdir {subdir!r} not found in the archive at {sha[:12]}")

        skill_dirs = discover_skill_dirs(scan_root)
        if pick:
            wanted = pick.strip().lower()
            skill_dirs = [d for d in skill_dirs if _skill_slug(d, {}) == wanted or d.name.lower() == wanted]
        if not skill_dirs:
            scope = f" under {subdir!r}" if subdir else ""
            return _fail(f"no SKILL.md found{scope} in {owner}/{repo}@{sha[:12]}")
        if len(skill_dirs) > 1:
            listing = ", ".join(sorted(d.name for d in skill_dirs))
            return _fail(
                f"multiple skills found ({listing}) — install one with "
                f"'{owner}/{repo}@{sha}:<subdir>' or pass pick='<name>'"
            )

        folder = skill_dirs[0]
        skill_md = folder / "SKILL.md"
        try:
            frontmatter, body = _parse_skill_frontmatter(skill_md.read_text(encoding="utf-8"))
        except Exception as exc:
            return _fail(f"SKILL.md unreadable: {exc}")
        body = (body or "").strip()
        if not body:
            return _fail(f"{folder.name}/SKILL.md has no instruction body — not installable")

        name = _skill_slug(folder, frontmatter)

        # Caps.
        files, total = _folder_stats(folder)
        if files > _MAX_SKILL_FILES:
            return _fail(f"skill has {files} files (cap {_MAX_SKILL_FILES})")
        if total > _MAX_SKILL_BYTES:
            return _fail(f"skill is {total} bytes (cap {_MAX_SKILL_BYTES})")

        mgr = _manager(manager)
        hroot = Path(_hub_root(hub_root))
        dest = hroot / "skills" / name

        # Collision guard: only an upgrade of the SAME source may overwrite.
        existing = next(
            (s for s in mgr.list_skills() if str(s.get("name", "")).lower() == name.lower()),
            None,
        )
        upgraded = False
        if existing is not None:
            prev = existing.get("source") or {}
            if (
                prev.get("kind") == "hub"
                and str(prev.get("repo", "")).strip("/") == f"{owner}/{repo}"
                and str(prev.get("subdir", "")) == subdir
            ):
                upgraded = True
            else:
                origin = prev.get("kind") or existing.get("created_by", "existing")
                return _fail(
                    f"a skill named {name!r} already exists ({origin}) — installs never "
                    "overwrite a different source; remove it first or pick a different skill"
                )

        # Materialize the skill folder (fresh copy on upgrade — no orphans).
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for item in folder.rglob("*"):
            rel = item.relative_to(folder)
            if item.is_dir():
                (dest / rel).mkdir(parents=True, exist_ok=True)
            elif item.is_file() and not item.is_symlink():
                shutil.copy2(item, dest / rel)

    meta = {
        "kind": "hub",
        "repo": f"{owner}/{repo}",
        "sha": sha,
        "subdir": subdir,
        "ref": ref,
        "trust": trust,
        "installed_at": _now_iso(),
        "folder": str(dest),
        "files": files,
        "bytes": total,
    }

    triggers = _frontmatter_triggers(frontmatter) or [name]
    desc = str(frontmatter.get("description", "") or "").strip()
    instruction = body[:_MAX_BODY_CHARS]
    instruction += (
        f"\n\n[Installed via Crusor Skills Hub from github.com/{owner}/{repo} "
        f"@ {sha[:12]} — supporting files: {dest}]"
    )

    mgr.add_skill(
        name,
        triggers,
        instruction,
        created_by="user",
        pinned=True,
        description=desc[:200],
        source=meta,
    )

    ledger = _load_ledger(hroot)
    ledger.setdefault("version", 1)
    ledger.setdefault("skills", {})
    ledger["skills"][name] = meta
    _save_ledger(hroot, ledger)

    return {
        "ok": True,
        "name": name,
        "repo": meta["repo"],
        "sha": sha,
        "subdir": subdir,
        "trust": trust,
        "files": files,
        "bytes": total,
        "upgraded": upgraded,
        "folder": str(dest),
        "warnings": lint_skill_metadata(name, frontmatter, body, triggers),
    }


def uninstall_skill(
    name: str,
    *,
    manager: SkillManager | None = None,
    hub_root: str | Path | None = None,
) -> dict:
    """Remove a hub-installed skill (store entry + folder + ledger)."""
    clean = (name or "").strip()
    if not clean:
        return _fail("no skill name given")
    mgr = _manager(manager)
    skill = next(
        (s for s in mgr.list_skills() if str(s.get("name", "")).lower() == clean.lower()),
        None,
    )
    if skill is None:
        return _fail(f"no skill named {clean!r} is installed")
    if skill.get("created_by") == "bundled":
        return _fail(f"{skill['name']} is a bundled repo skill — bundled skills are read-only")
    meta = skill.get("source") or {}
    if meta.get("kind") != "hub":
        return _fail(
            f"{skill['name']} was not installed via the hub "
            f"(created_by={skill.get('created_by', 'user')!r}) — remove it with skill_manage"
        )

    folder = Path(str(meta.get("folder", "")))
    if not mgr.remove_skill(str(skill["name"])):
        return _fail(f"could not remove {skill['name']!r} from the skill store")
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)
    hroot = Path(_hub_root(hub_root))
    ledger = _load_ledger(hroot)
    ledger.get("skills", {}).pop(str(skill["name"]), None)
    _save_ledger(hroot, ledger)
    return {"ok": True, "name": str(skill["name"])}


def list_hub(
    *,
    catalog: dict | None = None,
    manager: SkillManager | None = None,
    hub_root: str | Path | None = None,
) -> dict:
    """Installed hub skills with provenance + a cheap update hint (the
    catalog pins a newer SHA for the same repo+subdir)."""
    mgr = _manager(manager)
    hroot = Path(_hub_root(hub_root))
    ledger = _load_ledger(hroot).get("skills", {})
    cat = catalog if catalog is not None else load_catalog()
    by_location: dict[tuple[str, str], dict] = {}
    if cat.get("ok"):
        for e in cat["entries"]:
            by_location[(_owner_repo(e["repo"]), e["subdir"])] = e

    rows: list[dict] = []
    for s in mgr.list_skills():
        meta = s.get("source") or {}
        if meta.get("kind") != "hub":
            continue
        row = {
            "name": str(s.get("name", "")),
            "repo": meta.get("repo", ""),
            "sha": meta.get("sha", ""),
            "subdir": meta.get("subdir", ""),
            "trust": meta.get("trust", "community"),
            "installed_at": meta.get("installed_at", ""),
            "files": meta.get("files", 0),
        }
        entry = by_location.get((row["repo"], row["subdir"]))
        row["update_available"] = bool(entry and entry["sha"] != row["sha"])
        rows.append(row)
    return {"ok": True, "installed": rows, "ledger": str(_ledger_path(hroot))}


def update_hub_skill(
    name: str,
    *,
    catalog: dict | None = None,
    manager: SkillManager | None = None,
    hub_root: str | Path | None = None,
    fetcher: Callable[[str], bytes] | None = None,
    ref_resolver: Callable[[str, str, str], str | None] | None = None,
) -> dict:
    """Upgrade one hub-installed skill to the SHA the catalog currently pins.

    Same trust model as install: the move is always to an exact catalog
    SHA (never a moving ref), through the same install pipeline, and only
    over a prior install of the SAME repo+subdir (the collision guard
    enforces that). A skill the catalog doesn't cover is reported, never
    touched.
    """
    clean = (name or "").strip()
    if not clean:
        return _fail("no skill name given")
    mgr = _manager(manager)
    skill = next(
        (s for s in mgr.list_skills() if str(s.get("name", "")).lower() == clean.lower()),
        None,
    )
    if skill is None:
        return _fail(f"no skill named {clean!r} is installed")
    meta = skill.get("source") or {}
    if meta.get("kind") != "hub":
        return _fail(f"{skill['name']} was not installed via the hub — nothing to update")

    cat = catalog if catalog is not None else load_catalog()
    if not cat.get("ok"):
        return _fail(f"catalog unavailable: {cat.get('error')}")
    entry = next(
        (
            e for e in cat["entries"]
            if _owner_repo(e["repo"]) == str(meta.get("repo", "")).strip("/")
            and e["subdir"] == str(meta.get("subdir", ""))
        ),
        None,
    )
    if entry is None:
        return _fail(
            f"{skill['name']} ({meta.get('repo')}:{meta.get('subdir')}) is not in the "
            "curated catalog — reinstall it directly with hub_install at a new SHA"
        )
    old_sha = str(meta.get("sha", ""))
    if entry["sha"] == old_sha:
        return {"ok": True, "name": str(skill["name"]), "updated": False, "sha": old_sha}

    src = _entry_to_source(entry)
    res = install_skill(
        src,
        catalog=cat,
        manager=mgr,
        hub_root=hub_root,
        fetcher=fetcher,
        ref_resolver=ref_resolver,
    )
    if not res.get("ok"):
        return res
    return {
        "ok": True,
        "name": res["name"],
        "updated": True,
        "from_sha": old_sha,
        "to_sha": res["sha"],
        "trust": res["trust"],
        "folder": res["folder"],
    }



def notify_skills_changed() -> dict:
    """Process-local invalidation seam for every mutating skills op.

    Field 2026-10-01: the skills-index LRU (+ disk snapshot), each live
    session view's cached system prompt, and each live thread engine's
    cached "skills" layer all outlived an install — so "live in the skills
    index now" was only true for NEW sessions. This seam makes the change
    visible to the NEXT model call of RUNNING sessions:

      1. skills-index LRU + disk snapshot  (prompts.hermes.skills_index)
      2. every cached per-view system prompt
         (prompts.hermes.session._views -> system_prompt.invalidate_system_prompt)
      3. every live engine's cached "skills" layer
         (graphs.chat_graph._ENGINES -> ContextEngine.invalidate_layer)

    Step 3 is required, not dead code: "skills" is deliberately NOT in
    layer_policy.VOLATILE_LAYERS (only git_context is). Every step is
    best-effort — invalidation must never break the mutation that
    triggered it (D17 fail-open). Cross-process note: a CLI run in another
    process cannot invalidate the app; the app re-syncs on its next hub op
    or restart. The bridge and the agent tools mutate in-process, so for
    them this seam is complete.
    """
    cleared: dict = {"index": False, "views": 0, "engines": 0}
    try:
        from src.prompts.hermes.skills_index import clear_skills_system_prompt_cache
        from src.prompts.hermes.view import crusor_home
        clear_skills_system_prompt_cache(clear_snapshot=True, home=crusor_home())
        cleared["index"] = True
    except Exception:
        pass
    try:
        from src.prompts.hermes import session as prompt_session
        from src.prompts.hermes.system_prompt import invalidate_system_prompt
        for view in list(getattr(prompt_session, "_views", {}).values()):
            try:
                invalidate_system_prompt(view)
                cleared["views"] += 1
            except Exception:
                continue
    except Exception:
        pass
    try:
        from src.graphs import chat_graph
        for engine in list(getattr(chat_graph, "_ENGINES", {}).values()):
            try:
                engine.invalidate_layer("skills")
                cleared["engines"] += 1
            except Exception:
                continue
    except Exception:
        pass
    return cleared


def probe_connectors(workspace: str = "") -> dict:
    """Live connector status for the hub dialog's Connectors tab — what is
    ACTUALLY reachable right now, probed cheaply (file reads, env checks,
    shutil.which, module presence — never a process spawn or network call:
    this runs every time the tab opens). The panel is a pure view; the
    engine owns the truth (same rule as skills_manifest)."""
    import importlib.util

    rows: list[dict] = []

    # MCP — real servers come from <workspace>/.crusorai/mcp.json (the same
    # file mcp_client runs); parse it directly, never initialize clients.
    servers: list[str] = []
    mcp_detail = "no .crusorai/mcp.json in this workspace yet"
    if workspace:
        try:
            from src.tools.mcp_client import mcp_config_path
            raw = json.loads(mcp_config_path(workspace).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = {}
        except Exception:
            raw = None
        if raw is None:
            rows.append({
                "id": "mcp", "label": "MCP (Model Context Protocol)",
                "desc": "external tool servers", "status": "setup",
                "detail": ".crusorai/mcp.json exists but is not valid JSON",
                "hint": "say \"list my MCP servers\" in chat once the file parses",
            })
            raw = {}
        else:
            for sname, spec in (raw.get("servers") or {}).items():
                if isinstance(spec, dict) and spec.get("enabled") is not False and spec.get("command"):
                    servers.append(str(sname))
            if servers:
                mcp_detail = f"{len(servers)} server(s): {', '.join(servers)}"
    if not any(r.get("id") == "mcp" for r in rows):
        if not workspace:
            mcp_detail = "open a workspace folder to configure MCP servers"
        rows.append({
            "id": "mcp", "label": "MCP (Model Context Protocol)",
            "desc": "external tool servers",
            "status": "connected" if servers else "setup",
            "detail": mcp_detail,
            "servers": servers,
            "hint": "add servers to <workspace>/.crusorai/mcp.json, or say \"list my MCP servers\" in chat",
        })

    # GitHub — gh CLI on PATH, else a token env.
    gh = shutil.which("gh")
    if gh:
        rows.append({"id": "github", "label": "GitHub connector", "desc": "PRs and issues",
                     "status": "connected", "detail": f"gh CLI found ({gh})",
                     "hint": "say \"open the PR reviews for this repo\""})
    elif os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        rows.append({"id": "github", "label": "GitHub connector", "desc": "PRs and issues",
                     "status": "connected", "detail": "token auth found in environment",
                     "hint": "say \"open the PR reviews for this repo\""})
    else:
        rows.append({"id": "github", "label": "GitHub connector", "desc": "PRs and issues",
                     "status": "setup", "detail": "gh CLI not on PATH and no GH_TOKEN set",
                     "hint": "install gh (or set GH_TOKEN) — then say \"open the PR reviews for this repo\""})

    # Browser — the stack module present in this engine env.
    browser = importlib.util.find_spec("camoufox") or importlib.util.find_spec("playwright")
    rows.append({
        "id": "browser", "label": "Browser connector", "desc": "real-browser verification",
        "status": "connected" if browser else "setup",
        "detail": "browser stack module present" if browser else "browser stack module not found in this engine env",
        "hint": "say \"verify the UI works\" — Crusor drives a real browser and checks the page",
    })

    # DB — configured via environment (DATABASE_URL / PGHOST / POSTGRES_HOST).
    if os.environ.get("DATABASE_URL") or os.environ.get("PGHOST") or os.environ.get("POSTGRES_HOST"):
        rows.append({"id": "db", "label": "DB connector", "desc": "postgres / sqlite",
                     "status": "connected", "detail": "database connection found in environment",
                     "hint": "say \"query the users table\" — guarded reads, mutations ask first"})
    else:
        rows.append({"id": "db", "label": "DB connector", "desc": "postgres / sqlite",
                     "status": "setup", "detail": "no DATABASE_URL / PGHOST in environment",
                     "hint": "set DATABASE_URL to connect — sqlite needs no server; mutations always ask first"})

    # Terminal — the guarded shell ships with every session.
    rows.append({"id": "terminal", "label": "Terminal connector", "desc": "guarded shell access",
                 "status": "connected", "detail": "wired into every session",
                 "hint": "run_terminal with approval gates — dangerous commands ask first"})
    return {"ok": True, "connectors": rows}


def connector_attach(workspace: str, name: str, command: str, args: list[str] | None = None) -> dict:
    """Attach a custom MCP server: merge {command, args} into the
    workspace's .crusorai/mcp.json (the file/folder is created when
    missing). The panel only sends the form — the engine owns the file.
    Takes effect next session (mcp_client initializes servers per
    session, a dead server never blocks the others)."""
    from src.tools.mcp_client import mcp_config_path
    ws = (workspace or "").strip()
    if not ws:
        return {"ok": False, "error": "open a workspace folder first — server config lives in <workspace>/.crusorai/mcp.json"}
    cname = (name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", cname):
        return {"ok": False, "error": "server name must start with a letter or digit (letters, digits, . _ - only)"}
    cmd = (command or "").strip()
    if not cmd:
        return {"ok": False, "error": "a command is required, e.g. npx -y @modelcontextprotocol/server-filesystem ~/docs"}
    path = mcp_config_path(ws)
    raw: dict = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"ok": False, "error": ".crusorai/mcp.json is not valid JSON — fix or remove it first"}
    if not isinstance(raw, dict):
        raw = {}
    servers = raw.setdefault("servers", {})
    if not isinstance(servers, dict):
        return {"ok": False, "error": '.crusorai/mcp.json has a non-object "servers" — fix it first'}
    if cname in servers:
        return {"ok": False, "error": f"'{cname}' is already attached — detach it first"}
    servers[cname] = {"command": cmd, "args": [str(a) for a in (args or [])]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    res = probe_connectors(ws)
    res["attached"] = cname
    return res


def connector_detach(workspace: str, name: str) -> dict:
    """Detach a custom MCP server: remove its entry from the workspace's
    .crusorai/mcp.json and re-probe."""
    from src.tools.mcp_client import mcp_config_path
    ws = (workspace or "").strip()
    cname = (name or "").strip()
    if not ws or not cname:
        return {"ok": False, "error": "connector_detach needs a workspace and a server name"}
    path = mcp_config_path(ws)
    if not path.exists():
        return {"ok": False, "error": "no .crusorai/mcp.json in this workspace"}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "error": ".crusorai/mcp.json is not valid JSON — fix or remove it first"}
    servers = raw.get("servers") or {}
    if cname not in servers:
        return {"ok": False, "error": f"'{cname}' is not attached"}
    servers.pop(cname)
    raw["servers"] = servers
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    res = probe_connectors(ws)
    res["detached"] = cname
    return res


def create_user_skill(
    name: str,
    instruction: str,
    triggers: list[str] | None = None,
    description: str = "",
    *,
    manager: SkillManager | None = None,
) -> dict:
    """Create (or update by name) a skill from the hub dialog's Create box —
    the foreground user path (skill_manage's agent loop is the other one).
    Non-coder friendly: the name is normalized (spaces -> hyphens, lower),
    and empty triggers are derived from the name's words so the skill still
    auto-activates. The panel sends the text; the engine owns the store."""
    mgr = _manager(manager)
    raw = (name or "").strip().lower()
    norm = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")
    if not norm:
        return {"ok": False, "error": "a skill name is required (letters, numbers, hyphens)"}
    norm = norm[:64]
    body = (instruction or "").strip()
    if len(body) < 20:
        return {"ok": False, "error": "the skill body is too short — describe when to use it and the steps (at least a sentence or two)"}
    trig = [t.strip().lower() for t in (triggers or []) if t.strip()]
    if not trig:
        trig = [w for w in norm.split("-") if len(w) > 2] or [norm]
    existing = next((s for s in mgr.list_skills() if s.get("name") == norm), None)
    if existing and existing.get("created_by") == "bundled":
        return {"ok": False, "error": f"'{norm}' is a bundled engine skill — bundled skills are read-only; pick another name"}
    desc = (description or "").strip()[:120]
    mgr.add_skill(norm, trig, body, created_by="user", pinned=False, description=desc)
    return {
        "ok": True,
        "skill": norm,
        "updated": existing is not None,
        "triggers": trig,
    }


def handle_hub_op(
    op: str = "",
    frame: dict | None = None,
    *,
    manager: SkillManager | None = None,
    catalog: dict | None = None,
    hub_root: str | Path | None = None,
    fetcher: Callable[[str], bytes] | None = None,
    ref_resolver: Callable[[str, str, str], str | None] | None = None,
) -> dict:
    """Consolidated Skills Hub op dispatcher — ONE function behind every
    surface (bridge envelope, CLI, tests).

    Ops:
      list    — hub-installed skills + update hints (list_hub)
      search  — curated catalog search (query, category)
      install — install/upgrade a source (source, pick)
      update  — update one (name) or every outdated hub skill
      remove  — uninstall a hub skill (name)
      all     — every installed skill (any origin), trimmed rows for UI
      toggle  — enable/disable any installed skill (name, enabled)
      manifest — the exact SKILLS INDEX text injected into the system prompt
                 (skills_manifest(), single source of truth — the Manager's
                 "what the model sees" pane renders this string verbatim)
      connectors — live integration status (MCP servers from the workspace's
                 .crusorai/mcp.json, gh/token, browser stack, DB env, terminal)
                 for the hub dialog's Connectors tab; probed cheaply, never spawned
      connector_attach — merge a custom MCP server (name, command, args) into
                 the workspace's .crusorai/mcp.json (creates the file)
      connector_detach — remove an MCP server entry from that file
      skill_create — create/update a USER skill from the dialog's Create box
                 (name normalized, triggers derived from the name when absent)

    Every op returns a dict with an `ok` flag; unknown ops fail with a
    message naming the valid set. Errors never raise (skills-layer D17).
    """
    f = dict(frame or {})
    clean = (op or str(f.get("op") or "list")).strip().lower()
    name = str(f.get("name") or "").strip()
    mgr = _manager(manager)
    # Injectable pipeline (catalog/hub_root/fetcher/ref_resolver) keeps the
    # whole op matrix hermetic — tests and embedded hosts pin them; the
    # bridge and CLI pass nothing and get the real network path.
    net: dict = {"hub_root": hub_root, "fetcher": fetcher, "ref_resolver": ref_resolver}

    if clean == "list":
        return list_hub(catalog=catalog, manager=mgr, hub_root=hub_root)
    if clean == "catalog":
        cat = catalog if catalog is not None else load_catalog()
        if not cat.get("ok"):
            return cat
        return {"ok": True, "results": cat.get("entries", [])}
    if clean == "search":
        cat = catalog if catalog is not None else load_catalog()
        if not cat.get("ok"):
            return cat
        return search_catalog(cat, str(f.get("query") or ""), str(f.get("category") or ""))
    if clean == "install":
        res = install_skill(
            str(f.get("source") or ""), pick=str(f.get("pick") or ""),
            catalog=catalog, manager=mgr, **net,
        )
        if res.get("ok"):
            res["invalidated"] = notify_skills_changed()
        return res
    if clean == "update":
        if name:
            res = update_hub_skill(name, catalog=catalog, manager=mgr, **net)
            if res.get("ok") and res.get("updated"):
                res["invalidated"] = notify_skills_changed()
            return res
        updated: list[dict] = []
        changed = False
        for row in list_hub(catalog=catalog, manager=mgr, hub_root=hub_root).get("installed", []):
            if row.get("update_available"):
                r = update_hub_skill(str(row["name"]), catalog=catalog, manager=mgr, **net)
                updated.append(r)
                changed = changed or bool(r.get("ok") and r.get("updated"))
        if changed:
            notify_skills_changed()
        return {"ok": True, "updated": updated}
    if clean == "remove":
        res = uninstall_skill(name, manager=mgr, hub_root=hub_root)
        if res.get("ok"):
            res["invalidated"] = notify_skills_changed()
        return res
    if clean == "all":
        rows: list[dict] = []
        for s in mgr.list_skills():
            src = s.get("source") or {}
            rows.append({
                "name": str(s.get("name", "")),
                "description": str(s.get("description", "") or ""),
                "origin": str(src.get("kind") or s.get("created_by") or "user"),
                "enabled": bool(s.get("enabled", True)),
                "pinned": bool(s.get("pinned", False)),
                "state": str(s.get("state", "active")),
                "use_count": int(s.get("use_count", 0)),
                "triggers": [str(x) for x in (s.get("triggers") or [])][:8],
            })
        return {"ok": True, "skills": rows}
    if clean == "toggle":
        if not name:
            return _fail("toggle needs a skill name")
        enabled = f.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() not in ("off", "0", "false", "no", "disabled")
        if not mgr.toggle_skill(name, bool(enabled)):
            return _fail(f"no skill named {name!r} is installed")
        return {"ok": True, "name": name, "enabled": bool(enabled),
                "invalidated": notify_skills_changed()}
    if clean == "manifest":
        return {"ok": True, "manifest": mgr.skills_manifest()}
    if clean == "connectors":
        return probe_connectors(str(f.get("workspace") or ""))
    if clean == "connector_attach":
        return connector_attach(
            str(f.get("workspace") or ""), str(f.get("name") or ""),
            str(f.get("command") or ""), [str(a) for a in (f.get("args") or [])])
    if clean == "connector_detach":
        return connector_detach(str(f.get("workspace") or ""), str(f.get("name") or ""))
    if clean == "skill_create":
        res = create_user_skill(
            str(f.get("name") or ""), str(f.get("instruction") or ""),
            [str(t) for t in (f.get("triggers") or [])],
            str(f.get("description") or ""), manager=mgr,
        )
        if res.get("ok"):
            res["invalidated"] = notify_skills_changed()
        return res

    return _fail(
        f"unknown skills_hub op {clean!r} — valid ops: list, catalog, search, "
        "install, update, remove, all, toggle, manifest, connectors, "
        "connector_attach, connector_detach, skill_create"
    )


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
