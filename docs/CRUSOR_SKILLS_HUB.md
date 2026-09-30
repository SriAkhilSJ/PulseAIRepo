# Crusor Skills Hub

**Status:** landed (Phase 1). **Owner:** engine (`src/agents/skills_hub.py`, `src/tools/skill_hub_tools.py`).

The Skills Hub is the INSTALL side of the skills story. Bundled skills +
`skills_list` / `skill_view` cover what is already on disk; the Hub adds
discovery and installation of community Agent Skills (the `SKILL.md` folder
standard) straight into the user's skill store — from chat (`hub_search` →
`hub_install`) or from a terminal (`scripts/skills_hub_cli.py`).

## The user-visible flow

```
user:  "install a skill for C security review"
agent: hub_search("security review c")
       → c-review [security] (curated) — C/C++ security review ...
agent: hub_install("c-review")
       → SHA-pinned download → capped, traversal-proof extraction →
         collision guard → lands in ~/.crusorai/skills.json + folder copy
agent: "installed. loading skill_view('c-review') and following it."
```

After install the skill rides every existing path: the `<available_skills>`
index (name + description), eager trigger injection, `skill_view`, usage
telemetry, and the D39 curator (hub installs are `pinned` — the curator
never auto-archives a skill the user explicitly chose).

## Sources

| Source | Example | Trust |
|---|---|---|
| Curated catalog | `hub_install("frontend-design")` | `curated` |
| Direct repo, pinned | `hub_install("owner/repo@<40-char-sha>")` | `community` |
| Direct repo + subdir | `hub_install("owner/repo@<sha>:skills/x")` | `community` |
| Symbolic ref | `hub_install("owner/repo@main")` | `community` (resolved to a full SHA first; fail-closed if it can't be) |

### The catalog — `skills/catalog.json`

Curated entries, each pinned to an **exact 40-char commit SHA**. Presence in
the catalog is the trust signal. Admission rules (enforced by
`load_catalog()` validation, which drops + reports bad entries):

1. Full 40-char SHA pins only — branches and tags are rejected.
2. `repo` must be a github.com repo root URL.
3. `trust` is `curated` | `community`.
4. Names are unique slugs; description and category are required (search UX).
5. Adding or bumping an entry is a reviewed PR — the SHA diff is the review.

## Safety pipeline (every install, catalog or not)

1. **Host allow-list** — only `github.com` / `codeload.github.com` /
   `api.github.com`, https only.
2. **SHA anchoring** — symbolic refs resolve to a full SHA before download;
   the resolved SHA is what is recorded in provenance. Unresolvable ref ⇒
   install refused (fail closed).
3. **Download caps** — 25 MB archive cap, bounded reads.
4. **Safe extraction** — no absolute paths, no `..` traversal, no
   hardlinks/devices, absolute or escaping symlinks rejected; *contained*
   relative symlinks (common in community repos) are materialized as real
   file copies of their target. File-count (2000) and per-file (8 MB) caps.
5. **Skill validation** — a discoverable `SKILL.md` with a non-empty body;
   slug-sanitized name; instruction capped at the bundled 6000-char budget.
6. **Collision guard** — an existing skill of the same name is never
   silently overwritten. Only a prior install of the SAME repo+subdir can be
   upgraded (fresh folder copy — no orphan files).
7. **No execution** — installing never runs anything from the skill. Skill
   scripts are data; running them goes through the usual terminal approval
   gates like any other workspace file.

## Provenance & lifecycle

- `~/.crusorai/hub-skills/skills/<name>/` — the installed folder (support
  files included). `SkillManager` stores the body + a `source` dict
  (`kind/repo/sha/subdir/ref/trust/installed_at/folder/files/bytes`);
  `add_skill(source=...)` is backward-compatible (no source ⇒ no key).
- `~/.crusorai/hub-skills/provenance.json` — the install ledger (atomic
  write). Powers `hub_list` (with an `update_available` hint when the
  catalog pins a newer SHA for the same repo+subdir) and `hub_remove`.
- `hub_remove` refuses bundled skills (read-only) and non-hub user skills
  (those belong to `skill_manage`).
- `CRUSORAI_HUB_SKILLS_DIR` overrides the hub root (tests/CI).

## Surfaces

| Surface | Tools | Notes |
|---|---|---|
| Agent | `hub_search`, `hub_install`, `hub_update`, `hub_list`, `hub_remove` | bound in the always-on skills waist (`toolsets._SKILL_TOOLS`) and `_TOOLS_BY_NAME`; one gated prompt sentence (`_HUB_SENTENCE`) renders only when hub tools are bound |
| Bridge | `skills_hub_op` → `skills_hub_result` (op envelope: list / search / install / update / remove) | the transport the desktop Skills panel binds to; protocol pinned at all four layers |
| CLI | `skills_hub_cli.py search/install/update/list/remove` | same pipeline |
| Terminal | `scripts/skills_hub_cli.py` (`search` / `install` / `list` / `remove`) | same pipeline; useful for setup scripts and catalog verification |
| Python | `src.agents.skills_hub` | result dicts, errors never raise (skills-layer convention) |

## Verification

`src/tests/test_skills_hub.py` — 31 hermetic tests (injectable fetcher +
ref resolver, zero network): source grammar, catalog validation (incl. the
shipped catalog), search ranking, end-to-end installs, fail-closed ref
resolution, traversal/symlink/cap rejections, collision + upgrade rules,
uninstall scope, tool binding, `add_skill(source=...)` round-trip, and a
branding-hygiene pin (the hub surface carries Crusor naming only).
Live-verified over a real socket: catalog install (`frontend-design`), direct
`@sha:subdir` install (Vercel repo with internal symlinks), and `@main`
resolution to an exact SHA.

## Roadmap (not in this phase)

- **Phase 2 — store browser UI**: a Marketplace panel in the IDE (browse,
  search, one-click install, update badges). DONE so far: the backend —
  `hub_update` (catalog-pinned upgrades, same-source collision guard) and the
  `skills_hub_op`/`skills_hub_result` bridge frame pair; the panel UI binds to
  the bridge envelope.
- **Phase 3 — bundles**: multi-skill packs + custom commands as one unit.
- **Phase 4 — publishing**: Crusor users open their own catalogs.
- Remote catalog federation (community-maintained catalog files fetched at
  runtime) — deliberately deferred; the bundled catalog + direct GitHub
  sources cover the MVP without third-party registry trust.
