"""Crusor Skills Hub: search -> install -> provenance -> uninstall.

Pins the full pipeline end to end, with ZERO network (fetcher and ref
resolver are injected fakes):

  - source grammar: catalog name / owner/repo / @sha / :subdir / github URL
  - the shipped catalog is valid (every entry pinned to a full 40-char SHA —
    a branch or tag pin must never pass validation)
  - keyword search over the catalog (all-tokens-match, category filter)
  - install from the catalog AND from a direct owner/repo@sha source lands
    the SKILL.md body in the user's store (pinned, provenance-footer,
    frontmatter triggers), copies support files into the hub root, and
    writes the provenance ledger
  - fail-closed ref resolution: a symbolic ref that cannot resolve to an
    exact SHA is refused — installs are SHA-anchored, period
  - extraction safety: traversal members, symlink members, byte caps and
    file-count caps are all rejected
  - collision guard: a different existing source is never overwritten; the
    SAME hub source upgrades cleanly
  - uninstall removes store entry + folder + ledger, and refuses bundled /
    non-hub skills
  - the hub tools are bound in chat_graph's _TOOLS_BY_NAME and ride the
    always-on skills waist in toolsets (a resolver-named tool the graph
    cannot call is a phantom)
  - branding hygiene: the new hub surface carries Crusor naming only
"""
import io
import json
import tarfile
from pathlib import Path

import pytest

from src.agents.skill_manager import SkillManager
from src.agents import skills_hub as hub

_REPO = Path(__file__).resolve().parents[2]
_SHA_A = "a" * 40
_SHA_B = "b" * 40
_SHA_C = "c" * 40

SKILL_BODY = """# Frontend Design

Make deliberate, opinionated choices about palette, typography, and layout.
"""


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _make_tar(entries: dict[str, bytes], links: list[tuple[str, str]] | None = None) -> bytes:
    """Build an in-memory tarball: {path: content} plus optional symlinks."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path, data in entries.items():
            ti = tarfile.TarInfo(name=path)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        for src, dst in links or []:
            ti = tarfile.TarInfo(name=src)
            ti.type = tarfile.SYMTYPE
            ti.linkname = dst
            tf.addfile(ti)
    return buf.getvalue()


def _skill_tar(
    root: str = "repo-x",
    sub: str = "skills/frontend-design",
    sha: str = _SHA_A,
    name: str = "frontend-design",
    extra_files: dict[str, bytes] | None = None,
) -> bytes:
    entries = {
        f"{root}/{sub}/SKILL.md": (
            "---\n"
            f"name: {name}\n"
            "description: Distinctive visual design guidance for new UI.\n"
            "keywords: [design, ui, frontend]\n"
            "---\n\n" + SKILL_BODY
        ).encode("utf-8"),
        f"{root}/{sub}/references/palette.md": b"# Palette\n",
    }
    entries.update({f"{root}/{k}": v for k, v in (extra_files or {}).items()})
    return _make_tar(entries)


def _fake_fetcher(archives: dict[str, bytes]):
    def fetch(url: str) -> bytes:
        for key, blob in archives.items():
            if key in url:
                return blob
        raise AssertionError(f"unexpected fetch: {url}")
    return fetch


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Throwaway manager + hub root + catalog, wired into the module."""
    manager = SkillManager(storage_path=str(tmp_path / "skills.json"))
    hub_root = tmp_path / "hub"
    monkeypatch.setattr("src.agents.skill_manager.skill_manager", manager)
    catalog = {
        "ok": True,
        "entries": [
            {
                "name": "frontend-design",
                "repo": "https://github.com/anthropics/skills",
                "sha": _SHA_A,
                "subdir": "skills/frontend-design",
                "description": "Distinctive visual design guidance.",
                "category": "ui-design",
                "trust": "curated",
            },
        ],
        "rejected": [],
    }
    return {
        "manager": manager,
        "hub_root": hub_root,
        "catalog": catalog,
        "archives": {
            _SHA_A: _skill_tar(sha=_SHA_A),
            _SHA_B: _skill_tar(sha=_SHA_B),
            _SHA_C: _skill_tar(sha=_SHA_C),
        },
    }


def _install(env, source: str, **kw) -> dict:
    return hub.install_skill(
        source,
        catalog=env["catalog"],
        manager=env["manager"],
        hub_root=env["hub_root"],
        fetcher=_fake_fetcher(env["archives"]),
        **kw,
    )


# ---------------------------------------------------------------------------
# Source grammar
# ---------------------------------------------------------------------------

class TestParseSource:
    def test_catalog_name(self):
        out = hub.parse_source("Frontend-Design")
        assert out["ok"] and out["kind"] == "catalog" and out["name"] == "frontend-design"

    def test_owner_repo(self):
        out = hub.parse_source("vercel-labs/agent-skills")
        assert out["ok"] and out["kind"] == "repo" and out["ref"] == "" and out["subdir"] == ""

    def test_owner_repo_sha_subdir(self):
        out = hub.parse_source(f"owner/repo@{_SHA_A}:skills/x")
        assert out["ok"] and out["ref"] == _SHA_A and out["subdir"] == "skills/x"

    def test_github_url_with_tree(self):
        out = hub.parse_source(f"https://github.com/owner/repo/tree/{_SHA_A}/skills/x")
        assert out["ok"] and out["owner"] == "owner" and out["subdir"] == "skills/x"

    def test_non_github_host_rejected(self):
        assert not hub.parse_source("https://gitlab.com/owner/repo")["ok"]

    def test_empty_rejected(self):
        assert not hub.parse_source("   ")["ok"]


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

