# MCP for the Architect library — plan

Status: **P0–P4 built and tested** (`src/mcp_skills/`, `scripts/skills_mcp_server.py`,
`src/tests/test_skills_mcp_server.py`, 23 tests green), including wiring through the
repository's own `.crusorai/mcp.json` → `discover_mcp_tools` → `call_mcp_tool` path.

Answer to "fastest, easiest, highest quality": **one index built once from the
`SkillManager` the internal tools already use, served over stdio, tools first and
resources as a thin layer over the same dict.** No manifest file, no second parser,
no database, no HTTP. Measured on this machine:

| Operation | Time |
|---|---|
| index build (240 skills, once at process start) | **68 ms** |
| `skill_view` of three books | **< 0.01 ms** |
| `resources/read` of one book | **0.001 ms** |
| `skills_search` over the whole library | **3.9 ms** |

That is the whole speed argument: anything that re-parses 220 files per request, or
keeps a manifest in sync, is slower *and* has a second source of truth to drift.

---

## 1. Where the skills actually stand (verified, not remembered)

Checked at `e6357c94` by running the commands, not by quoting an earlier summary:

| Check | Command | Result |
|---|---|---|
| Conformance | `python scripts/audit_skills.py` | 220 books, **0 violations** |
| Gate | `pytest src/tests/test_skill_library_conformance.py` | 5 passed |
| Suites | 10 focused suites | **229 passed, 1 skipped** |
| Reachability | gate test | **220/220** books selectable by their own triggers |
| Execution gating | gate test | **0** architect skills injected with `phase="executing"` |
| Library size | audit | 220 across 6 domains (website 76, cloud 36, ai-ml 31, data 29, mobile 28, desktop 20) |

**Done:** breadth (one book per framework/primitive), spec conformance, provenance
discipline (2 adapted books, MIT/Apache-2.0, pinned, notices shipped), a build gate.

**Not done, stated plainly:**

- **Depth.** Books are 3–5 KB of decisions and receipts. No `references/` with
  real citations. Roughly 15 books sit at the bottom of the rubric
  (`lineage`, `semantic-layer`, `data-observability`, `react-ui-libraries`,
  `desktop-telemetry`, … ).
- **MCP.** Nothing exists. There is an MCP *client*
  (`src/tools/mcp_client.py`, stdio, protocol `2024-11-05`) and an MCP *test server*
  (`scripts/mcptest_server.py`), but no server exposing the library.
- **Discovery at scale.** 220 skills is past the point where `skills_list()` browsing
  is pleasant; search/ranking is the MCP layer's job.

So: skills breadth is **done and tested**; the library is **not** deep, and MCP is
**unbuilt**. Next section is how to build it.

---

## 2. Goal and non-goals

