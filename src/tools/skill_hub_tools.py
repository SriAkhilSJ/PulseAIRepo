"""Skills Hub tools — the INSTALL side of skills.

The bundled skills + ``skills_list``/``skill_view`` cover what is ALREADY
installed. These tools cover discovery and installation of community Agent
Skills (the ``SKILL.md`` open standard): search the curated catalog, install
from the catalog or any GitHub repo, list what the hub installed, remove an
install. The pipeline (size caps, traversal-proof extraction, SHA pinning,
collision guard, no execution on install) lives in
``src/agents/skills_hub.py``; these tools are thin, string-returning
wrappers — errors are strings, never raised.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

_MAX_LISTED = 20


def _hub() -> Any:
    from src.agents import skills_hub
    return skills_hub


@tool
def hub_search(query: str, category: str = "") -> str:
    """Search the Crusor Skills Hub catalog for installable community skills.

    Call this when the user asks for a skill/capability that is not in the
    skills index — e.g. "find a security review skill". Returns name,
    one-line description, category, and the exact source to install with
    hub_install.

    Args:
        query: space-separated keywords, e.g. "react performance" or
            "security review". Every keyword must match.
        category: optional filter, one of the hub's categories (omit to
            search all).
    """
    hub = _hub()
    cat = hub.load_catalog()
    if not cat.get("ok"):
        return f"hub_search error: {cat.get('error')}"
    res = hub.search_catalog(cat, query, category)
    entries = res.get("results", [])
    if not entries:
        cats = ", ".join(hub.catalog_categories(cat))
        return (
            f"hub_search: no catalog match for {query!r}. "
            f"Categories: {cats or 'none'}. You can also install any GitHub "
            "repo directly: hub_install(\"owner/repo@<full-commit-sha>\")"
        )
    lines = []
    for e in entries:
        src = f"{e['repo'].replace('https://github.com/', '')}@{e['sha']}"
        if e.get("subdir"):
            src += f":{e['subdir']}"
        lines.append(
            f"- {e['name']} [{e['category'] or 'general'}] ({e['trust']}) — "
            f"{e['description']}\n  install: hub_install(\"{e['name']}\")  "
            f"(direct: hub_install(\"{src}\"))"
        )
    return (
        f"Crusor Skills Hub — {len(entries)} match(es) for {query!r} "
        "(install with hub_install, then the skill appears in the skills "
        "index and can be loaded with skill_view):\n" + "\n".join(lines)
    )


@tool
def hub_install(source: str, pick: str = "") -> str:
    """Install a community Agent Skill into the user's skill store.

    Installs are safe by construction: SHA-pinned download, capped and
    traversal-proof extraction, collision guard, and NOTHING from the skill
    is executed during install. After a successful install the skill is
    immediately in the skills index — load it with skill_view(name).

    Args:
        source: a catalog name ("frontend-design"), "owner/repo",
            "owner/repo@<full-40-char-sha>" or "owner/repo@<sha>:<subdir>".
            Catalog names are preferred (curated + SHA-pinned).
        pick: when the source hosts several skills, the one to install
            (folder or skill name). Omit when the source is a single skill.
    """
    res = _hub().install_skill(source, pick=pick)
    if not res.get("ok"):
        return f"hub_install error: {res.get('error')}"
    word = "upgraded" if res.get("upgraded") else "installed"
    out = (
        f"{word}: {res['name']} (from {res['repo']} @ {res['sha'][:12]}, "
        f"{res['trust']}, {res['files']} files). It is now in the skills "
        f"index — load with skill_view(\"{res['name']}\"). Nothing from the "
        "skill was executed; run any of its scripts only with the user's "
        "approval."
    )
    # Install-time metadata linter (warn, never block): bad metadata makes a
    # skill invisible or inert, and the model is the one that can compensate
    # (better description via skill_manage patch, explicit skill_view usage).
    warnings = res.get("warnings") or []
    if warnings:
        out += "\nMetadata warnings: " + "; ".join(warnings) + (
            "\nConsider skill_manage(action='patch') to add the missing "
            "description/triggers so the skill indexes and activates well."
        )
    return out


@tool
def hub_list() -> str:
    """List skills installed via the Skills Hub, with source repo, commit,
    trust tier, and whether the catalog pins a newer version."""
    res = _hub().list_hub()
    rows = res.get("installed", [])
    if not rows:
        return (
            "No hub-installed skills yet. hub_search finds curated ones; "
            "hub_install(\"owner/repo@<sha>\") installs from any GitHub repo."
        )
    lines = []
    for r in rows[:_MAX_LISTED]:
        upd = " — UPDATE AVAILABLE (hub_install the same source to upgrade)" if r.get("update_available") else ""
        lines.append(
            f"- {r['name']} — {r['repo']} @ {r['sha'][:12]} [{r['trust']}] "
            f"installed {r['installed_at']}{upd}"
        )
    return "Hub-installed skills:\n" + "\n".join(lines)


@tool
def hub_remove(name: str) -> str:
    """Remove a skill that was installed via the Skills Hub.

    Removes the store entry, the installed folder, and the provenance
    record. Bundled and manually-created skills are refused — those are not
    hub property (use skill_manage for agent-created ones).

    Args:
        name: the skill name exactly as in the skills index.
    """
    res = _hub().uninstall_skill(name)
    if not res.get("ok"):
        return f"hub_remove error: {res.get('error')}"
    return f"removed: {res['name']} (hub install fully uninstalled)"


@tool
def hub_update(name: str = "") -> str:
    """Update hub-installed skills to the exact commit the curated catalog
    currently pins.

    Updates always move to a catalog-pinned SHA through the same sandboxed
    pipeline as install — never to a moving branch. Without arguments,
    updates every hub-installed skill that has a newer pinned version;
    with a name, only that skill. Skills not covered by the catalog are
    reported and left untouched.

    Args:
        name: optional skill name to update just one skill (omit to update
            everything the catalog covers).
    """
    hub = _hub()
    results: list[dict] = []
    if (name or "").strip():
        results.append(hub.update_hub_skill(name.strip()))
    else:
        installed = hub.list_hub().get("installed", [])
        if not installed:
            return "hub_update: nothing installed via the hub yet."
        targets = [r for r in installed if r.get("update_available")]
        if not targets:
            return (
                f"hub_update: {len(installed)} hub-installed skill(s), all already "
                "at the catalog-pinned versions."
            )
        for r in targets:
            results.append(hub.update_hub_skill(str(r["name"])))

    lines = []
    for r in results:
        if not r.get("ok"):
            lines.append(f"- {r.get('error', 'failed')}")
        elif r.get("updated"):
            lines.append(
                f"- {r['name']}: {r['from_sha'][:12]} → {r['to_sha'][:12]} (updated)"
            )
        else:
            lines.append(f"- {r['name']}: already at the pinned version ({r['sha'][:12]})")
    return "hub_update:\n" + "\n".join(lines)


HUB_TOOLS = (hub_search, hub_install, hub_update, hub_list, hub_remove)
