#!/usr/bin/env python3
"""Probe a live Colibri OpenAI endpoint before an Agent Core turn.

The probe is intentionally independent of LangChain. It distinguishes the
model server contract from PulseAI's bridge/runtime contract and produces a
small JSON receipt without persisting prompts, credentials, or full model
responses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.colibri_agent_core import SCHEMA_VERSION

_CONTEXT_KEYS = (
    "context_window",
    "context_length",
    "max_context_length",
    "max_position_embeddings",
    "max_model_len",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _bounded_text(value: Any, limit: int = 500) -> str:
    if isinstance(value, list):
        value = "".join(
            str(part.get("text") or "") if isinstance(part, dict) else str(part)
            for part in value
        )
    text = str(value or "").replace("\x00", "")
    return text[:limit]


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class Phase:
    name: str
    status: str
    elapsed_seconds: float
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "evidence": self.evidence,
        }
        if self.error:
            payload["error"] = self.error[:1000]
        return payload


class ColibriProbe:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        expected_context: int,
        timeout_seconds: float,
        long_context_tokens: int,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        self.v1 = normalized if normalized.endswith("/v1") else f"{normalized}/v1"
        self.root = self.v1[:-3].rstrip("/")
        self.api_key = api_key
        self.model = model
        self.expected_context = expected_context
        self.timeout_seconds = timeout_seconds
        self.long_context_tokens = long_context_tokens
        self.phases: list[Phase] = []
        self._tool_call: dict[str, Any] | None = None
        self._tool_nonce = f"probe-{secrets.token_hex(6)}"

    def _request(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any], float]:
        data = None
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                raw = response.read()
                status = int(response.status)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            detail = raw.decode("utf-8", "replace")[:1000]
            raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc
        elapsed = time.monotonic() - started
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"HTTP {status} from {url} was not a JSON object ({len(raw)} bytes)"
            ) from exc
        if not isinstance(decoded, dict):
            raise TypeError(
                f"HTTP {status} from {url} returned {type(decoded).__name__}"
            )
        return status, decoded, elapsed

    def _chat(self, body: dict[str, Any]) -> tuple[dict[str, Any], float]:
        payload = {"model": self.model, "temperature": 0, **body}
        status, response, elapsed = self._request(
            "POST", f"{self.v1}/chat/completions", payload
        )
        if status != 200:
            raise RuntimeError(f"chat endpoint returned HTTP {status}")
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("chat response has no choices")
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise TypeError("chat response has no assistant message")
        return response, elapsed

    def _run_phase(self, name: str, fn: Callable[[], dict[str, Any]]) -> None:
        started = time.monotonic()
        try:
            evidence = fn()
            self.phases.append(
                Phase(name, "passed", time.monotonic() - started, evidence=evidence)
            )
        except Exception as exc:  # noqa: BLE001 - every failed phase needs a receipt
            self.phases.append(
                Phase(
                    name,
                    "failed",
                    time.monotonic() - started,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    def _health(self) -> dict[str, Any]:
        status, body, elapsed = self._request("GET", f"{self.root}/health")
        if status != 200:
            raise RuntimeError(f"health endpoint returned HTTP {status}")
        return {
            "http_status": status,
            "request_seconds": round(elapsed, 3),
            "state": body.get("state") or body.get("status"),
            "model": body.get("model") or body.get("model_id"),
            "arch": body.get("arch"),
            "response_sha256": _sha256_json(body),
        }

    def _models(self) -> dict[str, Any]:
        status, body, elapsed = self._request("GET", f"{self.v1}/models")
        entries = body.get("data")
        if status != 200 or not isinstance(entries, list):
            raise RuntimeError("model catalog did not return an OpenAI data list")
        ids = [str(item.get("id") or "") for item in entries if isinstance(item, dict)]
        if self.model not in ids:
            raise RuntimeError(
                f"configured model {self.model!r} is absent from {ids!r}"
            )
        selected = next(item for item in entries if item.get("id") == self.model)
        published = next(
            (
                int(selected[key])
                for key in _CONTEXT_KEYS
                if isinstance(selected.get(key), int)
            ),
            None,
        )
        if published is not None and published < self.expected_context:
            raise RuntimeError(
                f"endpoint publishes {published} tokens, below expected {self.expected_context}"
            )
        return {
            "http_status": status,
            "request_seconds": round(elapsed, 3),
            "ids": ids,
            "selected_capabilities": selected.get("capabilities"),
            "published_context_window": published,
            "configured_context_window": self.expected_context,
            "context_source": (
                "endpoint_metadata" if published is not None else "runner_configuration"
            ),
        }

    def _basic_chat(self) -> dict[str, Any]:
        sentinel = f"PULSEAI_COLIBRI_READY_{secrets.token_hex(4)}"
        response, elapsed = self._chat(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": f"Reply with this exact token and nothing else: {sentinel}",
                    }
                ],
                "max_tokens": 64,
            }
        )
        choice = response["choices"][0]
        text = _bounded_text(choice["message"].get("content"))
        if sentinel not in text:
            raise RuntimeError(
                "assistant reply did not preserve the readiness sentinel"
            )
        return {
            "request_seconds": round(elapsed, 3),
            "finish_reason": choice.get("finish_reason"),
            "sentinel_preserved": True,
            "response_preview": text,
            "usage": response.get("usage"),
        }

    @staticmethod
    def _decode_arguments(call: dict[str, Any]) -> dict[str, Any]:
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            raise TypeError("tool-call arguments are not a JSON object")
        return arguments

    def _forced_tool_call(self) -> dict[str, Any]:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "report_colibri_probe",
                    "description": "Report that the local inference probe is ready.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nonce": {"type": "string"},
                            "status": {"type": "string", "enum": ["ready"]},
                        },
                        "required": ["nonce", "status"],
                    },
                },
            }
        ]
        response, elapsed = self._chat(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Call report_colibri_probe now with nonce "
                            f"{self._tool_nonce!r} and status 'ready'. Do not answer in prose."
                        ),
                    }
                ],
                "tools": tools,
                "tool_choice": {
                    "type": "function",
                    "function": {"name": "report_colibri_probe"},
                },
                "max_tokens": 256,
            }
        )
        choice = response["choices"][0]
        calls = choice["message"].get("tool_calls")
        if not isinstance(calls, list) or len(calls) != 1:
            raise RuntimeError(
                f"expected exactly one tool call, received {len(calls or [])}"
            )
        call = calls[0]
        function = call.get("function") or {}
        if function.get("name") != "report_colibri_probe":
            raise RuntimeError(f"unexpected tool name {function.get('name')!r}")
        arguments = self._decode_arguments(call)
        if arguments != {"nonce": self._tool_nonce, "status": "ready"}:
            raise RuntimeError(f"unexpected tool arguments {arguments!r}")
        self._tool_call = call
        return {
            "request_seconds": round(elapsed, 3),
            "finish_reason": choice.get("finish_reason"),
            "tool_name": function.get("name"),
            "arguments_valid": True,
            "usage": response.get("usage"),
        }

    def _tool_round_trip(self) -> dict[str, Any]:
        if self._tool_call is None:
            raise RuntimeError("forced tool-call phase did not produce a call")
        sentinel = f"TOOL_ROUNDTRIP_{self._tool_nonce}"
        response, elapsed = self._chat(
            {
                "messages": [
                    {"role": "user", "content": "Run the local readiness probe."},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [self._tool_call],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": self._tool_call.get("id") or "probe-call",
                        "content": json.dumps({"ok": True, "receipt": sentinel}),
                    },
                ],
                "max_tokens": 128,
            }
        )
        choice = response["choices"][0]
        text = _bounded_text(choice["message"].get("content"))
        if sentinel not in text:
            raise RuntimeError("assistant did not preserve the tool-result sentinel")
        return {
            "request_seconds": round(elapsed, 3),
            "finish_reason": choice.get("finish_reason"),
            "tool_result_preserved": True,
            "response_preview": text,
            "usage": response.get("usage"),
        }

    def _long_context(self) -> dict[str, Any]:
        if self.long_context_tokens <= 0:
            return {"skipped": True, "reason": "long_context_tokens=0"}
        start_marker = f"START_{secrets.token_hex(8)}"
        end_marker = f"END_{secrets.token_hex(8)}"
        # "calibration" is normally one Qwen token. The count is deliberately
        # labelled approximate; the immutable request byte size and hash make
        # the actual payload reproducible without persisting its full body.
        filler = "calibration " * self.long_context_tokens
        content = (
            f"Remember the first marker: {start_marker}.\n"
            f"{filler}\n"
            f"Remember the final marker: {end_marker}.\n"
            "Return both markers exactly, separated by one space."
        )
        body = {
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 128,
        }
        response, elapsed = self._chat(body)
        choice = response["choices"][0]
        text = _bounded_text(choice["message"].get("content"), 1000)
        start_ok, end_ok = start_marker in text, end_marker in text
        if not (start_ok and end_ok):
            raise RuntimeError(
                f"long-context retrieval failed (start={start_ok}, end={end_ok})"
            )
        return {
            "request_seconds": round(elapsed, 3),
            "filler_tokens_approx": self.long_context_tokens,
            "request_utf8_bytes": len(content.encode("utf-8")),
            "request_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "start_marker_preserved": start_ok,
            "end_marker_preserved": end_ok,
            "finish_reason": choice.get("finish_reason"),
            "response_preview": text,
            "usage": response.get("usage"),
        }

    def run(self) -> dict[str, Any]:
        started_at = _utc_now()
        self._run_phase("health", self._health)
        self._run_phase("models", self._models)
        self._run_phase("basic_chat", self._basic_chat)
        self._run_phase("forced_tool_call", self._forced_tool_call)
        self._run_phase("tool_result_round_trip", self._tool_round_trip)
        if self.long_context_tokens > 0:
            self._run_phase("long_context", self._long_context)
        passed = all(phase.status == "passed" for phase in self.phases)
        return {
            "schema": SCHEMA_VERSION,
            "kind": "colibri_endpoint_probe",
            "started_at": started_at,
            "finished_at": _utc_now(),
            "status": "passed" if passed else "failed",
            "endpoint": self.v1,
            "api_key_present": bool(self.api_key),
            "api_key_persisted": False,
            "model": self.model,
            "expected_context_window": self.expected_context,
            "phases": [phase.to_dict() for phase in self.phases],
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("CUSTOM_BASE_URL", "http://127.0.0.1:8000/v1"),
    )
    parser.add_argument("--api-key", default=os.getenv("CUSTOM_API_KEY", ""))
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", "qwen3.6-colibri"))
    parser.add_argument("--expected-context", type=int, default=65536)
    parser.add_argument(
        "--long-context-tokens",
        type=int,
        default=16384,
        help="approximate filler-token count; 0 disables this phase",
    )
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.base_url.strip():
        print("--base-url (or CUSTOM_BASE_URL) is required", file=sys.stderr)
        return 2
    if not args.model.strip():
        print("--model (or LLM_MODEL) is required", file=sys.stderr)
        return 2
    if args.expected_context < 8192:
        print("--expected-context must be at least 8192", file=sys.stderr)
        return 2
    if args.long_context_tokens < 0:
        print("--long-context-tokens cannot be negative", file=sys.stderr)
        return 2
    probe = ColibriProbe(
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        expected_context=args.expected_context,
        timeout_seconds=max(1.0, args.timeout_seconds),
        long_context_tokens=args.long_context_tokens,
    )
    result = probe.run()
    if args.output:
        _atomic_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
