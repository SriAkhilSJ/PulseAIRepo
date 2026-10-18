# Laptop verification pack — engine + UI through `01bb6fd0` (UI stamp `2026-10-17-26`)

## Setup (every round)

1. Pull `arena/0d4596c3-pulseairepo`.
2. Fully quit and reopen the agent (a running workbench keeps the old
   compiled panel — that is what the freshness stamp exists to catch).
3. The status chip must read **`593b9aa1` · `ui 2026-10-17-19`**.
   Anything older = you are not testing this code; stop and tell me.

Run each check in the **desktop agent**. Mark ✅ / ❌ and send me the
failing numbers.

---

## A. Permission rules — the new rule table (`593b9aa1`)

### A1. Doom loop asks

> Read the file README.md (or any workspace file) — actually, read it,
> then read it again, then read it a third time, one call at a time.

- The **third identical read** produces a permission dock:
  *"The same call has repeated 3 times with identical input."*
- **Allow once** → the read runs. Ask again later in the session →
  **Allow always** → further identical reads run without asking.

Fail if: the third read just runs silently (or errors as "blocked").

### A2. Shell reaching outside the project asks

> Run this terminal command: `cat ~/.bashrc` (any file outside the
> workspace works).

- Dock appears: *"This touches files outside the project directory."*
- **Deny** → the command must NOT run.

Fail if: the command runs without asking, or runs after Deny.

### A3. Your own deny rule (config)

Create `<workspace>/.crusorai/settings.json`:

```json
{ "permission": { "edit": "deny" } }
```

Then:

> Create a new file called perm-test.txt with any content.

- **No dock at all.** The write is refused outright; the agent reports
  it was blocked ("Permission denied"), and `perm-test.txt` does NOT
  exist afterwards.
- Delete the settings file afterwards (or the rest of this pack gets
  weird).

Fail if: a dock appears, or the file gets created.

### A4. Ask-everything knob (optional)

Same file, `{ "permission": { "*": "ask" } }` — now even a plain file
read asks. Remove the file when done.

## B. Allow always finally means it (`4449c5f9`)

### B1. Overwrite the same file twice

> Create notes-check.py with a print statement. (let it finish)
> Now rewrite notes-check.py completely with different content.

- Second write → dock: *"This file already exists. Running this will
  overwrite it."* + the diff. Choose **Allow always** (confirm dialog
  names the file).
- Repeat: *"Rewrite notes-check.py again, different content."*
  → **no dock** — it just writes.
- *"Rewrite some OTHER existing file."* → dock returns (the grant was
  for notes-check.py only).

Fail if: the same-file rewrite asks again after Allow always, or the
other file does NOT ask.

### B2. Secrets always ask

> Rewrite .env (or create one first, then rewrite it).

- It asks. **Allow always** it. Rewrite it again → **it asks again**.
  No grant can silence a secret.

Fail if: the second .env write runs without asking.

### B3. Grants die with the session (session-only permissions)

> After B1, start a NEW session (or restart the app) and rewrite
> notes-check.py again.

- The dock **asks again** — last session's Allow always is gone.
- The confirm dialog says *"for the rest of this session"*
  (never "in this project").
- No `.crusorai/permissions-saved.json` exists in the workspace
  afterwards — verdicts are never written to disk.

Fail if: the new session writes without asking, or the dialog
promises the project.

## C. The dock's look (`4449c5f9`)

During any ask above, check with your eyes:

- Flat black card, amber ⚠ icon only (nothing amber-tinted), title
  "Permission required".
- One plain sentence under it — **no** `**`, no "Reply with: yes/no",
  no emoji walls.
- File ask shows the diff (`+`/`-` signed rows); shell ask shows the
  command as a code line and names what's dangerous.
- Buttons bottom-right: **Deny | Allow always | Allow once**.

Fail if: anything shows raw `**Safety Check:**` text.

## D. Cards & dropdowns (`115b5252`)

### D1. List files — the `{}` is dead

> List the files in this workspace, then list a subfolder.

- While it runs, the **List files** row shows nothing expandable.
- When done, it has a chevron; open it → the **actual file names**,
  not `{}`.
- Any running tool card (terminal, web search) stays **closed while
  it renders**; click it mid-run → it opens; before your click it
  never pops open by itself.

### D2. Dropdown headers

Trigger two reads/searches in a row (ask: "search the codebase for X,
then read the top two matches"):

- Group header reads **`⌄ Explored 2`** — arrow at the START, word,
  count hugging it.
- Live: reads say **Exploring**, edits say **Editing** (then settle to
  Explored / Edit), terminals stay **Terminal**; the live word
  shimmers.

## E. Older, still unverified (one pass, any order)

1. **Child settles when watched** (`ab8f234a`): open a running child;
   when it finishes, its view settles (no stuck "Running…"), and no
   answer text appears twice.
2. **Hover shake** (`201faf63`): hover a running sub-agent card —
   nothing wiggles sideways.
3. **Big delegate answer** (`ee4ae231`): have a sub-agent produce a
   long report (50+ lines) — the full answer arrives in the parent,
   not truncated to a preview.
4. **Clarify timeout** (`6166843d`): make a child ask a question with
   choices and DON'T answer (5 min — do this one last / over coffee).
   The final answer must plainly say the question went unanswered —
   it must NOT invent a choice for you.
5. **Dropdown highlight**: hover any dropdown header → it visibly
   highlights; open one → it keeps a quiet wash while open.
6. **Diff rows**: sign before number (`+ 1`, `- 1`), tight gutters,
   no green/red edge line on Edit/Write diffs.
