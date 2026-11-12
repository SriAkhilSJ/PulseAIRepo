# PM-Skills — Installation & Verification Report

Status: **COMPLETE — verified by runtime discovery**
Date: 2026-11-12
Owner: TPM (product track for Crusor AI IDE)
Upstream: https://github.com/product-on-purpose/pm-skills

## 1. Installation method

Official, documented OpenCode path ("git clone + skill source configuration"), per
<https://product-on-purpose.github.io/pm-skills/getting-started/platforms/#opencode>:

1. `git clone --depth 1 https://github.com/product-on-purpose/pm-skills.git` into a stable,
   non-project location: `C:\Users\Administrator\.config\opencode\pm-skills`
2. Registered that clone's `skills/` folder as an OpenCode skill source via a **new** project
   config file: `C:\Users\Administrator\Downloads\CRUSORAI\.opencode\opencode.json`

```json
{
  "$schema": "https://opencode.ai/config.json",
  "skills": ["C:/Users/Administrator/.config/opencode/pm-skills/skills"]
}
```

Rejected alternatives and why:

| Method | Verdict | Reason |
| --- | --- | --- |
| `npx skills add` | Rejected | Resolves an agent default directory heuristically; clone + explicit source is the documented OpenCode path and is inspectable. |
| Copy skills into `.opencode/skills/` | Rejected | Duplicates Apache-2.0 third-party content into the workspace and breaks `git pull` updates. |
| `pm-skills-mcp` | Rejected | Upstream declares it **maintenance mode**, catalog frozen at v2.9.2 (40 skills, missing both sprint families). |
| Claude Code plugin marketplace | Not applicable | OpenCode is not a Claude Code client. |

## 2. Installation location

| Item | Path |
| --- | --- |
| Skill library (clone) | `C:\Users\Administrator\.config\opencode\pm-skills` |
| Skill source root | `...\pm-skills\skills` (68 skill directories, each with `SKILL.md`) |
| OpenCode project registration | `C:\Users\Administrator\Downloads\CRUSORAI\.opencode\opencode.json` (created; nothing overwritten) |

Clone commit `9b920db` (2026-11-03). Upstream release badge: **v2.35.0**. The clone is shallow,
so the tag itself is not resolvable locally — the version is read from the upstream README badge,
not from a local tag. Treat as "v2.35.0 line".

## 3. Skill count

- Directories under `skills/` containing a `SKILL.md`: **68**
- Skills OpenCode actually advertised to the model in this session: **68**
- Split: 30 phase (Discover/Define/Develop/Deliver/Measure/Iterate), 11 foundation,
  15 workshop tool, 12 utility.

## 4. Can OpenCode access them?

**Yes — verified, not assumed.** Two independent checks:

1. File-level: all 68 directories contain a valid `SKILL.md` with `name` + `description`
   frontmatter (required for model discovery).
2. Runtime: after writing the config, OpenCode reloaded and advertised all 68 skills to this
   session without a restart. The `skill` tool is callable by ID.

Note: `skills` array paths resolve from the active working directory, so an **absolute** path was
used. This also keeps the library available when a session is opened directly in `PulseAIRepo/`.

## 5. Skills ready to use (mapped to this engagement)

| Capability needed | Skill ID |
| --- | --- |
| Competitive analysis | `discover-competitive-analysis` |
| Customer discovery / interview synthesis | `discover-interview-synthesis` |
| Problem definition | `define-problem-statement` (+ `foundation-build-risk-review`) |
| Product strategy | `foundation-lean-canvas`, `define-opportunity-tree`, `foundation-okr-writer` |
| PRD | `deliver-prd` |
| User stories | `deliver-user-stories` |
| Acceptance criteria | `deliver-acceptance-criteria` |
| Edge cases | `deliver-edge-cases` |
| Solution brief | `develop-solution-brief` |
| Personas | `foundation-persona` |
| Roadmap / prioritisation | `define-prioritization-framework`, `iterate-pivot-decision` |
| Launch planning | `deliver-launch-checklist`, `deliver-release-notes` |
| Quality gate on my own output | `utility-pm-critic` |
| Stakeholder-facing versions of docs | `foundation-stakeholder-briefings` |

Not adopted for this engagement (out of scope for now): Design Sprint and Foundation Sprint
facilitation families, meeting skills, slideshow creator, skill-authoring utilities.

## 6. Compatibility issues

| # | Issue | Severity | Handling |
| --- | --- | --- | --- |
| 1 | Skill frontmatter uses the portable Agent Skills spec (`license`, `metadata.phase`, `author`). OpenCode V2 ignores unknown portable fields. | None | No action. |
| 2 | 6 upstream **sub-agents** are Claude Code native. Only some ship dispatch *skills*. | Low | Use the `utility-pm-critic` / `utility-pm-workflow-orchestrator` dispatch skills, or OpenCode's own `subagent` tool. Not relied on for this engagement. |
| 3 | Upstream slash commands (`/pm-skills:deliver-prd`) are Claude-Code-specific. | None | Invoke by skill ID / natural language instead. |
| 4 | 68 new skill descriptions now occupy context in every session. | Low | Acceptable; can be narrowed later via the `skills` permission rules if it becomes noisy. |
| 5 | Machine-specific absolute path in workspace config. | Low | Fine for local use; must be parameterised before this config is shared or committed. |

## 7. Safety compliance

- No existing OpenCode configuration was modified (`~/.config/opencode/opencode.json[c]` untouched;
  the only write was a new `.opencode/opencode.json`).
- No application source in `PulseAIRepo` was read as writable; no file in the repo was modified.
- License checked: **Apache-2.0** (`LICENSE` present). Commercial use permitted. Not committed to the
  repository, so no third-party code enters the product's git history.
- Existing project memory (`PulseAIRepo/docs/*`, `AGENTS.md`) read only, not overwritten.
