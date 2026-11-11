# Root-cause analysis and correction

## 1. Contract extraction (tests 02, 04, 05, 11, 42)

`extract_contract()` classified requirements with `requirement_intent()`. That
function treated the verb **build** as a BUILD-file requirement:

```python
# before
if re.search(r"\b(?:makefile|dockerfile|build|requirements\.txt)\b", lowered):
    return FileRole.BUILD
```

A product request such as “Build a multi-tier ecommerce store …” therefore
became a BUILD requirement. The fallback then did this:

```python
# before, CONFIG/DOC/BUILD with no matching file
if assigned_sources:
    target = assigned_sources[0]; role = SOURCE
    ambiguities.append(f"{rid} ({intent.value}) has no matching file; attached to {target}")
```

With no source yet assigned, the target stayed `None` → ambiguity → plan
rejected. Attaching to an unrelated source (when one existed) also produced a
role conflict/ambiguity.

### Correction

- `requirement_intent()` now recognises build-**system nouns** only
  (`makefile`, `dockerfile`, `docker-compose`, `build system`, `build script`,
  `build pipeline`, `ci build`, `requirements.txt`, `setup.py`). Bare “build”,
  “setup” and business wording are SOURCE.
- Necessary CONFIG/DOC/BUILD requirements receive deterministic,
  role-appropriate targets instead of being attached to a source file:
  `config/<req>.yaml`, `docs/<req>.md`, `build/<req>.py`
  (`_synthesize_target`). `detect_file_role()` recognises `config/` data files
  and `build/` scripts.
- Requirement IDs remain the map key, so traceability is unchanged; the target
  is stable per id, so contract hashes remain deterministic.
- Nothing was invented for SOURCE or TEST roles: those still prefer explicit
  files and the requested pool, and only synthesize when the user named none.
- `validate_contract_plan()` was not changed; its rejection conditions remain.

## 2. Requirement extraction + evidence (tests 26, 38, 40)

`RequirementExtractor._extract_functional_from_prompt()` only treated these
verbs as explicit user work:

```
add create build generate implement support allow enable include provide
handle integrate update
```

`fix`, `repair`, `refactor`, `clean`, `remove`, `delete`, `rename`, `move`,
`improve`, `migrate`, `optimize`, `replace`, `extend`, `reduce` were not
recognised, and the guard `len(sent) > 10` dropped “Clean task”. The analyzer
returned only optional suggestions; the contract had no mandatory requirement;
verification had no requirement evidence and returned `NOT_TESTED`, so the
verdict was `FAILED`.

### Correction

- The verb list now includes the repair/refactor/cleanup family.
- The sentence guard is `len(sent) >= 6`, so a short imperative request is still
  a requirement while one-word noise is not.
- No contract-validation relaxation; this makes the user's request a real
  explicit requirement with a role-correct target.

## 3. Contract before/after (eight prompts)

Before: no requirement-map entry or an ambiguity for `REQ-001`.

After (`logs/contracts-after.txt`):

| Case | Requirement map | Ambiguities |
|---|---|---|
| test_02 | `REQ-001 -> src/req_001_module.py` | none |
| test_04 | `REQ-001 -> src/req_001_module.py` | none |
| test_05 | `REQ-001 -> src/req_001_module.py` | none |
| test_11 | `REQ-001 -> src/req_001_module.py` | none |
| test_26 | `REQ-001 -> src/req_001_module.py` | none |
| test_38 | `REQ-001 -> auth_bug.py` | none |
| test_40 | `REQ-001 -> src/req_001_module.py` | none |
| test_42 | `REQ-001 -> src/req_001_module.py` | none |

## 4. Safety properties retained

- Explicit/user-named files win (`test_user_named_file_stays_authoritative`).
- Optional suggestions are excluded from mandatory work.
- Empty/ambiguous requirements still produce a contract ambiguity and are
  rejected by the unchanged validator.
- Same-target requirements coalesce into one work unit; IDs survive.
- Dispatch budget is still enforced (`test_dispatch_budget_is_still_enforced`).
- Contract hashes stay deterministic (`test_contract_hash_is_deterministic`).
