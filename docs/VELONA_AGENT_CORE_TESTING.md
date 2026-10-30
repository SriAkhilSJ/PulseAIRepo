# Test Agent Core with a Velona key

PulseAI already supports OpenAI-compatible endpoints through its generic `custom`
provider. Velona does **not** need a provider-specific SDK, workflow, selector, or
source-code change.

This guide keeps the credential outside Git and tests these routes:

| Purpose | Provider | Model |
|---|---|---|
| Main Agent Core model | `custom` | `z-ai/glm-5.3-flash` |
| Auxiliary/management model | `custom` | `scaledown/summarize` |

Both routes use `https://velona.in/v1` and the same `CUSTOM_API_KEY`.
The model catalog and prices can change, so re-check the model IDs in Velona before
a later paid run.

## Security rules

- Never put the real key in source code, this document, a prompt, a commit, or a
  command-line argument.
- Never paste the key into chat or print it in logs.
- Enter it through a hidden terminal prompt or store it as a GitHub Actions secret
  named `CUSTOM_API_KEY`.
- Remove surrounding whitespace before starting Python. An accidental copied newline
  becomes an invalid HTTP authorization header.
- Run evidence in a temporary directory, not inside the repository.
- Unset the key when testing is finished.

> **Important:** the repository-root `.env` is loaded with `override=True`. If `.env`
> exists, its values override terminal exports. For a terminal-only test, first make
> sure `.env` is absent or contains the same non-secret route values and a correctly
> trimmed key. Never commit `.env`.

## 0. Is the key real? One command, no tokens spent on a turn

`scripts/check_velona_keys.py` answers that before anything else:

```bash
export CUSTOM_API_KEY='...'          # or CUSTOM_API_KEYS='a,b'
python scripts/check_velona_keys.py           # add --offline for shape only, --json for machines
```

It reports the key's fingerprint (length + last four — never the key), whether it
authenticates against the gateway catalog, and one 1-token chat call per pinned
model. Exit 0 green, 1 failed, 2 nothing to check.

On CI the same check runs as `Verify provider key` against the `CUSTOM_API_KEY`
repository secret and posts its verdict to issue #28, because the secret can only
be exercised on a runner. Measured 2026-10-30 (commit `6e114be6`):

| Model | Route | Result | 1-token latency |
|---|---|---|---|
| `z-ai/glm-5.3-flash` | main | HTTP 200 | 13.8 s |
| `deepseek/deepseek-v4.1-flash` | main | HTTP 200 | 1.0 s |
| `qwen/qwen3.7-flash` | aux | HTTP 200 | 1.3 s |

GLM's first token is an order of magnitude slower at `max_tokens=1`: it spends the
budget on reasoning before emitting. Budget for that on the main route; do not read
it as a network problem.

## 1. Install the supported runtime

From the repository root:

```bash
uv sync --group dev
```

## 2. Configure one terminal session

### Bash, zsh, or Git Bash

The hidden prompt prevents the key from entering shell history:

```bash
read -rsp "Velona API key: " CUSTOM_API_KEY; echo
export CUSTOM_API_KEY
export CUSTOM_API_KEY="$(python -c 'import os,sys; sys.stdout.write(os.environ["CUSTOM_API_KEY"].strip())')"
test -n "$CUSTOM_API_KEY" || { echo "Key is empty" >&2; return 1 2>/dev/null || exit 1; }

export CUSTOM_BASE_URL='https://velona.in/v1'
export LLM_PROVIDER='custom'
export LLM_MODEL='z-ai/glm-5.3-flash'
export CONTEXT_MODEL='z-ai/glm-5.3-flash'

# AUX uses the same custom endpoint and key, but a separate request client.
export AUX_LLM_PROVIDER='custom'
export AUX_LLM_MODEL='scaledown/summarize'

# Velona's edge accepts a normal browser User-Agent for OpenAI-compatible calls.
export CRUSORAI_HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
export CRUSORAI_LLM_STREAMING='on'
```

### PowerShell

```powershell
$secureKey = Read-Host "Velona API key" -AsSecureString
$keyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $env:CUSTOM_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPtr).Trim()
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPtr)
}
if ([string]::IsNullOrWhiteSpace($env:CUSTOM_API_KEY)) { throw "Key is empty" }

$env:CUSTOM_BASE_URL = "https://velona.in/v1"
$env:LLM_PROVIDER = "custom"
$env:LLM_MODEL = "z-ai/glm-5.3-flash"
$env:CONTEXT_MODEL = "z-ai/glm-5.3-flash"
$env:AUX_LLM_PROVIDER = "custom"
$env:AUX_LLM_MODEL = "scaledown/summarize"
$env:CRUSORAI_HTTP_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
$env:CRUSORAI_LLM_STREAMING = "on"
```

## 3. Verify configuration without making a request

This prints route names only. It does not print any part of the key.

```bash
uv run python - <<'PY'
from src.config import settings

assert settings.LLM_PROVIDER == "custom"
assert settings.LLM_MODEL == "z-ai/glm-5.3-flash"
assert settings.CUSTOM_BASE_URL == "https://velona.in/v1"
assert settings.CUSTOM_API_KEY
assert settings.CUSTOM_API_KEY == settings.CUSTOM_API_KEY.strip()
assert settings.AUX_LLM_PROVIDER == "custom"
assert settings.AUX_LLM_MODEL == "scaledown/summarize"
print("PASS: main=custom/z-ai/glm-5.3-flash")
print("PASS: aux=custom/scaledown/summarize")
print("PASS: key is present and trimmed (value not printed)")
PY
```

For PowerShell, save the Python block to a temporary `.py` file or run the equivalent
commands with `uv run python -c`.

## 4. Make tiny live main and AUX requests