class TestCatalog:
    def test_shipped_catalog_is_valid(self):
        out = hub.load_catalog()
        assert out["ok"], out.get("error")
        assert len(out["entries"]) >= 8
        assert out["rejected"] == []
        for e in out["entries"]:
            assert hub._SHA_RE.match(e["sha"]), f"{e['name']} pin is not a full SHA"
            assert e["trust"] == "curated"
            assert e["description"], f"{e['name']} has no description"

    def test_bad_entries_dropped_with_reasons(self):
        p = Path(_REPO) / "skills" / "catalog.json"
        raw = json.loads(p.read_text(encoding="utf-8"))
        raw["entries"] = [
            {"name": "ok-skill", "repo": "https://github.com/o/r", "sha": _SHA_A,
             "description": "d", "category": "c", "trust": "curated"},
            {"name": "bad-sha", "repo": "https://github.com/o/r", "sha": "abc123",
             "description": "d", "category": "c", "trust": "curated"},
            {"name": "bad-repo", "repo": "https://example.com/o/r", "sha": _SHA_A,
             "description": "d", "category": "c", "trust": "curated"},
            {"name": "ok-skill", "repo": "https://github.com/o/r", "sha": _SHA_B,
             "description": "dup", "category": "c", "trust": "curated"},
        ]
        tmp = Path(_REPO) / "skills" / ".hub-test-catalog.json"
        tmp.write_text(json.dumps(raw), encoding="utf-8")
        try:
            out = hub.load_catalog(tmp)
        finally:
            tmp.unlink()
        assert out["ok"]
        assert [e["name"] for e in out["entries"]] == ["ok-skill"]
        assert len(out["rejected"]) == 3

    def test_search_all_tokens_and_category(self):
        cat = hub.load_catalog()
        res = hub.search_catalog(cat, "react performance")
        assert any(e["name"] == "react-best-practices" for e in res["results"])
        res = hub.search_catalog(cat, "", category="security")
        names = [e["name"] for e in res["results"]]
        assert "c-review" in names and "frontend-design" not in names
        res = hub.search_catalog(cat, "zzzznomatch")
        assert res["ok"] and res["results"] == []


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

class TestInstall:
    def test_install_from_catalog_end_to_end(self, env):
        res = _install(env, "frontend-design")
        assert res["ok"], res.get("error")
        assert res["name"] == "frontend-design"
        assert res["sha"] == _SHA_A and res["trust"] == "curated"

        # folder materialized with support files
        dest = Path(res["folder"])
        assert (dest / "SKILL.md").is_file()
        assert (dest / "references" / "palette.md").is_file()

        # store entry: pinned, user-created, body + provenance footer
        skill = next(s for s in env["manager"].list_skills() if s["name"] == "frontend-design")
        assert skill["created_by"] == "user" and skill["pinned"] is True
        assert SKILL_BODY.strip() in skill["instruction"]
        assert f"github.com/anthropics/skills @ {_SHA_A[:12]}" in skill["instruction"]
        assert skill["triggers"] == ["design", "ui", "frontend"]
        assert skill["description"].startswith("Distinctive visual design")
        assert skill["source"]["kind"] == "hub" and skill["source"]["sha"] == _SHA_A

        # provenance ledger written
        ledger = json.loads((env["hub_root"] / "provenance.json").read_text())
        assert "frontend-design" in ledger["skills"]

    def test_install_direct_repo_with_full_sha(self, env):
        res = _install(env, f"owner/repo@{_SHA_A}")
        assert res["ok"], res.get("error")
        assert res["repo"] == "owner/repo" and res["sha"] == _SHA_A

    def test_symbolic_ref_fails_closed_without_resolver(self, env):
        res = _install(env, "owner/repo@main")
        assert not res["ok"]
        assert "SHA" in res["error"]

    def test_symbolic_ref_resolves_then_installs(self, env):
        res = hub.install_skill(
            "owner/repo@main",
            catalog=env["catalog"],
            manager=env["manager"],
            hub_root=env["hub_root"],
            fetcher=_fake_fetcher(env["archives"]),
            ref_resolver=lambda o, r, ref: _SHA_B,
        )
        assert res["ok"] and res["sha"] == _SHA_B

    def test_multi_skill_source_requires_pick(self, env):
        env["archives"][_SHA_A] = _make_tar({
            "r/skills/one/SKILL.md": b"---\nname: one\n---\n\nBody one.\n",
            "r/skills/two/SKILL.md": b"---\nname: two\n---\n\nBody two.\n",
        })
        res = _install(env, f"owner/repo@{_SHA_A}")
        assert not res["ok"] and "multiple skills" in res["error"]
        res = _install(env, f"owner/repo@{_SHA_A}", pick="two")
        assert res["ok"] and res["name"] == "two"

    def test_no_skill_md_rejected(self, env):
        env["archives"][_SHA_A] = _make_tar({"r/readme.txt": b"not a skill"})
        res = _install(env, f"owner/repo@{_SHA_A}")
        assert not res["ok"] and "no SKILL.md" in res["error"]

    def test_upgrade_same_source_allowed(self, env):
        first = _install(env, "frontend-design")
        assert first["ok"] and first["upgraded"] is False
        second = _install(env, "frontend-design")
        assert second["ok"] and second["upgraded"] is True
        skill = next(s for s in env["manager"].list_skills() if s["name"] == "frontend-design")
        assert skill["source"]["sha"] == _SHA_A

    def test_collision_with_foreign_source_refused(self, env):
        env["manager"].add_skill(
            "frontend-design", ["design"], "hand-written workflow", created_by="user"
        )
        res = _install(env, "frontend-design")
        assert not res["ok"] and "already exists" in res["error"]
        # the hand-written body is untouched
        skill = next(s for s in env["manager"].list_skills() if s["name"] == "frontend-design")
        assert skill["instruction"] == "hand-written workflow"

    def test_subdir_escape_rejected(self, env):
        res = _install(env, f"owner/repo@{_SHA_A}:../../etc")
        assert not res["ok"]


