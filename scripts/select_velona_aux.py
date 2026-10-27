#!/usr/bin/env python3
"""Select the cheapest live Velona model with a >=1M-token context window.

The API key is read from an environment variable, never a CLI argument.  The
receipt contains only provider-published model metadata and prices; it never
contains response bodies, prompts, or credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.telemetry import pricing  # noqa: E402

MINIMUM_CONTEXT_WINDOW = 1_000_000
_SAFE_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
_CONTEXT_FIELDS = (
    "context_window",
    "context_length",
    "max_context_length",
    "max_position_embeddings",
    "max_model_len",
)
_NON_CHAT_ID_MARKERS = (
    "embed",
    "rerank",
    "extract",
    "moderation",
    "guardrail",
    "image",
    "ocr",
    "whisper",
    "speech",
    "transcrib",
    "tts",
)
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class CatalogSelectionError(RuntimeError):
    """The live catalog cannot support an honest auxiliary selection."""


@dataclass(frozen=True)
class Candidate:
    model: str
    context_window: int
    input_per_1m: float
    output_per_1m: float
    equal_volume_per_1m: float
    currency: str


def _model_entries(payload: Any) -> list[dict[str, Any]]:
    """Return model objects from common and Velona-nested catalog shapes."""
    if not isinstance(payload, dict):
        return []
    containers: list[Any] = [payload]
    containers.extend(
        payload.get(key) for key in ("data", "models", "result")
    )
    for container in containers:
        if isinstance(container, list):
            return [item for item in container if isinstance(item, dict)]
        if not isinstance(container, dict):
            continue
        for key in ("models", "data", "result", "items"):
            value = container.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    if payload.get("id"):
        return [payload]
    return []


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _context_window(entry: dict[str, Any]) -> int | None:
    for field in _CONTEXT_FIELDS:
        value = _positive_int(entry.get(field))
        if value is not None:
            return value
    limits = entry.get("limits")
    if isinstance(limits, dict):
        for field in (*_CONTEXT_FIELDS, "max_context_window_tokens"):
            value = _positive_int(limits.get(field))
            if value is not None:
                return value
    return None


def _entry_id(entry: dict[str, Any]) -> str:
    return str(
        entry.get("id")
        or entry.get("model")
        or entry.get("name")
        or entry.get("slug")
        or ""
    ).strip()


def _obviously_non_chat(model: str) -> bool:
    lowered = model.lower()
    return any(marker in lowered for marker in _NON_CHAT_ID_MARKERS)


def select_cheapest_aux(
    payload: Any,
    *,
    main_model: str,
    minimum_context: int = MINIMUM_CONTEXT_WINDOW,
) -> dict[str, Any]:
    """Select by the lowest equal-input/output advertised cost.

    Provider pricing has two dimensions.  To avoid silently inventing an
    application-specific traffic ratio, "cheapest" means the cost of one
    million input plus one million output tokens.  Input price, output price,
    larger context, then model id are deterministic tie-breakers.
    """
    entries = _model_entries(payload)
    if not entries:
        raise CatalogSelectionError("catalog contains no model entries")

    by_id = {
        _entry_id(entry).lower(): entry
        for entry in entries
        if _entry_id(entry)
    }
    main_entry = by_id.get(main_model.strip().lower())
    if main_entry is None:
        raise CatalogSelectionError(
            f"required main model {main_model!r} is absent from the live catalog"
        )

    rates = pricing.parse_catalog(payload)
    rates_lower = {model.lower(): rate for model, rate in rates.items()}
    candidates: list[Candidate] = []
    for entry in entries:
        model = _entry_id(entry)
        if (
            not model
            or not _SAFE_MODEL_ID.fullmatch(model)
            or _obviously_non_chat(model)
        ):
            continue
        window = _context_window(entry)
        if window is None or window < minimum_context:
            continue
        rate = rates_lower.get(model.lower())
        if not isinstance(rate, dict):
            continue
        try:
            input_price = float(rate["input_per_1m"])
            output_price = float(rate["output_per_1m"])
        except (KeyError, TypeError, ValueError):
            continue
        if input_price < 0 or output_price < 0:
            continue
        currency = str(rate.get("currency") or "USD").upper()
        candidates.append(
            Candidate(
                model=model,
                context_window=window,
                input_per_1m=input_price,
                output_per_1m=output_price,
                equal_volume_per_1m=round(input_price + output_price, 6),
                currency=currency,
            )
        )

    if not candidates:
        raise CatalogSelectionError(
            f"catalog has no priced model with context_window >= {minimum_context}"
        )
    currencies = {candidate.currency for candidate in candidates}
    if len(currencies) != 1:
        raise CatalogSelectionError(
            "cannot compare live auxiliary prices across currencies: "
            + ", ".join(sorted(currencies))
        )

    candidates.sort(
        key=lambda candidate: (
            candidate.equal_volume_per_1m,
            candidate.input_per_1m,
            candidate.output_per_1m,
            -candidate.context_window,
            candidate.model,
        )
    )
    selected = candidates[0]
    return {
        "schema": "pulseai.velona_aux_selection.v2",
        "selection_policy": (
            "exclude obvious non-chat utility ids; minimum(input_per_1m + "
            "output_per_1m), then input, output, larger context, model id; "
            "optionally require a live exact-sentinel chat pass"
        ),
        "minimum_context_window": minimum_context,
        "main": {
            "model": main_model,
            "catalog_present": True,
            "context_window": _context_window(main_entry),
        },
        "selected": asdict(selected),
        "eligible_count": len(candidates),
        "eligible": [asdict(candidate) for candidate in candidates[:20]],
    }


def _assistant_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "")


def _probe_chat_candidate(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: float,
) -> dict[str, Any]:
    """Use a tiny exact-sentinel request to prove OpenAI-chat compatibility."""
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/v1"):
        endpoint += "/v1"
    endpoint += "/chat/completions"
    total_started = time.monotonic()
    last_error = "unspecified"
    attempts = 0
    for attempt in range(2):
        attempts += 1
        sentinel = f"AUX_CHAT_READY_{secrets.token_hex(5)}"
        body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": f"Reply with exactly this token: {sentinel}",
                }
            ],
            "max_tokens": 48,
            "temperature": 0,
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": _BROWSER_USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                status = int(response.status)
                payload = json.loads(response.read())
            choices = payload.get("choices") if isinstance(payload, dict) else None
            message = (
                choices[0].get("message")
                if isinstance(choices, list)
                and choices
                and isinstance(choices[0], dict)
                else None
            )
            if status == 200 and sentinel in _assistant_text(message):
                return {
                    "model": model,
                    "status": "passed",
                    "attempts": attempts,
                    "elapsed_seconds": round(time.monotonic() - total_started, 3),
                    "sentinel_preserved": True,
                }
            last_error = "HTTP 200 response did not preserve the exact sentinel"
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code < 500:
                break
        except Exception as exc:  # noqa: BLE001 - bounded classification only
            last_error = type(exc).__name__
        if attempt == 0:
            time.sleep(0.4)
    return {
        "model": model,
        "status": "failed",
        "attempts": attempts,
        "elapsed_seconds": round(time.monotonic() - total_started, 3),
        "error": last_error,
    }


def validate_chat_candidates(
    receipt: dict[str, Any],
    *,
    probe: Callable[[str], dict[str, Any]],
    max_candidates: int,
) -> dict[str, Any]:
    """Pick the first price-ranked candidate that passes a real chat call."""
    candidates = receipt.get("eligible")
    if not isinstance(candidates, list):
        raise CatalogSelectionError("selection receipt has no eligible candidates")
    attempts: list[dict[str, Any]] = []
    for candidate in candidates[: max(1, max_candidates)]:
        if not isinstance(candidate, dict) or not candidate.get("model"):
            continue
        result = probe(str(candidate["model"]))
        attempts.append(result)
        if result.get("status") == "passed":
            validated = dict(receipt)
            validated["selected"] = candidate
            validated["chat_validation"] = {
                "status": "passed",
                "attempted_count": len(attempts),
                "attempts": attempts,
            }
            return validated
    summary = ", ".join(
        f"{row.get('model')}={row.get('error') or row.get('status')}"
        for row in attempts
    )
    raise CatalogSelectionError(
        "no price-ranked 1M candidate passed live chat validation: " + summary[:1200]
    )


def fetch_live_selection(
    *,
    base_url: str,
    api_key: str,
    main_model: str,
    minimum_context: int = MINIMUM_CONTEXT_WINDOW,
    timeout: float = 15.0,
    verify_chat: bool = False,
    max_chat_candidates: int = 20,
    chat_timeout: float = 45.0,
) -> dict[str, Any]:
    """Try provider catalog layouts and return the first honest selection."""
    if not api_key:
        raise CatalogSelectionError("CUSTOM_API_KEY is not configured")
    failures: list[str] = []
    for url in pricing.candidate_urls(base_url):
        payload: Any = None
        for attempt in range(2):
            try:
                payload = pricing._http_get_json(url, api_key, timeout)  # noqa: SLF001
                break
            except Exception as exc:  # noqa: BLE001 - continue to next layout
                safe = f"{type(exc).__name__}: {exc}".replace(api_key, "[REDACTED]")
                if attempt:
                    failures.append(f"{url}: {safe[:300]}")
                else:
                    time.sleep(0.4)
        if payload is None:
            continue
        try:
            receipt = select_cheapest_aux(
                payload,
                main_model=main_model,
                minimum_context=minimum_context,
            )
        except CatalogSelectionError as exc:
            failures.append(f"{url}: {exc}")
            continue
        receipt["source_url"] = url
        if verify_chat:
            receipt = validate_chat_candidates(
                receipt,
                probe=lambda model: _probe_chat_candidate(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    timeout=max(1.0, chat_timeout),
                ),
                max_candidates=max_chat_candidates,
            )
        return receipt
    detail = "; ".join(failures[-4:]) or "no catalog URL answered"
    raise CatalogSelectionError(f"no usable live Velona catalog: {detail}")


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


def _append_github_env(path: Path, receipt: dict[str, Any]) -> None:
    selected = receipt["selected"]
    model = str(selected["model"])
    if not _SAFE_MODEL_ID.fullmatch(model):
        raise CatalogSelectionError("selected model id is unsafe for an env file")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"AUX_LLM_MODEL={model}\n")
        handle.write(f"VELONA_AUX_CONTEXT_WINDOW={int(selected['context_window'])}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://velona.in/v1")
    parser.add_argument("--main-model", default="z-ai/glm-5.3-flash")
    parser.add_argument("--minimum-context", type=int, default=MINIMUM_CONTEXT_WINDOW)
    parser.add_argument("--api-key-env", default="CUSTOM_API_KEY")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--verify-chat",
        action="store_true",
        help="require a tiny exact-sentinel chat pass before selecting a model",
    )
    parser.add_argument("--max-chat-candidates", type=int, default=20)
    parser.add_argument("--chat-timeout", type=float, default=45.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--github-env", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    key = os.environ.get(args.api_key_env, "").strip()
    try:
        receipt = fetch_live_selection(
            base_url=args.base_url,
            api_key=key,
            main_model=args.main_model,
            minimum_context=max(1, args.minimum_context),
            timeout=max(1.0, args.timeout),
            verify_chat=args.verify_chat,
            max_chat_candidates=max(1, args.max_chat_candidates),
            chat_timeout=max(1.0, args.chat_timeout),
        )
        if args.output:
            _atomic_json(args.output, receipt)
        if args.github_env:
            _append_github_env(args.github_env, receipt)
        selected = receipt["selected"]
        _github_annotation(
            "notice",
            "Velona 1M AUX selected",
            (
                f"model={selected['model']}; context={selected['context_window']}; "
                f"input_per_1m={selected['input_per_1m']}; "
                f"output_per_1m={selected['output_per_1m']}; "
                f"equal_volume={selected['equal_volume_per_1m']} "
                f"{selected['currency']}; eligible={receipt['eligible_count']}; "
                f"chat_validated={receipt.get('chat_validation', {}).get('status')}; "
                f"chat_attempts={receipt.get('chat_validation', {}).get('attempted_count')}"
            ),
        )
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI emits one bounded safe reason
        safe = f"{type(exc).__name__}: {exc}".replace(key, "[REDACTED]")
        _github_annotation("error", "Velona 1M AUX selection failed", safe[:1200])
        print(f"Velona auxiliary selection failed: {safe[:1200]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