This uses PulseAI's real factory. It sends two small paid requests and prints only pass
status and response length.

```bash
CRUSORAI_LLM_STREAMING=off uv run python - <<'PY'
from src.llm.factory import get_auxiliary_llm, get_llm

main = get_llm(
    "custom",
    "z-ai/glm-5.3-flash",
    max_attempts=1,
    request_timeout=30.0,
)
main_reply = main.invoke("Reply with only READY.")
main_text = str(getattr(main_reply, "content", main_reply) or "").strip()
assert main_text, "main model returned no text"
print(f"PASS: main endpoint answered ({len(main_text)} characters)")

aux = get_auxiliary_llm()
aux_reply = aux.invoke("Summarize this as one word: Agent Core is ready.")
aux_text = str(getattr(aux_reply, "content", aux_reply) or "").strip()
assert aux_text, "AUX model returned no text"
print(f"PASS: AUX endpoint answered ({len(aux_text)} characters)")
PY
```

If this fails, do not start Agent Core until the endpoint test passes.

## 5. Run one genuine bounded Agent Core turn

The runner starts `python -m src.bridge`, creates a fresh session, exercises the real
agent/tool loop, records sanitized frames, and stops at strict spend/time bounds.

```bash
RUN_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/pulseai-velona.XXXXXX")"
WORKSPACE="$RUN_ROOT/workspace"
PROMPT_FILE="$RUN_ROOT/prompt.txt"
RESULTS_ROOT="$RUN_ROOT/results"
RUN_ID="velona-agent-core-$(date +%Y%m%d%H%M%S)"
mkdir -p "$WORKSPACE"

cat > "$PROMPT_FILE" <<'EOF'
Create a file named velona-smoke.txt in the workspace containing exactly:
VELONA_AGENT_CORE_OK
Verify the file, then finish with a concise confirmation.
EOF

uv run python scripts/run_bridge_turn.py \
  --workspace "$WORKSPACE" \
  --prompt-file "$PROMPT_FILE" \
  --run-id "$RUN_ID" \
  --timeout-s 600 \
  --max-llm-calls 8 \
  --max-input-tokens 80000 \
  --max-no-delivery-calls 4 \
  --results-root "$RESULTS_ROOT"
```

Verify both the bridge result and the delivered file:

```bash
uv run python - "$RESULTS_ROOT/$RUN_ID/outcome.json" "$WORKSPACE/velona-smoke.txt" <<'PY'
import json
import sys
from pathlib import Path

outcome = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
delivered = Path(sys.argv[2])
assert outcome.get("result") == "turn_done", outcome
assert outcome.get("completed") is True, outcome
assert outcome.get("llm_request_frames", 0) >= 1, outcome
assert delivered.is_file(), "Agent Core did not create velona-smoke.txt"
assert delivered.read_text(encoding="utf-8").strip() == "VELONA_AGENT_CORE_OK"
print("PASS: genuine bounded Agent Core turn completed")
print(f"Evidence directory: {Path(sys.argv[1]).parent}")
PY
```

A valid result has all of the following:

- `result` is `turn_done`;
- `completed` is `true`;
- at least one `llm.request` frame was observed;
- `velona-smoke.txt` exists with the exact requested content;
- no budget, no-delivery, or timeout stop occurred.

## 6. Store the key for GitHub Actions (optional)

GitHub secrets are write-only after creation. Normalize the key before storing it so
runner HTTP headers cannot contain copied whitespace:

```bash
read -rsp "Velona API key: " VELONA_KEY; echo
VELONA_KEY="$(VELONA_KEY="$VELONA_KEY" python -c 'import os,sys; sys.stdout.write(os.environ["VELONA_KEY"].strip())')"
test -n "$VELONA_KEY" || { echo "Key is empty" >&2; return 1 2>/dev/null || exit 1; }
printf '%s' "$VELONA_KEY" | gh secret set CUSTOM_API_KEY
unset VELONA_KEY
```

A test job can then expose the existing generic-provider variables to its shell:

```yaml
env:
  CUSTOM_API_KEY: ${{ secrets.CUSTOM_API_KEY }}
  CUSTOM_BASE_URL: https://velona.in/v1
  LLM_PROVIDER: custom
  LLM_MODEL: z-ai/glm-5.3-flash
  CONTEXT_MODEL: z-ai/glm-5.3-flash
  AUX_LLM_PROVIDER: custom
  AUX_LLM_MODEL: scaledown/summarize
  CRUSORAI_HTTP_USER_AGENT: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36
```

Do not upload `.env`, raw bridge stderr, or unrestricted workspace archives as Actions
artifacts. Keep only bounded, sanitized evidence.

## 7. Remove the credential from the terminal

### Bash, zsh, or Git Bash

```bash
unset CUSTOM_API_KEY
```

### PowerShell

```powershell
Remove-Item Env:CUSTOM_API_KEY -ErrorAction SilentlyContinue
```

## Troubleshooting

| Symptom | Meaning and next action |
|---|---|
| `LocalProtocolError: Illegal header value` | The copied key contains whitespace/newlines. Re-enter it and trim before Python starts. |
| HTTP `401` or `403` auth response | Verify the Velona key/account. Never print the key while diagnosing. |
| Cloudflare-style `403` before auth | Confirm `CRUSORAI_HTTP_USER_AGENT` is set before the client is created. |
| HTTP `404` / unsupported model | Re-check the exact model ID in the live Velona catalog. |
| HTTP `429` | Stop and honor the provider's retry delay; do not launch repeated paid runs. |
| Settings show another provider/model | A repository-root `.env` is overriding the terminal exports. |
| Endpoint probes pass but Agent Core fails | Inspect the bounded `outcome.json`, `frames.jsonl`, and sanitized `bridge_stderr.log` from the temporary results directory. |