# ---------------------------------------------------------------------------
# Extraction safety
# ---------------------------------------------------------------------------

class TestExtractionSafety:
    def test_traversal_member_rejected(self, env):
        env["archives"][_SHA_A] = _make_tar({"r/ok.txt": b"x", "../evil.txt": b"pwned"})
        res = _install(env, f"owner/repo@{_SHA_A}")
        assert not res["ok"] and "unsafe member" in res["error"]

    def test_escaping_symlink_rejected(self, env):
        env["archives"][_SHA_A] = _make_tar(
            {"r/skills/x/SKILL.md": SKILL_BODY.encode()},
            links=[("r/link", "/etc/passwd")],
        )
        res = _install(env, f"owner/repo@{_SHA_A}")
        assert not res["ok"] and "symlink rejected" in res["error"]

    def test_contained_symlink_materialized_as_copy(self, env):
        env["archives"][_SHA_A] = _make_tar(
            {
                "r/skills/frontend-design/SKILL.md": (
                    "---\nname: frontend-design\ndescription: d\n---\n\n" + SKILL_BODY
                ).encode(),
                "r/skills/frontend-design/README.md": b"# read me",
            },
            links=[("r/skills/frontend-design/CLAUDE.md", "README.md")],
        )
        res = _install(env, f"owner/repo@{_SHA_A}")
        assert res["ok"], res.get("error")
        link_copy = Path(res["folder"]) / "CLAUDE.md"
        assert link_copy.is_file() and link_copy.read_bytes() == b"# read me"

    def test_byte_cap_enforced(self, env, monkeypatch):
        monkeypatch.setattr(hub, "_MAX_ARCHIVE_BYTES", 10)
        res = _install(env, "frontend-design")
        assert not res["ok"] and "cap" in res["error"]

    def test_file_count_cap_enforced(self, env, monkeypatch):
        monkeypatch.setattr(hub, "_MAX_SKILL_FILES", 1)
        res = _install(env, "frontend-design")  # SKILL.md + references/palette.md
        assert not res["ok"] and "cap" in res["error"]

    def test_corrupt_tarball_rejected(self, env):
        env["archives"][_SHA_A] = b"this is not a tarball"
        res = _install(env, f"owner/repo@{_SHA_A}")
        assert not res["ok"] and "tarball" in res["error"]


# ---------------------------------------------------------------------------
# Uninstall + list
# ---------------------------------------------------------------------------

class TestUninstallAndList:
    def test_uninstall_removes_store_folder_and_ledger(self, env):
        _install(env, "frontend-design")
        res = hub.uninstall_skill(
            "frontend-design", manager=env["manager"], hub_root=env["hub_root"]
        )
        assert res["ok"], res.get("error")
        assert env["manager"].list_skills() == [] or all(
            s["name"] != "frontend-design" for s in env["manager"].list_skills()
        )
        assert not (env["hub_root"] / "skills" / "frontend-design").exists()
        ledger = json.loads((env["hub_root"] / "provenance.json").read_text())
        assert "frontend-design" not in ledger["skills"]

    def test_uninstall_refuses_bundled(self, env):
        env["manager"]._load_bundled_skills()
        res = hub.uninstall_skill(
            "media-sourcing", manager=env["manager"], hub_root=env["hub_root"]
        )
        assert not res["ok"] and "bundled" in res["error"]

    def test_uninstall_refuses_non_hub_user_skill(self, env):
        env["manager"].add_skill("my-own", ["x"], "body", created_by="user")
        res = hub.uninstall_skill("my-own", manager=env["manager"], hub_root=env["hub_root"])
        assert not res["ok"] and "not installed via the hub" in res["error"]

    def test_list_reports_update_available(self, env):
        _install(env, "frontend-design")  # pinned at _SHA_A
        env["catalog"]["entries"][0]["sha"] = _SHA_B  # catalog moved on
        out = hub.list_hub(manager=env["manager"], hub_root=env["hub_root"])
        rows = out["installed"]
        assert len(rows) == 1
        assert rows[0]["update_available"] is True
        assert rows[0]["trust"] == "curated"