**Goal.** Expose the exact same library over MCP — same tree, same books, same
gating — so any MCP-capable client (not just Crusor's internal tool loop) can browse
shelves, pull several books, and get the same content the internal `skill_view`
returns.

**Non-goals.**

- A second taxonomy. If MCP names a node, that node is a directory on disk.
- Rewriting books for MCP. Same `SKILL.md`, same frontmatter, one source of truth.
- Shipping skills to users. Internal only, as before.

---

## 3. Mirroring rule (the whole design in one line)

> **One skill directory = one MCP node.** No hand-maintained mapping layer.

| Library | MCP |
|---|---|
| `skills/` root | `skill://catalog` resource + `skills_list()` |
| domain (`website-architect/`) | `skill://website-architect` |
| shelf (`…/backend-development-architect/`) | `skill://website-architect/backend-development-architect` |
| book (`…/python-architect/`) | `skill://website-architect/…/python-architect` |

The server builds this from the filesystem at startup and re-reads on change, using
the same `SkillManager` the internal tools use. Hierarchy is derived, never declared.

---

## 4. Surface

### 4.1 Tools (actions)

| Tool | Args | Returns |
|---|---|---|
| `skills_list` | `shelf?: str` | the shelf listing, same text the internal tool returns |
| `skill_view` | `names: str` | **several books in one call**, comma/space separated (existing rule) |
| `skills_search` | `query: str, limit?: int` | ranked `{name, shelf, why_matched, triggers_hit}` |
| `skill_bundle` | `task: str` | the planning-phase selection for a task, with the reason per book |

`skill_view` stays the pull path: the agent takes as many books as it wants. The
bundle tool is the only thing that *proposes* a set, and only during planning.

### 4.2 Resources (browsing) — corrected after measuring

The first implementation mirrored the tree into `resources/list`: 240 books, with
descriptions, **97 937 bytes ≈ 25 800 tokens** for any host that reads the listing
eagerly. That is the library's entire premise paid before a single question is asked.

The MCP specification says resources are **application-driven** ("host applications
determining how to incorporate context") and that parameterised content belongs in
**resource templates**, with `resources/list` allowed to be sparse. Top servers follow
that: the reference filesystem server exposes file access as *tools*, and knowledge
servers (qdrant, github) expose a small lookup surface rather than enumerating their
corpus.

So the listing is now catalog + health + six domains — **8 entries, 1 266 bytes
≈ 333 tokens** — and every book is still readable through the
`skill://{domain}/{shelf}/{book}` template. Books are *addressed*, not enumerated.

Original text kept below for the record:

- `skill://catalog` — domains, counts, one-line descriptions (642 bytes).
- `skill://{domain}`, `skill://{domain}/{shelf}` — children, with `mimeType: text/markdown`.
- `skill://{domain}/{shelf}/{book}` — the full `SKILL.md` body, resolved by template,
  plus `metadata` echoed in the resource annotations.

Resources are a bonus surface for hosts that have a resource picker. Tools remain the
only surface the *model* can drive on its own, which is why selection lives there.

### 4.3 Prompt

`plan_with_skills(task)` — injects the crown for the matching domain plus the top
three books, with an instruction to open more via `skill_view`. This is the mirror of
the internal planning-phase injection.

---

## 5. Phase gating (non-negotiable rule)

Architect skills are planning instruments.

- `skill_bundle` and `plan_with_skills` require `phase == "planning"`, passed by the
  caller in the request `_meta`. Missing phase is treated as planning for
  read-only clients, but the response is annotated `"phase_assumed": true`.
- `skill_view` and resources are **allowed in any phase** — deliberate pull is the
  documented escape hatch, unchanged from the internal tools.
- With `phase="executing"`, `skill_bundle` returns a structured `PHASE_DENIED` error
  listing what the agent may do instead (open a book deliberately).

---

## 6. Budgets

- One `skill_view` response ≤ **24 000 chars** (several books), then a pointer rather
  than a silent truncation: `{truncated: true, remaining: [names], next: "skill_view('…')"}`.
- Resource read of a single book ≤ **8 000 chars** (bodies are ≤6 000, plus header).
- `skills_search` ≤ 20 results, ranked, with a `why_matched` string per hit.
- Startup catalog build ≤ 300 ms for 220 books; cached, invalidated by mtime.

---

## 7. Issue handling

The internal tools follow rule D17 — **never raise into the model; return a
structured error**. The server keeps that, and adds codes so a client can branch.

### 7.1 Error taxonomy

| Code | When | Response includes | Client should |
|---|---|---|---|
| `UNKNOWN_SHELF` | shelf path is not a directory | closest 5 matches, valid children of the parent | re-browse from parent |
| `UNKNOWN_BOOK` | name not found | close matches (token overlap), suggestion to `skills_list` | retry with a suggestion |
| `BAD_URI` | malformed `skill://` path | the canonical form for what they probably meant | fix the URI |
| `PHASE_DENIED` | bundle requested while executing | the allowed alternative | open books deliberately |
| `BUDGET_EXCEEDED` | response over cap | `truncated`, `remaining`, `next` | issue a follow-up call |
| `SKILL_INVALID` | frontmatter missing name/description | file path + the parse failure | file a bug; server keeps serving others |
| `LIBRARY_UNAVAILABLE` | skills dir missing/unreadable | path checked, errno | degraded mode |
| `INTERNAL` | anything unforeseen | correlation id, no traceback | report the id |

### 7.2 Behaviour rules

1. **One bad book never breaks the catalog.** A `SKILL.md` that fails to parse is
   skipped with `SKILL_INVALID` logged; the other 219 still serve.
2. **No silent truncation.** Ever. A cut response says it was cut and how to get the rest.
3. **Idempotent reads.** Resources and `skill_view` are pure; retries are safe.
4. **Timeouts.** 10 s per request; on timeout return `INTERNAL` with correlation id,
   do not kill the session.
5. **Protocol mismatch.** Unknown `protocolVersion` → answer with the supported one
   and let the client decide; never half-initialise.
6. **Loud logging.** Every error is logged with the correlation id and counted in a
   metric; the same code three times in a session is a bug, not a user error.
7. **No crash loops.** If the catalog build fails at startup, serve `LIBRARY_UNAVAILABLE`
   for reads and keep the process alive for the client to inspect — a dead server
   looks like a client bug.

### 7.3 What we do with failures while building

Same discipline as the skills pass, which is what caught the licence and provenance
problems: a failure is either **fixed** or **written down as a gap** — never smoothed
over in a summary. Concretely: every phase below ends with a test, not a claim; the
report quotes the command that produced the number.

---

## 8. Build phases

| Phase | Content | Gate | Status |
|---|---|---|
| **P0 — skeleton** | `scripts/skills_mcp_server.py` (stdio, `2024-11-05`), `initialize`/`tools/list`, `skills_list` + `skill_view` backed by `SkillManager` | contract test over stdio: init → list → view 2 books; byte-identical body to internal `skill_view` | **done** — real client session test; body parity asserted |
| **P1 — resources** | catalog + templates + per-book resources, `mimeType`, annotations | every one of the 220 books resolvable as a resource; resource set == disk set | **done** — resource set == index set, asserted |
| **P2 — search & bundle** | `skills_search`, `skill_bundle`, phase gating | self-retrieval parity: each book found via its triggers through MCP; `PHASE_DENIED` proven | **done** — ranking asserted, gating proven |
| **P3 — errors & budgets** | full taxonomy, truncation contract, logging, metrics | fault-injection tests: bad URI, unknown book, unparseable book, missing dir, over-budget | **done** — `skill://health` exposes counters; unreadable books are skipped and reported; `LIBRARY_UNAVAILABLE` proven by fault injection |
| **P4 — client wiring** | register the server in `.crusorai/mcp.json`, document in `skills/mcp/SKILL.md` | end-to-end from a real client session, not a unit test | **done** — `docs/skills-mcp.example.json`, live `.crusorai/mcp.json`, and a test that discovers the tools through `mcp_client` |

P0–P2 are the useful half; P3 is what makes it trustworthy; P4 is one config entry.

---

## 9. Risks

- **Two doors, one library.** MCP and internal tools could drift. Mitigation: both
  call the same `SkillManager`; a test asserts identical bodies.
- **Context bloat.** A server that happily returns five books will burn a context
  window. Mitigation: budgets in §6 and a `skill_bundle` that returns 3, not 10.
- **Phase gating can be bypassed** by any client that lies about `phase`. Accepted:
  the gate is a planning discipline, not a security boundary. Resources stay open by
  design.
- **Ranking quality.** `skills_search` over 220 books with trigger matching will
  cross-fire across domains (already observed: "tablet layout" → mobile *and*
  html-css). Mitigation: `why_matched` transparency beats a clever opaque ranker.

---

## 10. Decisions I need from you

1. **Scope of P1** — full resource templates (browsable library in the client) or
   tools only (smaller, faster)? Default: full resources, since that is the point of
   "MCP mirrors the skills".
2. **Transport** — stdio only for now, or also an HTTP/SSE endpoint so remote clients
   can reach it? Default: stdio first, HTTP later.
3. **Where it lives** — `scripts/` like `mcptest_server.py`, or a first-class package
   `src/mcp_skills/`? Default: `src/mcp_skills/` with a `scripts/` entry point,
   because it is a product surface, not a test fixture.

What was built follows the defaults: full resource templates, stdio only, code in
`src/mcp_skills/` with a `scripts/` entry point.


## Operational notes

- **Logs never touch stdout** — stdout is the protocol. Structured JSON lines go to
  stderr, level from `SKILLS_MCP_LOG` (`debug|info|warn|error`).
- **`skill://health`** returns uptime, per-tool and per-resource counts, error counts
  by code, index builds and refreshes.
- **Freshness** — the index reloads when a `SKILL.md` mtime changes, throttled to once
  every `SKILLS_MCP_REFRESH_SECONDS` (default 5 s), so editing a book does not require
  a restart.
- **Config shape** — `command` is a single string and `args` is the list. A list in
  `command` never launches, which is what the wiring test asserts against.
