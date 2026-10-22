"""Call ledger — Phase 0 metering for the strength plan (founder 2026-10-21).

Every model call the engine makes lands here as ONE append-only JSONL line:
model, provider, token counts, wall time, reasoning volume. At turn end a
second line records the run's verdict (``completed`` / ``unverified`` /
``failed`` / ``budget_exhausted`` / ``cancelled`` — the exact stamps
``finalize_node`` computes). Nothing else. No prompts, no answers, no tool
output, no file contents: the ledger meters COST and OUTCOME; conversation
content already lives in ``~/.crusorai/sessions.db`` and is never copied.

Why this exists, in founder terms:
  * expense: monthly spend cannot be planned from guesses — this is the
    meter. ``python -m src.telemetry.call_ledger`` prints the month's
    calls, tokens, cost (when a rate card is configured), cost per
    completed run and the month-end projection at the current burn rate.
  * learning/training later: joined with sessions by thread id, these
    lines are the labels (verified vs not) every future improvement —
    routing, skills, fine-tuning — trains and evaluates against.

Storage follows the established house layout (feedback_memory's
``~/.crusorai/*.jsonl``): user-level, local-only, plain files.
Directory: ``CRUSORAI_TELEMETRY_DIR`` or ``~/.crusorai/telemetry``,
one file per month (``calls-YYYY-MM.jsonl``). Kill-switch:
``CRUSORAI_TELEMETRY=off`` (also 0/false/no). Every write is best-effort
inside a try — telemetry must never break a model call (house law).

Cost math needs prices; providers differ and change. Rate card, first
match wins: ``CRUSORAI_RATE_CARD`` env JSON, then
``<telemetry dir>/rates.json``. Shape:
``{"<model-substring>": {"input_per_1m": 0.30, "output_per_1m": 1.20,
"currency": "USD"}}`` — matched case-insensitively against the model id.
Without a rate, cost is reported as ``None`` ("tokens only") — never
invented. Reasoning tokens, when a provider bills them separately, ride
inside output tokens on every adapter we use; ``reasoning_chars`` is
kept as a volume signal only, never double-counted into cost.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

_LOCK = threading.Lock()
_OFF_VALUES = {"off", "0", "false", "no"}


def telemetry_enabled() -> bool:
    return os.environ.get("CRUSORAI_TELEMETRY", "on").strip().lower() not in _OFF_VALUES


def telemetry_dir() -> str:
    override = os.environ.get("CRUSORAI_TELEMETRY_DIR", "").strip()
    if override:
        return os.path.expanduser(override)
    return os.path.join(os.path.expanduser("~"), ".crusorai", "telemetry")


def _month_stamp(when: datetime | None = None) -> str:
    return (when or datetime.now()).strftime("%Y-%m")


def ledger_path(month: str | None = None, directory: str | None = None) -> str:
    return os.path.join(directory or telemetry_dir(), f"calls-{month or _month_stamp()}.jsonl")


def _append(record: dict, directory: str | None = None) -> None:
    """One JSONL line, thread-safe, never raises."""
    try:
        path = ledger_path(directory=directory)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with _LOCK:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:
        pass  # metering must never break the work it meters


def record_call(
    thread_id: str,
    provider: str,
    model: str,
    wall_s: float,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    reasoning_chars: int = 0,
    streamed: bool = False,
    error: str = "",
    provider_cost: float | None = None,
    directory: str | None = None,
) -> None:
    """Meter one billed model call. Token counts may be None (provider
    reported none) — recorded as null, never estimated silently. When the
    provider itself reported the call's cost in its usage payload, that
    number is stamped on the line (cost_source=provider) and wins over
    every rate card: the provider's own bill is the ground truth."""
    if not telemetry_enabled():
        return
    record = {
        "kind": "call",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "thread": str(thread_id or "default"),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "reasoning_chars": int(reasoning_chars or 0),
        "wall_s": round(float(wall_s or 0.0), 3),
        "streamed": bool(streamed),
        "error": str(error or "")[:80],
    }
    if provider_cost is not None:
        record["cost"] = round(float(provider_cost), 6)
        record["cost_source"] = "provider"
    _append(record, directory=directory)
    try:
        from src.telemetry import pricing

        pricing.ensure_pricing_async(directory=directory)
    except Exception:
        pass  # pricing refresh is opportunistic; the call path never waits


def record_run(
    thread_id: str,
    verdict: str,
    *,
    wall_s: float | None = None,
    directory: str | None = None,
) -> None:
    """Meter one finished turn: the finalize_node verdict stamp."""
    if not telemetry_enabled():
        return
    record: dict = {
        "kind": "run",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "thread": str(thread_id or "default"),
        "verdict": str(verdict or ""),
    }
    if wall_s is not None:
        record["wall_s"] = round(float(wall_s), 3)
    _append(record, directory=directory)


# --------------------------------------------------------------------------
# Reading + monthly summary
# --------------------------------------------------------------------------