# ---------------------------------------------------------------------------
# Binding + branding hygiene
# ---------------------------------------------------------------------------

class TestBindingAndHygiene:
    def test_hub_tools_bound_in_graph_and_toolsets(self):
        from src.graphs.chat_graph import _TOOLS_BY_NAME
        from src.tools.toolsets import all_known_tool_names, resolve_toolset_names
        from src.tools.skill_hub_tools import HUB_TOOLS

        names = {"hub_search", "hub_install", "hub_update", "hub_list", "hub_remove"}
        assert names <= set(_TOOLS_BY_NAME), "hub tools must be callable by the graph"
        assert names <= set(all_known_tool_names())
        bound = set(resolve_toolset_names("coding"))
        assert names <= bound, "hub tools must ride the always-on skills waist"
        assert {t.name for t in HUB_TOOLS} == names

    def test_no_vendor_branding_in_new_surface(self):
        """The hub is Crusor surface: no third-party agent vendor names in
        code or catalog metadata (source repo URLs are pointers, not branding,
        and are allowed to name their own owners)."""
        forbidden = ("hermes", "cursor", "nousresearch")
        internal_paths = ("src/prompts/hermes", "src.prompts.hermes", "prompts.hermes")
        files = [
            _REPO / "src" / "agents" / "skills_hub.py",
            _REPO / "src" / "tools" / "skill_hub_tools.py",
            _REPO / "src" / "prompts" / "oneshot.py",
        ]
        for f in files:
            text = f.read_text(encoding="utf-8").lower()
            # the prompts package's INTERNAL module name is repo plumbing,
            # not branding — strip it before scanning (field 2026-10-01:
            # notify_skills_changed legitimately imports those modules)
            for path in internal_paths:
                text = text.replace(path, "<prompts>")
            for word in forbidden:
                assert word not in text, f"vendor name {word!r} found in {f.name}"
        cat = json.loads((_REPO / "skills" / "catalog.json").read_text(encoding="utf-8"))
        for entry in cat["entries"]:
            blob = json.dumps(entry).lower()
            for word in forbidden:
                assert word not in blob, f"vendor name {word!r} in catalog entry {entry['name']}"

    def test_add_skill_source_roundtrip(self, tmp_path):
        manager = SkillManager(storage_path=str(tmp_path / "skills.json"))
        manager.add_skill("s1", ["t"], "body", source={"kind": "hub", "sha": _SHA_A})
        reloaded = SkillManager(storage_path=str(tmp_path / "skills.json"))
        skill = next(s for s in reloaded.list_skills() if s["name"] == "s1")
        assert skill["source"]["sha"] == _SHA_A

        # legacy call shape (no source) still works and never fabricates one
        manager.add_skill("s2", ["t"], "body")
        skill2 = next(s for s in manager.list_skills() if s["name"] == "s2")
        assert "source" not in skill2

# ---------------------------------------------------------------------------
# Update (Phase 2: catalog-pinned upgrades)
# ---------------------------------------------------------------------------

