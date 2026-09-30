---
name: skill-authoring
description: "Author skills/<name>/SKILL.md files that Crusor auto-loads."
version: 1.0.0
author: Hermes Agent (adapted from hermes-agent-skill-authoring), ported for CrusorAI
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [skills, authoring, conventions, skill-md, self-improvement]
    related_skills: [requesting-code-review]
---

**Triggers:** create a skill, new skill, save this as a skill, skill authoring, skill.md, teach you a workflow, remember this workflow

# Authoring Crusor Skills

## Overview

Crusor skills are ONE markdown file each: `skills/<skill-name>/SKILL.md` in the engine repo. The runtime (`src/agents/skill_manager.py`) loads every `skills/*/SKILL.md` at boot as a pinned bundled skill, derives triggers, and injects the body into context when a trigger matches the task. No code required — markdown only. This is the loop: **recurring workflow observed → captured as a skill → reused forever**.

Two homes:
1. **Bundled (this repo):** `skills/<name>/SKILL.md` — daily-driver behavior, broadly useful ("a user loads this in 5+ sessions per month"). Committed with `write_file` + git.
2. **User-local:** `~/.crusorai/skills.json` via the SkillManager API / Connectors UI — personal preferences ("always use type hints"). Not for workflow walkthroughs.

When in doubt, bundled-and-generic over bundled-and-niche; niche workflows can start user-local.

## Required shape

```markdown
---
name: my-skill-name                # lowercase, hyphens, ≤64 chars; == folder name
description: "Capability statement, under sixty chars, ends with a period."
version: 0.1.0                     # semver
author: Real Name (handle), Hermes Agent, ported for CrusorAI
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Short, Descriptive, Tags]          # ALSO become triggers
    related_skills: [existing-in-repo-skill]
---

**Triggers:** word-one, word-two, phrase three     # most reliable trigger control

# Skill Title
...body...
```

Hard rules:
- File starts with `---` as the very first line; frontmatter closes with a lone `---`; non-empty body after.
- `name` and `description` are mandatory. Description ≤ 60 chars, capability not implementation, no marketing words ("powerful", "comprehensive"), quote it if it contains `:`.
- `related_skills` must resolve to existing in-repo skills — verify with `search_files` in `skills/`.
- The `**Triggers:**` line is the primary trigger control: lowercase comma-separated words/phrases the USER's task would literally contain ("debug, crash, traceback"). Frontmatter `tags`/`keywords` also become triggers as fallback.
- **Trigger hygiene:** match on distinctive words. "test" fires on "latest"; prefer "unit test", "pytest". Every trigger is a substring match against the task.

## Body standards

- Target **~60–120 lines**; the bundled injection cap is 6000 chars and anything beyond is cut. Dense > long.
- Section order: intro (2–3 sentences, what it does AND doesn't) → `## When to Use` (+ "Don't use for") → core workflow/commands → pitfalls/invariants.
- Reference REAL Crusor tools: `run_terminal`, `read_file`, `write_file`, `edit_file`, `search_files`, `delegate_to_subagent`, `verify_ui_workspace`. Never invent tools.
- Commands the agent must run go in fenced blocks, ready to paste into `run_terminal`.
- Ship the decision rule ("use X when shape matters, use search_files when bytes matter"), not just the tool list.

## Before you finish

1. Frontmatter parses, name == folder name, triggers present and distinctive.
2. Body ≤ 6000 chars: `run_terminal("wc -c skills/<name>/SKILL.md")`.
3. No secrets, no absolute personal paths, no provider-specific keys.
4. Confirm it loads: `SkillManager` refresh or restart — `skills_manifest()` lists it with the new triggers.
5. Offer the user a one-line summary of when the skill will now fire.
