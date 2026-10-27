# Colibri-backed Agent Core on Kaggle

This lane runs a real PulseAI Agent Core turn in the **same Kaggle kernel** as a local
[Colibri](https://github.com/JustVugg/colibri) OpenAI-compatible server. Keeping both
processes in one kernel avoids exposing a notebook port or pretending that a local desktop
can call Kaggle's loopback interface.

## Current proof boundary

The checked-in code and notebook are reproducible launch artifacts. A result is real only
when the generated `run_receipt.json` says the required phases passed. Repository tests and
MCP tool discovery prove wiring; they do **not** prove that Kaggle allocated a GPU or that
the selected model generated tokens.

No Kaggle credential belongs in this repository, a notebook, a result bundle, or chat.
Kaggle authentication must be supplied through the operator's secure environment or
`~/.kaggle/kaggle.json`.

## Model selection

The machine-readable decision is [`model_manifest.json`](model_manifest.json).

| Property | Selected operating point |
|---|---|
| Model | Qwen3.6-35B-A3B |
| Colibri catalog id | `qwen36-35b` |
| Converted checkpoint | `Kreuzzelg/qwen36-35b-a3b-colibri-i4-gs64` |
| Download | 23.1 GB decimal (catalog value) |
| Colibri RAM guidance | 10 GB minimum / 20 GB good |
| Engine context | 8,192 default / 262,144 architectural maximum |
| First run | 65,536 configured; ~16,384-token retention probe |
| Tools | Native Qwen3.6 tool-call/tool-response translation |
| GPU | Colibri CUDA expert tier; execution is proven only by runtime markers plus a completed generation |

Qwen3-Coder-30B-A3B is smaller and coding-specialized, but all 48 layers use full
attention. Qwen3.6 uses only 10 full-attention layers, so its long-context state is a better
first fit for Kaggle-class host memory. The runner will not promote the first run to
131,072 tokens unless the 65,536-token resource plan and receipts pass with headroom.

## What the run does

`kaggle_runner.py` is the authority. The notebook only clones PulseAI and invokes it.

1. Fails closed unless RAM, free disk, `nvidia-smi`, and `nvcc` meet the declared gates.
2. Checks out Colibri commit `e0db083cdc9e563e0766cc6fc661ef23c32298e0`.
3. Builds `c/qwen36` with `CUDA=1` and verifies that it links `libcudart`.
4. Resolves the model's `main` revision once, records the immutable Hugging Face commit,
   and downloads exactly that commit under `/kaggle/temp`.
5. Saves Colibri's machine-local 65,536-token resource plan.
6. Starts `coli serve` on loopback and runs:
   - health and model identity;
   - basic generation;
   - a forced typed tool call;
   - a tool-result round trip;
   - retention of markers across an approximately 16,384-token filler prompt.
7. Configures PulseAI's existing custom provider seam with:
   - `LLM_PROVIDER=custom`
   - `LLM_MODEL=qwen3.6-colibri`
   - `CUSTOM_BASE_URL=http://127.0.0.1:8000/v1`
   - `LLM_CONTEXT_WINDOW=65536`
8. Runs a bounded, read-only bridge turn against a tiny bug fixture, requires grounded tool
   traffic, and checks that fixture bytes did not change.
9. Validates the per-turn evidence manifest, artifact hashes, journal chain, terminal
   identity, counts, and tool pairing with `--require-complete`.
10. Writes only bounded receipts/logs/evidence to `/kaggle/working`; the 23 GB model is not
    included in kernel output.

Colibri's current `/v1/models` response does not publish the configured context length.
The explicit `LLM_CONTEXT_WINDOW` is therefore required and must match `coli serve --ctx`.
At the pinned commit, the qwen36 family registry also has a stale descriptive
`capabilities.tools=false` bit even though `docs/api.md` and the Qwen3.6 gateway renderer
implement native tool calls. The run therefore requires a behavioral forced-tool and
round-trip pass rather than trusting that metadata bit.

## Kaggle MCP path

The inspected stdio candidate is `mtrakretech/kaggle-mcp` v3.1 at commit
`bb8c9539a0efe966000fb59d15be12aef2912df2`. It exposes 74 tools, including
`list_my_kernels`, `push_notebook`, `kernel_status`, `kernel_files`, and `kernel_output`.
It is community software, not Kaggle's official remote MCP.

A compatibility check with Kaggle CLI 1.8.4 found that the candidate's advertised
`get_quota` and `kernel_logs` tools shell out to nonexistent `kaggle quota` and
`kaggle kernels logs` commands. **Do not use either tool as evidence.** The supported
kernel commands reach the current CLI/API path; actual authentication, quota, allocation,
and execution still require live receipts.

Install it outside this repository and pin both inspected revisions:

```bash
git clone https://github.com/mtrakretech/kaggle-mcp.git /absolute/path/kaggle-mcp
git -C /absolute/path/kaggle-mcp checkout bb8c9539a0efe966000fb59d15be12aef2912df2
python -m pip install "requests>=2.28" "kaggle==1.8.4"
python /absolute/path/kaggle-mcp/kaggle_mcp.py --list-tools
```

Configure PulseAI in the **test workspace's ignored** `.crusorai/mcp.json`:

```json
{
  "servers": {
    "kaggle": {
      "command": "python",
      "args": [
        "/absolute/path/kaggle-mcp/kaggle_mcp.py",
        "--stdio"
      ],
      "env": {},
      "enabled": true
    }
  }
}
```

Leave credentials out of that file. This candidate needs `KAGGLE_USERNAME` plus either
`KAGGLE_KEY` or `KAGGLE_API_TOKEN`, inherited from the launching environment, or the
matching values in a mode-600 `~/.kaggle/kaggle.json`.

After authentication, the guarded tool sequence is:

1. `mcp_kaggle_list_my_kernels` with `limit: 1` — require a successful authenticated
   response. This proves account access, not available GPU quota.
2. Treat GPU quota as **unknown** because Kaggle CLI 1.8.4 has no quota command. Do not
   infer availability from tool discovery or kernel metadata; proceed only when spending
   the account's GPU allocation is authorized, and let the kernel receipt prove allocation.
3. `mcp_kaggle_push_notebook` with:
   - `path`: the absolute path to `kaggle/colibri_agent_core.ipynb`
   - `name`: `pulseai-colibri-agent-core`
   - `gpu`: `true`
   - `tpu`: `false`
   - `internet`: `true`
   - `private`: `true`
4. `mcp_kaggle_kernel_status` until a terminal state.
5. `mcp_kaggle_kernel_files`, then `mcp_kaggle_kernel_output` to retrieve the result
   archive and SHA-256 sidecar. Build/model/runtime diagnostics are inside that archive;
   do not call the candidate's incompatible `kernel_logs` tool.

`push_notebook` generates account-specific kernel metadata itself. The checked-in
`kernel-metadata.template.json` is only for a manual Kaggle CLI fallback; replace
`KAGGLE_USERNAME` outside Git before using it.

### GitHub Actions secret bridge

`.github/workflows/kaggle-colibri-agent-core.yml` is restricted to this session branch,
has no pull-request trigger, and uses `contents: read`. The public Kaggle account handle is
pinned as `sriakhilsj`; only repository secret `KAGGLE_API_TOKEN` is scoped to the MCP
orchestration step. A push runs the expensive job only when its commit message contains
`[kaggle-colibri]`;
the job uploads bounded receipts and downloaded kernel output as a 14-day Actions
artifact. It never commits evidence, model weights, or credentials to Git.

For a running or terminal private kernel, `.github/workflows/kaggle-live-diagnostics.yml`
uses the official SDK's session-status, accelerator-quota, and log-stream endpoints. A
`[kaggle-logs]` commit reads for at most 30 seconds, retains only a rolling 256 KiB suffix,
decodes persisted structured worker records, and redacts credentials and terminal controls.
It publishes at most 12,000 characters of actionable phase neighborhoods (or the terminal
tail when no known phase is present) in bounded check annotations. It is read-only and does
not interrupt the kernel.

## Local validation (no GPU claim)

Validate configuration without network, model weights, or GPU work:

```bash
python -m benchmarks.colibri_agent_core.kaggle_runner \
  --dry-run --allow-non-kaggle \
  --runtime-root /tmp/pulseai-colibri-dry-runtime \
  --output-root /tmp/pulseai-colibri-dry-results
```

Run the endpoint probe against any already-running Colibri server:

```bash
CUSTOM_API_KEY=local-only python -m benchmarks.colibri_agent_core.probe \
  --base-url http://127.0.0.1:8000/v1 \
  --model qwen3.6-colibri \
  --expected-context 65536 \
  --long-context-tokens 16384 \
  --output /tmp/colibri-probe.json
```

## Acceptance receipts

A successful `run_receipt.json` must establish all of the following independently:

- GPU inventory and CUDA toolkit were visible inside the kernel.
- The built qwen36 binary linked `libcudart`.
- Colibri's server log contains both CUDA expert-tier activation markers.
- A real basic generation passed while that server was running.
- Health, model identity, forced tool call, tool-result round trip, and long-context phases passed.
- The real Agent Core bridge turn completed, emitted tool frames, and left fixture bytes unchanged.
- Runtime evidence reports `integrity_valid=true` and `capture_complete=true`.

If any item is absent, the runner records `failed`; it never upgrades architectural support,
a clean build, or an MCP upload into proof of GPU inference.