class TestUpdate:
    def test_already_at_pin_is_a_clean_noop(self, env):
        _install(env, "frontend-design")
        res = hub.update_hub_skill(
            "frontend-design",
            catalog=env["catalog"],
            manager=env["manager"],
            hub_root=env["hub_root"],
            fetcher=_fake_fetcher(env["archives"]),
        )
        assert res["ok"] and res["updated"] is False

    def test_catalog_bump_upgrades_same_source(self, env):
        _install(env, "frontend-design")  # at _SHA_A
        env["catalog"]["entries"][0]["sha"] = _SHA_B  # curated pin moves
        res = hub.update_hub_skill(
            "frontend-design",
            catalog=env["catalog"],
            manager=env["manager"],
            hub_root=env["hub_root"],
            fetcher=_fake_fetcher(env["archives"]),
        )
        assert res["ok"], res.get("error")
        assert res["updated"] is True
        assert res["from_sha"] == _SHA_A and res["to_sha"] == _SHA_B
        skill = next(s for s in env["manager"].list_skills() if s["name"] == "frontend-design")
        assert skill["source"]["sha"] == _SHA_B

    def test_not_in_catalog_reported_not_touched(self, env):
        _install(env, f"owner/repo@{_SHA_A}")
        res = hub.update_hub_skill(
            "frontend-design",
            catalog=env["catalog"],
            manager=env["manager"],
            hub_root=env["hub_root"],
            fetcher=_fake_fetcher(env["archives"]),
        )
        # the direct-repo install's frontmatter name is "frontend-design" (same
        # tarball), and the catalog entry points at a DIFFERENT repo, so the
        # catalog lookup misses -> refused cleanly
        assert not res["ok"] and "not in the" in res["error"]

    def test_unknown_and_non_hub_names_refused(self, env):
        res = hub.update_hub_skill(
            "ghost", catalog=env["catalog"], manager=env["manager"], hub_root=env["hub_root"]
        )
        assert not res["ok"] and "no skill named" in res["error"]
        env["manager"].add_skill("manual", ["x"], "body", created_by="user")
        res = hub.update_hub_skill(
            "manual", catalog=env["catalog"], manager=env["manager"], hub_root=env["hub_root"]
        )
        assert not res["ok"] and "not installed via the hub" in res["error"]

    def test_tool_updates_all_pending_and_reports_clean(self, env, monkeypatch):
        from src.tools.skill_hub_tools import hub_update as hub_update_tool
        _install(env, "frontend-design")
        env["catalog"]["entries"][0]["sha"] = _SHA_B
        import src.tools.skill_hub_tools as tools_mod
        import src.agents.skill_manager as sm_mod
        monkeypatch.setattr(sm_mod, "skill_manager", env["manager"])

        def _hub():
            import functools, inspect
            from src.agents import skills_hub as real
            class _HubProxy:
                def __getattr__(self, item):
                    attr = getattr(real, item)
                    if not callable(attr):
                        return attr
                    @functools.wraps(attr)
                    def wrapper(*a, **kw):
                        kw.setdefault("catalog", env["catalog"])
                        kw.setdefault("manager", env["manager"])
                        kw.setdefault("hub_root", env["hub_root"])
                        try:
                            sig = inspect.signature(attr)
                            if "fetcher" in sig.parameters:
                                kw.setdefault("fetcher", _fake_fetcher(env["archives"]))
                        except (ValueError, TypeError):
                            pass
                        return attr(*a, **kw)
                    return wrapper
            return _HubProxy()
        monkeypatch.setattr(tools_mod, "_hub", _hub)
        out = hub_update_tool.invoke({"name": ""})
        assert "updated" in out and _SHA_B[:12] in out
        # second run: everything at pin -> clean all-green message
        out2 = hub_update_tool.invoke({"name": ""})
        assert "already at the catalog-pinned" in out2

# ---------------------------------------------------------------------------
# Monorepo cap vs subdir (field 2026-09-30: trailofbits/skills has 2117
# entries; the whole-repo cap fired before the subdir filter and blocked
# `install c-review` — the cap guards what we EXTRACT, not repo size)
# ---------------------------------------------------------------------------

class TestMonorepoSubdir:
    def _monorepo_tar(self) -> bytes:
        entries = {
            f"trailofbits-skills-{_SHA_A}/plugins/c-review/skills/c-review/SKILL.md": (
                "---\nname: c-review\ndescription: C/C++ security review.\n"
                "keywords: [security, review]\n---\n\n" + SKILL_BODY
            ).encode(),
            f"trailofbits-skills-{_SHA_A}/plugins/c-review/skills/c-review/references/r.md": b"# ref",
        }
        for i in range(2010):
            entries[f"trailofbits-skills-{_SHA_A}/decoys/f{i:04d}.txt"] = b"x"
        return _make_tar(entries)

    def test_subdir_installs_from_a_repo_over_the_cap(self, env):
        env["archives"][_SHA_A] = self._monorepo_tar()
        res = _install(env, f"owner/repo@{_SHA_A}:plugins/c-review/skills/c-review")
        assert res["ok"], res.get("error")
        assert res["name"] == "c-review"
        dest = Path(res["folder"])
        assert sorted(q.name for q in dest.rglob("*") if q.is_file()) == ["SKILL.md", "r.md"]

    def test_whole_repo_over_cap_hints_the_subdir_form(self, env):
        env["archives"][_SHA_A] = self._monorepo_tar()
        res = _install(env, f"owner/repo@{_SHA_A}")
        assert not res["ok"]
        assert f"cap {hub._MAX_REPO_FILES}" in res["error"]
        assert "subdirectory" in res["error"]

    def test_subdir_missing_from_archive_is_a_clean_error(self, env):
        env["archives"][_SHA_A] = self._monorepo_tar()
        res = _install(env, f"owner/repo@{_SHA_A}:nope/missing")
        assert not res["ok"] and "not found in the archive" in res["error"]

# ---------------------------------------------------------------------------
# handle_hub_op — the ONE dispatcher behind the bridge envelope, CLI and UI
# ---------------------------------------------------------------------------