def load_records(month: str | None = None, directory: str | None = None) -> list[dict]:
    path = ledger_path(month=month, directory=directory)
    records: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # cross-process interleave debris: skip, keep the rest
                if isinstance(record, dict):
                    records.append(record)
    except OSError:
        return []
    return records


def load_rate_card(directory: str | None = None) -> dict:
    """Merged price book, manual over dynamic: CRUSORAI_RATE_CARD env /
    rates.json entries win; underneath, the provider catalog fetched by
    src.telemetry.pricing (pricing-cache.json) prices ANY model id the
    provider publishes. {} when nothing is known anywhere."""
    merged: dict = {}
    try:
        from src.telemetry import pricing

        if pricing.pricing_enabled():
            merged.update(pricing.load_cached_rates(directory=directory))
    except Exception:
        pass
    manual = _load_manual_card(directory=directory)
    merged.update(manual)
    return merged


def _load_manual_card(directory: str | None = None) -> dict:
    """Env JSON first, then <telemetry dir>/rates.json. {} when unset/bad."""
    raw = os.environ.get("CRUSORAI_RATE_CARD", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    try:
        with open(os.path.join(directory or telemetry_dir(), "rates.json"), "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
            if isinstance(parsed, dict):
                return parsed
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _rate_for(model: str, card: dict) -> dict | None:
    valid = {k: v for k, v in card.items() if isinstance(v, dict)}
    if not valid:
        return None
    try:
        from src.telemetry import pricing

        return pricing.resolve_rate(model, valid)
    except Exception:
        lowered = (model or "").lower()
        for key, rate in valid.items():
            if str(key).lower() in lowered:
                return rate
        return None


def record_currency(record: dict) -> str:
    """Currency stamped beside a provider-reported cost, when present."""
    value = record.get("currency")
    return str(value) if isinstance(value, str) and value else ""



def _resolve(model: str, card: dict, manual: dict | None) -> dict | None:
    """Manual card resolves FIRST (the founder's explicit price always
    wins), then the merged book (manual keys over the dynamic catalog)."""
    if manual:
        rate = _rate_for(model, manual)
        if rate is not None:
            return rate
    return _rate_for(model, card)


def _call_cost(record: dict, card: dict, manual: dict | None = None) -> float | None:
    reported = record.get("cost")
    if isinstance(reported, (int, float)) and not isinstance(reported, bool):
        return float(reported)  # the provider's own bill for this call
    rate = _resolve(str(record.get("model") or ""), card, manual)
    if rate is None:
        return None
    try:
        input_per_1m = float(rate.get("input_per_1m"))
        output_per_1m = float(rate.get("output_per_1m"))
    except (TypeError, ValueError):
        return None
    input_tokens = record.get("input_tokens") or 0
    output_tokens = record.get("output_tokens") or 0
    return (input_tokens / 1_000_000 * input_per_1m) + (output_tokens / 1_000_000 * output_per_1m)


def summarize(month: str | None = None, directory: str | None = None, now: datetime | None = None) -> dict:
    """Aggregate one month of ledger lines into the expense picture."""
    month = month or _month_stamp(now)
    records = load_records(month=month, directory=directory)
    card = load_rate_card(directory=directory)
    manual = _load_manual_card(directory=directory)
    calls = [r for r in records if r.get("kind") == "call"]
    runs = [r for r in records if r.get("kind") == "run"]
    ok_calls = [c for c in calls if not c.get("error")]

    def _sum(rows: list[dict], key: str) -> int:
        return sum(int(r.get(key) or 0) for r in rows)

    by_model: dict[str, dict] = {}
    cost_total = 0.0
    cost_known_calls = 0
    currency = ""
    for call in ok_calls:
        model = str(call.get("model") or "unknown")
        bucket = by_model.setdefault(
            model, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "wall_s": 0.0, "cost": None}
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += int(call.get("input_tokens") or 0)
        bucket["output_tokens"] += int(call.get("output_tokens") or 0)
        bucket["wall_s"] = round(bucket["wall_s"] + float(call.get("wall_s") or 0.0), 1)
        cost = _call_cost(call, card, manual)
        if cost is not None:
            cost_known_calls += 1
            cost_total += cost
            bucket["cost"] = (bucket["cost"] or 0.0) + cost
            rate = _resolve(model, card, manual) or {}
            currency = str(record_currency(call) or rate.get("currency") or currency or "USD")

    verdicts: dict[str, int] = {}
    for run in runs:
        verdict = str(run.get("verdict") or "unknown")
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
    completed = verdicts.get("completed", 0)

    # Burn projection: month-to-date cost spread over elapsed days,
    # extrapolated across the whole month. Honest only with a rate card;
    # otherwise falls back to a token projection (same shape).
    moment = now or datetime.now()
    days_elapsed = max(1, moment.day) if _month_stamp(moment) == month else None
    days_in_month = _days_in_month(month)
    projection_cost = None
    projection_tokens = None
    total_tokens = _sum(ok_calls, "input_tokens") + _sum(ok_calls, "output_tokens")
    if days_elapsed and days_in_month:
        if cost_known_calls:
            projection_cost = round(cost_total / days_elapsed * days_in_month, 2)
        projection_tokens = int(total_tokens / days_elapsed * days_in_month)

    return {
        "month": month,
        "calls": len(ok_calls),
        "failed_calls": len(calls) - len(ok_calls),
        "runs": len(runs),
        "input_tokens": _sum(ok_calls, "input_tokens"),
        "output_tokens": _sum(ok_calls, "output_tokens"),
        "total_tokens": total_tokens,
        "unknown_token_calls": sum(1 for c in ok_calls if c.get("input_tokens") is None),
        "cost": round(cost_total, 10) if cost_known_calls else None,
        "currency": currency if cost_known_calls else "",
        "cost_per_completed_run": (
            round(cost_total / completed, 10) if cost_known_calls and completed else None
        ),
        "projected_month_cost": projection_cost,
        "projected_month_tokens": projection_tokens,
        "by_model": by_model,
        "verdicts": verdicts,
    }


def _days_in_month(month: str) -> int | None:
    try:
        year, mon = (int(part) for part in month.split("-"))
        if mon == 12:
            following = datetime(year + 1, 1, 1)
        else:
            following = datetime(year, mon + 1, 1)
        return (following - datetime(year, mon, 1)).days
    except (ValueError, TypeError):
        return None


def format_summary(summary: dict) -> str:
    """Human-readable monthly expense report (console/terminal)."""
    cost = summary["cost"]
    currency = summary["currency"] or "USD"
    lines = [
        f"CrusorAI usage — {summary['month']}",
        f"  model calls: {summary['calls']} ok, {summary['failed_calls']} failed; "
        f"turns finished: {summary['runs']} {summary['verdicts'] or ''}",
        f"  tokens: {summary['input_tokens']:,} in / {summary['output_tokens']:,} out "
        f"({summary['total_tokens']:,} total"
        + (f"; {summary['unknown_token_calls']} calls reported no usage" if summary["unknown_token_calls"] else "")
        + ")",
    ]
    if cost is None:
        lines.append(
            "  cost: unknown — no pricing source yet. Run "
            "`python -m src.telemetry.call_ledger --refresh-pricing` to pull your "
            "provider's catalog, or set CRUSORAI_RATE_CARD / rates.json manually."
        )
    else:
        lines.append(f"  cost so far: {currency} {cost:,.10f}".rstrip("0").rstrip("."))
        if summary["cost_per_completed_run"] is not None:
            lines.append(
                f"  cost per completed turn: {currency} {summary['cost_per_completed_run']:,.10f}".rstrip("0").rstrip(".")
            )
        if summary["projected_month_cost"] is not None:
            lines.append(
                f"  projected month-end at current burn: {currency} {summary['projected_month_cost']:,.2f}"
            )
    if summary["projected_month_tokens"]:
        lines.append(f"  projected month-end tokens: {summary['projected_month_tokens']:,}")
    for model, bucket in sorted(summary["by_model"].items()):
        model_cost = bucket["cost"]
        cost_part = f", {currency} {model_cost:,.10f}".rstrip("0").rstrip(".") if model_cost is not None else ""
        lines.append(
            f"  - {model}: {bucket['calls']} calls, {bucket['input_tokens'] + bucket['output_tokens']:,} tokens"
            f"{cost_part}, {bucket['wall_s']:.0f}s model time"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="call_ledger", description="CrusorAI monthly usage/expense summary")
    parser.add_argument("--month", default=None, help="YYYY-MM (default: current month)")
    parser.add_argument("--dir", default=None, help="telemetry directory override")
    parser.add_argument("--json", action="store_true", help="print the raw summary dict as JSON")
    parser.add_argument("--refresh-pricing", action="store_true",
                        help="fetch the provider's priced model catalog now (no manual rates needed)")
    parser.add_argument("--model", default=None,
                        help="print the resolved rate for ANY model id, or 'unknown'")
    args = parser.parse_args(argv)
    if args.refresh_pricing:
        from src.telemetry import pricing

        try:
            rates, source = pricing.refresh(directory=args.dir)
        except Exception as exc:
            print(f"pricing refresh failed: {exc}")
            return 1
        if not rates:
            print(f"{source} answered but carried no parseable pricing — "
                  "cost stays unknown until a rates.json override is added.")
            return 1
        print(f"priced {len(rates)} model(s) from {source} — cached for 24h.")
        return 0
    if args.model:
        card = load_rate_card(directory=args.dir)
        rate = _rate_for(args.model, card)
        if rate is None:
            print(f"{args.model}: unknown — no rate in the manual card or the provider catalog "
                  f"(try --refresh-pricing).")
            return 1
        print(f"{args.model}: input {rate.get('input_per_1m')}/1M, output {rate.get('output_per_1m')}/1M "
              f"({rate.get('currency') or 'USD'}, source: {rate.get('source') or 'manual'})")
        return 0
    summary = summarize(month=args.month, directory=args.dir)
    print(json.dumps(summary, indent=2) if args.json else format_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
