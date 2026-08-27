# Branch Audit: `arena/01a02a5c-pulseairepo` → `main`

**Date:** 2026-08-27
**Audited branch:** `arena/01a02a5c-pulseairepo` (tip `00d8ced8`)
**Against:** `main` (tip `403bce9d` — *"Merge Pulse agent reliability and four-mode desktop UI"*)
**Outcome:** **Nothing to cherry-pick — every change on the branch is already present on `main`, and the branch's headline fix is superseded by a strictly better implementation. Branch deleted. Not merged.**

---

## 1. Topology

The two refs have **unrelated histories** (no common ancestor; both are single
root commits):

- `arena/01a02a5c-pulseairepo` = one root commit `00d8ced8`,
  *"fix(safety_guard): add trailing space to 'rm' pattern to prevent false positives"*.
  Because it is a root commit, the whole tree is part of that commit, but the
  commit message describes **one** substantive change.
- `main` = a newer, larger snapshot (`403bce9d`).

So "cherry-pick the commit" is not meaningful (it is a full-tree root commit);
the correct audit is a **tree-vs-tree content comparison**.

## 2. Tree comparison

| Metric | `arena/01a02a5c` | `main` |
|---|---|---|
| Total files | 17,134 | 18,144 |
| Test files under `src/tests` | 89 | 98 |
| Files present on the branch but **absent** from `main` | **0** | — |

- **Zero** files (vendored `desktop/vscode` or otherwise) exist on the branch
  that are not already on `main`.
- Every shared source file on `main` is a superset (e.g. `src/graphs/chat_graph.py`
  3,128 → 3,555 lines; `src/llm/factory.py` 678 → 923 lines). `main` contains
  substantial later work (`src/context/lazy_memory.py`, `workspace_integrity.py`,
  `src/graphs/budget.py`, `src/runtime/host_capabilities.py`, nine extra test
  modules, and more).
- Direction of the `src/` + `benchmarks/` diff: **+3,822 / −228** on the `main`
  side — the branch is an older snapshot that `main` has moved past.

## 3. The headline fix is superseded

The branch's only described change (`src/context/safety_guard.py`) adds a
trailing space to the dangerous-command set so a bare `"rm"` no longer matches
inside words such as PowerShell's `Format-Table`.

**Branch (`00d8ced8`):**
```python
DANGEROUS_COMMANDS = {
    "rm ", "rm -rf", "del ", "rd /s", "mkfs", "dd ", "format ", ...
}
```

**`main` (`403bce9d`)** replaces the substring hack with a proper shell-token
regex, and the code comment explicitly records that the branch's `"rm "`
interim fix was insufficient:
```python
DANGEROUS_COMMANDS = { "del ", "rd /s", "mkfs", "dd ", "format ", ... }
# Match rm as a shell token instead of a raw substring. The old "rm"
# pattern blocked harmless commands such as PowerShell's Format-Table;
# the branch's interim "rm " fix still missed tabs and a bare `rm`.
RM_COMMAND = re.compile(r"(?<![\w-])rm(?=\s|$)", re.IGNORECASE)
```

`main` also ships a dedicated regression test,
`src/tests/test_review12.py::test_rm_is_matched_as_a_shell_token_not_a_substring`,
which covers every case the branch fix handled **plus** the cases it missed
(`rm\tfile.txt`, a bare `rm`, `sudo rm -rf build`, and the `Format-Table`
false positive). The branch fix is therefore **superseded, not needed**.

## 4. Provider-free regression tests (run on `main`)

Environment: Python 3.11.2, pytest 9.1.1, pytest-asyncio; framework deps
(langchain/langgraph/openai/groq/google-genai, etc.) installed but **no API
keys and no live provider calls**; tree-sitter grammars installed.

- **Safety/guard suites** (`test_review12`, `test_ptc`, `test_cancellation_gates`,
  `test_parallel_tools`, `test_engine_smoke`): **104 passed** — including the
  `rm`-token regression test that validates the superseded fix.
- **Full suite (`src/tests`, 98 files):** **1014 passed, 4 skipped, 22 failed.**
  All 22 failures are pre-existing on `main` and unrelated to the audited
  branch:
  - **19** were missing native grammar/tokenizer dependencies in the sandbox
    (`test_lang_extractors`, `test_lab_fixes`, `test_chunk_index`). After
    installing the tree-sitter grammar wheels these were re-run standalone:
    **103/103 passed.**
  - **3** remain on `main` and are genuine pre-existing issues in newer
    `main`-only code (absent/simpler on the branch), none in `safety_guard`:
    - `test_session_engines.py::TestRegistry::test_memoized_per_session` and
      `::TestNodeWiring::test_recovery_limit_node_records_on_session_engine` —
      root-caused to `chat_graph.get_context_engine()`: passing a config dict
      with `"model": "m"` for a thread, then a bare string key for the same
      thread, builds **two** engines because the bare-string path falls back to
      the process default `LLM_MODEL` (`qwen/qwen3.6-27b`) and the model-mismatch
      guard (`chat_graph.py`, model-aware rebuild block added on `main`) evicts
      the first engine. The branch's older registry lacks this model-aware
      logic, so the mismatch is introduced by later `main` work.
    - `test_review_autopsy_fixes.py::test_d26_token_and_trace_churn_no_longer_busts_layer_cache`
      — the layer-cache identity check is sensitive to token counts; in the
      sandbox `tiktoken` cannot download the `o200k_base` encoding (no network to
      the OpenAI blob host) and degrades to the chars/4 heuristic, which perturbs
      the budget and rebuilds the `repo_map` layer. Passes with a populated
      tiktoken cache.

  These are out of scope for this audit (they are not fixes the branch can
  provide — the branch does not contain newer code for them) but are recorded
  here for maintainers.

## 5. Decision

- **Cherry-picks: none.** No commit on `arena/01a02a5c-pulseairepo` is both
  valuable and unsuperseded. The sole described fix is already on `main` in a
  strictly better, tested form; every file in the branch is already present
  on `main`.
- **No wholesale merge** (explicitly avoided — histories are unrelated and the
  branch is a strict older subset).
- **Branch deleted** (remote `origin/arena/01a02a5c-pulseairepo` and local
  tracking ref). No open PR or ref referenced it.