class TestHubOps:
    def test_every_surface_op_round_trips(self, env):
        _install(env, "frontend-design")
        def op(kind, **extra):
            return hub.handle_hub_op(
                kind, frame={"name": "frontend-design", **extra},
                catalog=env["catalog"], manager=env["manager"],
                hub_root=env["hub_root"], fetcher=_fake_fetcher(env["archives"]),
            )

        listed = op("list")
        assert listed["ok"] and listed["installed"][0]["name"] == "frontend-design"
        searched = op("search", query="design")
        assert searched["ok"] and any(e["name"] == "frontend-design" for e in searched["results"])
        updated = op("update", name="frontend-design")
        assert updated["ok"] and updated["updated"] is False
        removed = op("remove")
        assert removed["ok"] and removed["name"] == "frontend-design"

    def test_all_lists_every_origin_with_trimmed_rows(self, env):
        _install(env, "frontend-design")
        env["manager"].add_skill("hand-made", ["x"], "body", created_by="user")
        res = hub.handle_hub_op("all")
        assert res["ok"]
        rows = {r["name"]: r for r in res["skills"]}
        assert rows["frontend-design"]["origin"] == "hub"
        assert rows["hand-made"]["origin"] == "user"
        assert "instruction" not in rows["hand-made"]  # bodies stay out of UI rows
        assert rows["hand-made"]["enabled"] is True and rows["hand-made"]["use_count"] == 0

    def test_toggle_flips_and_persists(self, env):
        env["manager"].add_skill("togglable", ["x"], "body")
        res = hub.handle_hub_op("toggle", frame={"name": "togglable", "enabled": "off"})
        assert res["ok"] and res["enabled"] is False
        skill = next(s for s in env["manager"].list_skills() if s["name"] == "togglable")
        assert skill["enabled"] is False
        # string forms accepted; unknown names refused
        assert hub.handle_hub_op("toggle", frame={"name": "togglable", "enabled": "on"})["ok"]
        assert not hub.handle_hub_op("toggle", frame={"name": "ghost"})["ok"]

    def test_unknown_op_names_the_valid_set(self, env):
        res = hub.handle_hub_op("explode")
        assert not res["ok"] and "list, catalog, search, install, update, remove, all, toggle, manifest, connectors, "
        "connector_attach, connector_detach, skill_create" in res["error"]

    def test_connectors_op_reports_live_state(self, env, monkeypatch, tmp_path):
        """The Connectors tab is a pure view — the engine probes the REAL
        state (workspace mcp.json servers, gh/token, browser stack, DB env,
        terminal) cheaply, never spawning processes."""
        import json as _json
        ws = tmp_path / "ws"
        (ws / ".crusorai").mkdir(parents=True)
        (ws / ".crusorai" / "mcp.json").write_text(_json.dumps({
            "servers": {"filesystem": {"command": "npx"}, "off": {"command": "x", "enabled": False}},
        }), encoding="utf-8")
        for var in ("GH_TOKEN", "GITHUB_TOKEN", "DATABASE_URL", "PGHOST", "POSTGRES_HOST"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(hub.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)

        res = hub.handle_hub_op("connectors", frame={"workspace": str(ws)})
        assert res["ok"]
        by_id = {r["id"]: r for r in res["connectors"]}
        assert by_id["mcp"]["status"] == "connected"
        assert "filesystem" in by_id["mcp"]["detail"] and "off" not in by_id["mcp"]["detail"]
        assert by_id["github"]["status"] == "connected" and "gh" in by_id["github"]["detail"]
        assert by_id["db"]["status"] == "setup"
        assert by_id["terminal"]["status"] == "connected"

        monkeypatch.setenv("DATABASE_URL", "postgres://localhost/db")
        assert hub.handle_hub_op("connectors", frame={"workspace": str(ws)})["connectors"][-2]["status"] == "connected"

        # broken json is named honestly, never swallowed
        (ws / ".crusorai" / "mcp.json").write_text("{oops", encoding="utf-8")
        res3 = hub.handle_hub_op("connectors", frame={"workspace": str(ws)})
        mcp3 = next(r for r in res3["connectors"] if r["id"] == "mcp")
        assert mcp3["status"] == "setup" and "not valid JSON" in mcp3["detail"]

        # no workspace: still a full row set, mcp says what to do next
        res4 = hub.handle_hub_op("connectors", frame={})
        assert {r["id"] for r in res4["connectors"]} == {"mcp", "github", "browser", "db", "terminal"}
        assert "workspace" in res4["connectors"][0]["detail"]

    def test_connector_attach_and_detach_write_the_workspace_config(self, env, tmp_path):
        """Custom attachable connectors (field 2026-10-02): the dialog form
        reaches the engine, the engine owns .crusorai/mcp.json — merge on
        attach, removal on detach, probes refreshed in the same result."""
        import json as _json
        ws = tmp_path / "ws2"
        ws.mkdir()
        res = hub.handle_hub_op("connector_attach", frame={
            "workspace": str(ws), "name": "filesystem", "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "~/docs"],
        })
        assert res["ok"] and res["attached"] == "filesystem"
        cfg = _json.loads((ws / ".crusorai" / "mcp.json").read_text(encoding="utf-8"))
        assert cfg["servers"]["filesystem"]["command"] == "npx"
        assert cfg["servers"]["filesystem"]["args"] == ["-y", "@modelcontextprotocol/server-filesystem", "~/docs"]
        # the returned probe already reflects the attach
        mcp = next(r for r in res["connectors"] if r["id"] == "mcp")
        assert mcp["status"] == "connected" and "filesystem" in mcp["servers"]

        # duplicates refused, names validated, missing command refused
        dup = hub.handle_hub_op("connector_attach", frame={"workspace": str(ws), "name": "filesystem", "command": "x"})
        assert not dup["ok"] and "already attached" in dup["error"]
        bad = hub.handle_hub_op("connector_attach", frame={"workspace": str(ws), "name": "bad name!", "command": "x"})
        assert not bad["ok"] and "name" in bad["error"]
        nocmd = hub.handle_hub_op("connector_attach", frame={"workspace": str(ws), "name": "okname", "command": ""})
        assert not nocmd["ok"] and "command" in nocmd["error"]
        nows = hub.handle_hub_op("connector_attach", frame={"name": "x", "command": "y"})
        assert not nows["ok"] and "workspace" in nows["error"]

        # detach removes the entry and the probe flips back to setup
        det = hub.handle_hub_op("connector_detach", frame={"workspace": str(ws), "name": "filesystem"})
        assert det["ok"] and det["detached"] == "filesystem"
        cfg2 = _json.loads((ws / ".crusorai" / "mcp.json").read_text(encoding="utf-8"))
        assert "filesystem" not in cfg2["servers"]
        mcp2 = next(r for r in det["connectors"] if r["id"] == "mcp")
        assert mcp2["status"] == "setup"
        # detaching something absent fails honestly
        again = hub.handle_hub_op("connector_detach", frame={"workspace": str(ws), "name": "filesystem"})
        assert not again["ok"] and "not attached" in again["error"]

    def test_skill_create_adds_a_user_skill_from_the_dialog(self, env):
        """The Create box path: non-coder words -> engine normalization
        (spaces to hyphens), triggers derived from the name when the
        enhanced file had none, update-on-same-name, bundled refused."""
        body = "When the user says ship it, run the test suite, then build, then report go/no-go with the checklist output."
        res = hub.handle_hub_op("skill_create", frame={
            "name": "Ship It!", "instruction": body, "triggers": [],
            "description": "Run the ship checklist.",
        })
        assert res["ok"] and res["skill"] == "ship-it" and res["updated"] is False
        assert res["triggers"] == ["ship"]  # derived: name words longer than two chars
        assert isinstance(res["invalidated"], dict)  # invalidation seam summary
        skill = next(s for s in env["manager"].list_skills() if s["name"] == "ship-it")
        assert skill["created_by"] == "user"

        res2 = hub.handle_hub_op("skill_create", frame={
            "name": "ship-it",
            "instruction": "Longer replacement body for the ship checklist workflow, well over twenty characters.",
            "triggers": ["ship it"],
        })
        assert res2["ok"] and res2["updated"] is True and res2["triggers"] == ["ship it"]

        short = hub.handle_hub_op("skill_create", frame={"name": "tiny", "instruction": "too short"})
        assert not short["ok"] and "too short" in short["error"]
        noname = hub.handle_hub_op("skill_create", frame={"instruction": "x" * 50})
        assert not noname["ok"] and "name" in noname["error"]

    def test_catalog_op_returns_every_entry(self, env):
        res = hub.handle_hub_op("catalog", catalog=env["catalog"])
        assert res["ok"] and [e["name"] for e in res["results"]] == ["frontend-design"]

    def test_manifest_op_exposes_the_injected_skills_index(self, env):
        """The Manager's "what the model sees" pane must render the ENGINE's
        skills_manifest() verbatim — a TS re-build of the index would drift
        from the real system-prompt bytes silently."""
        _install(env, "frontend-design")
        env["manager"].add_skill("hand-made", ["x"], "body", created_by="user")
        env["manager"].toggle_skill("hand-made", False)
        res = hub.handle_hub_op("manifest")
        assert res["ok"] and isinstance(res["manifest"], str)
        # enabled hub skill shows with its triggers; the disabled one does not
        assert res["manifest"].startswith("=== SKILLS INDEX ===")
        assert "- **frontend-design** (" in res["manifest"]
        assert "hand-made" not in res["manifest"]
        # byte-identical to the function the prompt builder calls
        assert res["manifest"] == env["manager"].skills_manifest()
        # read-only: no skills-cache invalidation for a view op
        assert "invalidated" not in res

    def test_bridge_handles_hub_ops_before_session_resolution(self):
        """Field 2026-10-01: the skills_hub_op branch sat inside the
        session-scoped dispatcher, so a palette click on a fresh window (no
        chat bound) went through workspace/session resolution and silently
        stalled — the user saw 'nothing happened'. Hub ops are USER-level:
        the bridge must answer them BEFORE any session minting."""
        src = (_REPO / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
        handle = src.split("def handle(self, frame: dict)")[1]
        assert handle.index('if kind == "skills_hub_op":') < handle.index(
            'raw_workspace = frame.get("workspace")'
        ), "hub ops must be handled before workspace/session resolution"
        # and the branch must answer, not fall through
        branch = handle.split('if kind == "skills_hub_op":')[1].split("return True")[0]
        assert "handle_hub_op" in branch and "skills_hub_result" in branch

    def test_composer_plus_menu_and_in_panel_dialog(self):
        """Field 2026-10-02, rev 8 (owner flow, explicit: "+ -> menu bar
        option <select> -> Dialog box"): + opens the compact picker menu in
        the composer space — the exact anatomy of the Agent/Think pills —
        and choosing an option opens the hub dialog: the centered modal
        (dimmed backdrop over the pane) carrying the matching tab. The card
        ships its own CSS at runtime, mounts on document.body, inherits the
        panel theme from the anchor, and every var() carries a literal dark
        fallback. Data flows through skillsHubOp / oneshotRun — NEVER the
        top-center QuickPick."""
        browser = _REPO / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai" / "browser"
        renderer = (browser / "crusorAIRenderer.ts").read_text(encoding="utf-8")
        # the menu: + is a picker with the Agent/Think anatomy, options
        # open the dialog
        assert "crusorai-mode-picker crusorai-add-picker" in renderer
        assert "crusorai-mode-summary" in renderer and "crusorai-mode-menu" in renderer
        assert "crusorai-mode-option-copy" in renderer
        assert "entry.run(host, details)" in renderer
        assert "host.skillsHubOp === 'function'" in renderer
        # every direct-open / bespoke variant stays dead
        for dead in ("crusorai-add-menu", "crusorai-plus-summary", "openPlusMenu",
                     "plusButton", "addButton"):
            assert dead not in renderer, dead
        assert "oneshotRun?(" in renderer
        dialog = (browser / "crusorAIHubDialog.ts").read_text(encoding="utf-8")
        for token in ("marketplace", "connectors", "myskills", "oneshot"):
            assert f"'{token}'" in dialog, token
        assert "host.skillsHubOp!(" in dialog and "host.oneshotRun!(" in dialog
        # centered modal: backdrop over the pane, card inside it
        assert "document.body.append(backdrop)" in dialog
        assert "event.target === backdrop" in dialog, "click on the dim closes"
        assert "backdrop.remove()" in dialog
        # delivery-proof chrome: the dialog ships its own stylesheet
        assert "crusorai-hub-dialog-styles" in dialog and "ensureHubDialogStyles" in dialog
        for token in (".crusorai-hub-backdrop {", ".crusorai-hub-dialog {",
                      ".crusorai-hub-row {", ".crusorai-hub-chip {"):
            assert token in dialog, token
        assert "flex-wrap: wrap" in dialog, "rows must drop width:100% warnings to the next line"
        # body-mount theme inheritance + literal fallbacks (rev 5/6 lessons)
        assert "inheritPanelTheme(backdrop, anchor)" in dialog
        assert "getPropertyValue(`--vscode-${name}`)" in dialog
        for token in (
            "var(--vscode-editorWidget-background, #1f1f1f)",
            "var(--vscode-foreground, #cccccc)",
            "var(--vscode-button-background, #0e639c)",
        ):
            assert token in dialog, token
        # connectors are LIVE, not hardcoded (field 2026-10-02): the dialog
        # fetches the engine's connectors op (with a fallback for old
        # engines), the service supplies the workspace, status chips render.
        assert "host.skillsHubOp!('connectors')" in dialog
        assert "FALLBACK_CONNECTORS" in dialog and "crusorai-hub-state" in dialog
        # custom attachable: the form goes THROUGH the engine (never edits
        # files in the panel), attached servers are detachable chips
        # the Create box: Enhance (oneshot) + Add skill (engine op), with
        # frontmatter parsing so pasted files work too
        assert "host.oneshotRun!('enhance_skill'" in dialog
        assert "host.skillsHubOp!('skill_create'" in dialog
        assert "parseSkillMd" in dialog and "crusorai-hub-create" in dialog
        assert "host.skillsHubOp!('connector_attach'" in dialog
        assert "host.skillsHubOp!('connector_detach'" in dialog
        assert "crusorai-hub-attach" in dialog
        assert "is-connected" in dialog and "is-setup" in dialog
        service_src = (browser / "crusorAIRendererService.ts").read_text(encoding="utf-8")
        assert "op.startsWith('connector')" in service_src and "workspace: this.workspacePath" in service_src
        engine = (_REPO / "src" / "agents" / "skills_hub.py").read_text(encoding="utf-8")
        assert "def probe_connectors" in engine and '"connectors"' in engine
        assert "def connector_attach" in engine and "def connector_detach" in engine
        assert "def create_user_skill" in engine and '"skill_create"' in engine
        assert "mcp_config_path" in engine
        assert "mcp_config_path" in engine
        hub_ts = (browser / "crusorAISkillsHub.ts").read_text(encoding="utf-8")
        assert "crusorai.plusMenu" not in hub_ts, "the QuickPick Add… stays dead"
        service = (browser / "crusorAIRendererService.ts").read_text(encoding="utf-8")
        assert "oneshotRun: (template, instructions, variables)" in service
        assert "crusorai.plusMenu" not in service
        css = (browser / "media" / "crusorAI.css").read_text(encoding="utf-8")
        # the stylesheet carries no hub chrome — the dialog self-injects
        assert ".crusorai-hub" not in css and ".crusorai-add-menu" not in css
        assert ".crusorai-mode-summary" in css  # the pill rules the + borrows ship here

    def test_bridge_delegates_to_the_same_dispatcher(self):
        src = (_REPO / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
        assert "from src.agents.skills_hub import handle_hub_op" in src
        # the bridge must not hand-roll a second op implementation
        assert "elif op == " not in src.split("skills_hub_op")[1].split("subagent_list")[0]
