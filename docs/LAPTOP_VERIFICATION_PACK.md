# Laptop verification pack — sub-agent builds (through `d54ebd0a`)

Pull `arena/0d4596c3-pulseairepo`, open your test workspace in the agent,
run each prompt in the **desktop agent**. Every prompt is one delegated
run (real provider credits). Work top to bottom — later steps reuse
earlier results. Mark each ✅ / ❌ and send me the numbers that failed.

Setup for step 6 only: create this file in your workspace first —
`.crusorai/agents/release-writer.md`:

```markdown
---
description: Writes release notes
base: code
capabilities: workspace_read, workspace_write
---

You are a release-notes specialist. Write short, friendly release
notes with a "Highlights" heading. Never run terminal commands.
```

## 1. A child asks YOU a question (answer it from the parent view)

Paste:

> Delegate this to a research sub-agent: find out whether bubble sort
> or merge sort is better for nearly-sorted data. Tell the sub-agent:
> before you finish, you MUST use the question tool to ask me which one
> I prefer, with choices "bubble" and "merge", and wait for my answer
> before concluding.

You should see:
- The sub-agent card spins; a **question card docks above the composer
  in the parent view** (not inside the transcript).
- Answer it right there. The child then finishes and its result uses
  your choice.
- Bonus: while it waits, click into the child — the same question is
  in its transcript, its page scrolls, and the nav row at the very
  bottom shows Running…

Fail if: the child never asks and just concludes silently, the question
only appears inside the child, or answering in the parent does nothing
(the child hangs).

## 2. A child's approval surfaces — and check the look

Paste:

> Delegate to a code sub-agent: create hello.py in the workspace root
> that prints "hello from child", run it with the terminal, and report
> the output.

You should see (whenever the approval appears — if your settings
already allow the action, do step 2b):
- An approval dock: **flat dark card, black tray underneath it,
  amber ⚠ icon only** (nothing amber-tinted), title "Permission
  required", the command/file as a plain code line, and
  **Deny | Allow always | Allow once** buttons bottom-right.
- It appears in the **parent view** while the child waits. Allow once →
  the child proceeds and finishes.

### 2b. Force an approval in your own session

> Create a file crusor-check.txt with any content, then delete it using
> the terminal `rm` command.

Same dock, this time for your own session. Deny it: the deletion must
not happen.

Fail if: the approval only shows inside the child, the card is
amber-tinted/light, or Deny still lets it run.

## 3. Stop kills the worker

Paste, then press **Stop** within ~2 seconds:

> Delegate a long research task: research the complete history of
> sorting algorithms, in depth, with many sources.

You should see: the sub-agent card stops spinning and settles
(cancelled/error), the parent turn ends as cancelled, and opening the
child shows its turn ended too — nothing keeps running in the
background.

Fail if: the child keeps running / completes normally after Stop.

## 4. Resume the same worker (it remembers)

Step A paste:

> Delegate to a research sub-agent: read README.md and summarise it in
> one line. Report the sub-agent's session id back to me.

Keep the session id from the result. Step B paste:

> Continue that same sub-agent session (session_id from your last
> result): also read the LICENSE file and add one line about it.

You should see: the follow-up result builds on the first one, and
opening that child session shows **both exchanges in one transcript**.

Fail if: a brand-new session starts (empty transcript), or it errors
about the session.

## 5. Per-task agents + sibling hopping

Paste:

> Delegate these in parallel: (1) research which Python version this
> project needs, (2) write version_check.py that prints the Python
> version, (3) review README.md for problems.

You should see: three sub-agent cards (or batch rows) with their own
agent names — the writer says Code, not Research. Open a running
child: the nav row at the bottom has **sibling chips**; clicking one
jumps straight to that worker.

Fail if: the write task runs as Research, or siblings aren't clickable.

## 6. Your own custom agent

With the setup file above in place, paste:

> Use the release-writer agent to draft release notes for the most
> recent change in this workspace.

You should see: a card titled for **release-writer**; the result reads
like release notes with a "Highlights" heading (its own prompt), and
it does not run terminal commands (its declared capabilities).

Fail if: the agent says it doesn't know "release-writer", or it runs
as plain research/code with no release-notes shape.

## 7. Session list stays clean

Open the session list / Manager. You should see only your real
conversations — **no worker (sub-…) sessions as rows**, even after all
the delegations above. Workers are reached through their cards.

## 8. (Optional) Cheap model for workers

Only if you have a second model configured. Paste:

> Delegate a research task about sorting, but run the sub-agent on
> model <your-other-model-name>.

Pass = it completes and the engine log/show-model reflects the
override; skip freely with a single model.

## Report back

Just reply with the step numbers and ✅/❌ (plus a screenshot of any
❌). Especially valuable: step 1 (child question answered from the
parent) and step 2 (approval look + surfacing) — those are the
human-in-the-loop paths.
