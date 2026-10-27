#!/usr/bin/env python3
"""Run bounded, secret-safe live checks for Velona main and auxiliary models."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_SAFE_USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
)


def _bounded_text(value: Any, limit: int = 800) -> str:
    if isinstance(value, list):
        value = "".join(
            str(part.get("text") or "") if isinstance(part, dict) else str(part)
            for part in value
        )
    return str(value or "").replace("\x00", "")[:limit]


def _safe_error(exc: Exception, api_key: str) -> str:
    text = f"{type(exc).__name__}: {exc}".replace(api_key, "[REDACTED]")
    text = re.sub(
        r"(?i)(bearer\s+)[a-z0-9._~+/=-]{8,}", r"\1[REDACTED]", text
    )
    return text.replace("\x00", "")[:1200]


def _safe_usage(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    receipt: dict[str, int] = {}
    for key in _SAFE_USAGE_KEYS:
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            receipt[key] = value
    return receipt


def _workflow_escape(value: Any) -> str:
    return (
        str(value)
        .replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )


def _github_annotation(level: str, title: str, message: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(
            f"::{level} title={_workflow_escape(title)}::"
            f"{_workflow_escape(message)}"
        )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


@dataclass
class Phase:
    name: str
    status: str
    elapsed_seconds: float
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "name": self.name,
            "status": self.status,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "evidence": self.evidence,
        }
        if self.error:
            result["error"] = self.error
        return result


class VelonaModelProbe:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        main_model: str,
        aux_model: str,
        timeout: float,
    ) -> None:
        self.v1 = base_url.strip().rstrip("/")
        if not self.v1.endswith("/v1"):
            self.v1 += "/v1"
        self.api_key = api_key
        self.main_model = main_model
        self.aux_model = aux_model
        self.timeout = max(1.0, timeout)
        self.phases: list[Phase] = []
        self._tool_call: dict[str, Any] | None = None
        self._tool_prompt = ""
        self._tool_nonce = f"velona-{secrets.token_hex(6)}"

    def _request(self, body: dict[str, Any]) -> tuple[dict[str, Any], float]:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.v1}/chat/completions",
            data=encoded,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                status = int(response.status)
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        elapsed = time.monotonic() - started
        if status != 200:
            raise RuntimeError(f"chat endpoint returned HTTP {status}")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("chat endpoint returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise TypeError("chat endpoint did not return a JSON object")
        return payload, elapsed

    def _chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        **extra: Any,
    ) -> tuple[dict[str, Any], dict[str, Any], float]:
        response, elapsed = self._request(
            {
                "model": model,
                "messages": messages,
                "temperature": 0,
                "max_tokens": max_tokens,
                **extra,
            }
        )
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("chat response has no choices")
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise RuntimeError("chat response has no assistant message")
        return response, choice, elapsed

    def _phase(self, name: str, operation: Callable[[], dict[str, Any]]) -> None:
        started = time.monotonic()
        try:
            evidence = operation()
            self.phases.append(
                Phase(name, "passed", time.monotonic() - started, evidence)
            )
        except Exception as exc:  # noqa: BLE001 - each failure needs a receipt
            self.phases.append(
                Phase(
                    name,
                    "failed",
                    time.monotonic() - started,
                    error=_safe_error(exc, self.api_key),
                )
            )

    def _basic(self, model: str, label: str) -> dict[str, Any]:
        sentinel = f"{label}_{secrets.token_hex(5)}"
        messages = [
            {
                "role": "user",
                "content": f"Reply with exactly this token: {sentinel}",
            }
        ]
        started = time.monotonic()
        attempts = 0
        for attempt in range(2):
            attempts += 1
            try:
                response, choice, _elapsed = self._chat(
                    model=model,
                    messages=messages,
                    max_tokens=256,
                )
                text = _bounded_text(choice["message"].get("content"))
                if sentinel not in text:
                    usage = _safe_usage(response.get("usage"))
                    raise RuntimeError(
                        f"{label} response did not preserve its sentinel "
                        f"(finish_reason={choice.get('finish_reason')!r}, "
                        f"content_chars={len(text)}, usage={usage})"
                    )
                return {
                    "model": model,
                    "request_seconds": round(time.monotonic() - started, 3),
                    "attempts": attempts,
                    "finish_reason": choice.get("finish_reason"),
                    "sentinel_preserved": True,
                    "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "usage": _safe_usage(response.get("usage")),
                }
            except (TimeoutError, urllib.error.URLError):
                if attempt:
                    raise
                time.sleep(0.4)
        raise AssertionError("unreachable")

    def _main_basic(self) -> dict[str, Any]:
        return self._basic(self.main_model, "MAIN_READY")

    def _aux_basic(self) -> dict[str, Any]:
        return self._basic(self.aux_model, "AUX_READY")

    @staticmethod
    def _arguments(call: dict[str, Any]) -> dict[str, Any]:
        function = call.get("function")
        if not isinstance(function, dict):
            raise RuntimeError("tool call has no function object")
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            raise RuntimeError("tool arguments are not a JSON object")
        return arguments

    def _main_tool_call(self) -> dict[str, Any]:
        self._tool_prompt = (
            "Call report_agent_core_probe with nonce "
            f"{self._tool_nonce!r} and status 'ready'. Do not answer in prose."
        )
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "report_agent_core_probe",
                    "description": "Report that the Agent Core provider probe is ready.",
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
        response, choice, elapsed = self._chat(
            model=self.main_model,
            messages=[{"role": "user", "content": self._tool_prompt}],
            max_tokens=256,
            tools=tools,
            tool_choice={
                "type": "function",
                "function": {"name": "report_agent_core_probe"},
            },
        )
        calls = choice["message"].get("tool_calls")
        if not isinstance(calls, list) or len(calls) != 1:
            raise RuntimeError(f"expected exactly one tool call, got {len(calls or [])}")
        call = calls[0]
        if not isinstance(call, dict):
            raise RuntimeError("tool call is not an object")
        function = call.get("function") or {}
        if function.get("name") != "report_agent_core_probe":
            raise RuntimeError("main model selected an unexpected tool")
        expected = {"nonce": self._tool_nonce, "status": "ready"}
        if self._arguments(call) != expected:
            raise RuntimeError("main model produced incorrect tool arguments")
        self._tool_call = call
        return {
            "model": self.main_model,
            "request_seconds": round(elapsed, 3),
            "finish_reason": choice.get("finish_reason"),
            "tool_name": "report_agent_core_probe",
            "arguments_valid": True,
            "usage": _safe_usage(response.get("usage")),
        }

    def _main_tool_replay(self) -> dict[str, Any]:
        if self._tool_call is None:
            raise RuntimeError("tool-call phase did not produce replay state")
        sentinel = f"TOOL_RESULT_{self._tool_nonce}"
        call = dict(self._tool_call)
        call.setdefault("id", f"call_{secrets.token_hex(4)}")
        response, choice, elapsed = self._chat(
            model=self.main_model,
            messages=[
                {"role": "user", "content": self._tool_prompt},
                {"role": "assistant", "content": None, "tool_calls": [call]},
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps({"ok": True, "receipt": sentinel}),
                },
            ],
            max_tokens=96,
        )
        text = _bounded_text(choice["message"].get("content"))
        if sentinel not in text:
            raise RuntimeError("main model did not preserve the tool-result sentinel")
        return {
            "model": self.main_model,
            "request_seconds": round(elapsed, 3),
            "finish_reason": choice.get("finish_reason"),
            "tool_result_preserved": True,
            "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "usage": _safe_usage(response.get("usage")),
        }

    def run(self) -> dict[str, Any]:
        self._phase("main_basic", self._main_basic)
        self._phase("main_forced_tool_call", self._main_tool_call)
        self._phase("main_tool_result_replay", self._main_tool_replay)
        self._phase("aux_basic", self._aux_basic)
        passed = all(phase.status == "passed" for phase in self.phases)
        return {
            "schema": "pulseai.velona_model_probe.v1",
            "status": "passed" if passed else "failed",
            "endpoint": self.v1,
            "api_key_present": bool(self.api_key),
            "api_key_persisted": False,
            "main_model": self.main_model,
            "aux_model": self.aux_model,
            "phases": [phase.to_dict() for phase in self.phases],
        }


def _publish_phase_annotations(receipt: dict[str, Any]) -> None:
    summaries: list[str] = []
    failed = False
    for phase in receipt.get("phases", []):
        if not isinstance(phase, dict):
            continue
        name = str(phase.get("name") or "unknown")
        status = str(phase.get("status") or "unknown")
        if status == "passed":
            evidence = phase.get("evidence") or {}
            summaries.append(
                f"{name}=passed"
                f"({evidence.get('request_seconds')}s,"
                f"tokens={evidence.get('usage', {}).get('total_tokens')})"
            )
        else:
            failed = True
            summaries.append(
                f"{name}=failed({str(phase.get('error') or 'unspecified')[:500]})"
            )
    _github_annotation(
        "error" if failed else "notice",
        "Velona endpoint probe",
        "; ".join(summaries)[:3000],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://velona.in/v1")
    parser.add_argument("--main-model", default="z-ai/glm-5.3-flash")
    parser.add_argument("--aux-model", default=os.getenv("AUX_LLM_MODEL", ""))
    parser.add_argument("--api-key-env", default="CUSTOM_API_KEY")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        print(f"{args.api_key_env} is not configured", file=sys.stderr)
        return 2
    if not args.aux_model.strip():
        print("--aux-model (or AUX_LLM_MODEL) is required", file=sys.stderr)
        return 2
    probe = VelonaModelProbe(
        base_url=args.base_url,
        api_key=api_key,
        main_model=args.main_model,
        aux_model=args.aux_model,
        timeout=args.timeout,
    )
    receipt = probe.run()
    if args.output:
        _atomic_json(args.output, receipt)
    _publish_phase_annotations(receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
