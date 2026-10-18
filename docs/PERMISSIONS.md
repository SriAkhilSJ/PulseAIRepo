# Permissions — when Crusor asks you first

Crusor's human-in-the-loop guardrails, modelled on OpenCode's
permission system (rule table copied from upstream
`packages/core/src/permission.ts`; our SafetyGuard stays underneath
as the hard floor).

## The three verdicts

Every guarded call resolves to one of:

- **allow** — runs without asking
- **ask** — the permission dock appears: **Deny · Allow always · Allow once**
- **deny** — refused outright; the call never runs and never asks

"Allow always" remembers that exact file/command **for the rest of this session only**. Nothing is written to disk — the grant lives in the session's memory and dies with it, so a new session asks again. (Upstream OpenCode also persists "always" verdicts per project; Crusor deliberately does not — founder 2026-10-17: permission handling is session-only.) Rules you write yourself in config (below) are separate: they are your standing settings, not remembered verdicts.
Secrets (`.env`, credentials) and git-ignored files are re-asked
**every** time — no grant can silence them.

## When it asks (out of the box)

Our guard asks when something could actually hurt:

- overwriting a file git cannot restore (not tracked, or no repo)
- sensitive files (`.env`, credentials, secrets, config)
- git-ignored files (nothing can bring them back)
- dangerous shell commands (`rm -rf …`, command substitution, …)

plus the two OpenCode guard actions:

- **External directory** — a shell command reaching outside the
  project directory asks first. (Crusor's file tools are clamped to
  the workspace and physically cannot leave it, so they never ask.)
- **Doom loop** — the same call repeating 3 times in a row with
  identical input asks instead of looping on.

Everything else runs without asking.

## Your own rules (config)

OpenCode-style, in either file (workspace wins; later rules win;
wildcards `*` and `?`):

- `~/.crusorai/settings.json`
- `<workspace>/.crusorai/settings.json`

```json
{
  "permission": {
    "*": "ask",
    "bash": { "*": "ask", "git *": "allow", "rm *": "deny" },
    "edit": { "*": "deny", "src/**": "allow" }
  },
  "agent": {
    "build":  { "permission": { "bash": "ask" } },
    "review": { "permission": { "edit": "deny", "bash": "ask" } }
  }
}
```

Actions: `read`, `edit`, `glob`, `grep`, `list`, `bash`, `task`,
`skill`, `question`, `webfetch`, `websearch`, `session_search`,
`doom_loop`, `external_directory` — or any tool name. The main
agent is `build`; sub-agents use their mode (`research`, `code`,
`review`, …). A sub-agent cannot answer an ask, so an ask on a
child means the call is refused and the child reports it needs the
main session.

Rules only ever tighten: a config "allow" cannot silence a guard
ask, and reading `.env` files is denied by default (upstream's
rule: `*.env`, `*.env.*` deny; `*.env.example` allow).
