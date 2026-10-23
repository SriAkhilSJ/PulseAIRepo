# Permissions — when Crusor asks you first

> **Status:** current behavior
> **Last reviewed:** 2026-10-23
> **Verified against:** `590fe542306ef89547e7909b89da01a9c730e55c`

Crusor's human-in-the-loop guardrails, modelled on OpenCode's
permission system (rule table copied from upstream
`packages/core/src/permission.ts`; our SafetyGuard stays underneath
as the hard floor).

## The three verdicts

Every guarded call resolves to one of:

- **allow** — runs without asking
- **ask** — the permission dock appears: **Deny · Allow always · Allow once**
- **deny** — refused outright; the call never runs and never asks

An `ask` in the main session waits until the user answers or the turn is
cancelled. There is no automatic approval timeout/denial.

"Allow always" remembers the shown resource **for the rest of this session
only**. Ordinary asks key the tool plus its primary file/command resource;
external-directory asks grant the judged outside path so a later command under
that path does not ask again. Nothing is written to disk—the grant dies with
the session, so a new session asks again. (Upstream OpenCode can persist
"always" verdicts per project; Crusor deliberately does not.) Rules in config
(below) are separate standing settings, not remembered verdicts.
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
`review`, …).

A child can ask a **clarifying question** through the session tree, but the
current tool-execution path does not send a child's permission `ask` to that
approval dock. For `sub-*` sessions, guard-unsafe and permission-config `ask`
calls are refused immediately and the child reports that the main session must
perform the operation. `CRUSORAI_SUBAGENT_AUTO_APPROVE=1` is an unsafe diagnostic
escape hatch that skips checks; it is not approval routing and must not be used
in normal operation or as proof of child HITL parity.

Rules only ever tighten: a config "allow" cannot silence a guard
ask, and reading `.env` files is denied by default (upstream's
rule: `*.env`, `*.env.*` deny; `*.env.example` allow).
