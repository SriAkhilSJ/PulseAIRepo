"""
Phase 9.3.1.3.1: Financial Provenance & Request Ledger Automated Reconciliation Tests.

Verifies:
1. Raw JSON ledger integrity (live_economics_ledger_phase931.json).
2. JSON and CSV request counts match (exactly 24).
3. Token totals match (28,260 prompt, 5,392 completion, 9,216 cached, 33,652 total).
4. Cost totals match across Rate Cards A, B, and C.
5. Latency totals match (74,683 ms total, 3,111.79 ms mean).
6. Unknown cache-write values remain explicitly UNKNOWN_NOT_REPORTED (not silently converted to 0).
7. Rate-card classifications remain strictly distinct.
8. Task completion economics (6 attempted, 1 successful, 16.67% completion rate).
"""

import json
import csv
import os
import statistics
from decimal import Decimal
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW_LEDGER_PATH = os.path.join(REPO_ROOT, "live_economics_ledger_phase931.json")
AUTH_JSON_PATH = os.path.join(REPO_ROOT, "authoritative_live_economics_ledger_phase931.json")
AUTH_CSV_PATH = os.path.join(REPO_ROOT, "authoritative_live_economics_ledger_phase931.csv")

FX_EFFECTIVE = Decimal("92.4801")


def test_raw_ledger_structure_and_turn_count():
    assert os.path.exists(RAW_LEDGER_PATH), f"Missing {RAW_LEDGER_PATH}"
    with open(RAW_LEDGER_PATH, "r", encoding="utf-8") as f:
        sessions = json.load(f)

    assert len(sessions) == 6, f"Expected 6 sessions, got {len(sessions)}"

    total_turns = 0
    for s_idx, session in enumerate(sessions):
        assert "session_id" in session
        assert "task_id" in session
        assert "turn_telemetry" in session
        turns = session["turn_telemetry"]
        if "task-1" in session["task_id"]:
            assert len(turns) == 2, f"Session {s_idx} expected 2 turns, got {len(turns)}"
        else:
            assert len(turns) == 6, f"Session {s_idx} expected 6 turns, got {len(turns)}"
        total_turns += len(turns)

    assert total_turns == 24, f"Expected exactly 24 turns, got {total_turns}"


def test_raw_ledger_exact_token_aggregation():
    with open(RAW_LEDGER_PATH, "r", encoding="utf-8") as f:
        sessions = json.load(f)

    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    total_tokens = 0

    for s in sessions:
        for t in s["turn_telemetry"]:
            p = t.get("prompt_tokens", 0)
            c = t.get("completion_tokens", 0)
            ca = t.get("cached_tokens", 0) or 0
            tot = t.get("total_tokens", 0)

            prompt_tokens += p
            completion_tokens += c
            cached_tokens += ca
            total_tokens += tot

            req_id = t.get("provider_request_id", "")
            assert req_id.startswith("chatcmpl-"), f"Unexpected provider request ID format: {req_id}"

    assert prompt_tokens == 28260, f"Expected 28,260 prompt tokens, got {prompt_tokens}"
    assert completion_tokens == 5392, f"Expected 5,392 completion tokens, got {completion_tokens}"
    assert cached_tokens == 9216, f"Expected 9,216 cached tokens, got {cached_tokens}"
    assert total_tokens == 33652, f"Expected 33,652 total tokens, got {total_tokens}"
    assert prompt_tokens + completion_tokens == total_tokens


def test_json_and_csv_request_counts_match():
    assert os.path.exists(AUTH_JSON_PATH)
    assert os.path.exists(AUTH_CSV_PATH)

    with open(AUTH_JSON_PATH, "r", encoding="utf-8") as f:
        json_records = json.load(f)

    with open(AUTH_CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        csv_records = list(reader)

    assert len(json_records) == 24, f"Expected 24 JSON records, got {len(json_records)}"
    assert len(csv_records) == 24, f"Expected 24 CSV records, got {len(csv_records)}"


def test_token_totals_match():
    with open(AUTH_JSON_PATH, "r", encoding="utf-8") as f:
        json_records = json.load(f)

    with open(AUTH_CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        csv_records = list(reader)

    j_prompt = sum(r["prompt_tokens"] for r in json_records)
    c_prompt = sum(int(r["prompt_tokens"]) for r in csv_records)
    assert j_prompt == c_prompt == 28260

    j_comp = sum(r["completion_tokens"] for r in json_records)
    c_comp = sum(int(r["completion_tokens"]) for r in csv_records)
    assert j_comp == c_comp == 5392

    j_cached = sum(r["cached_tokens"] for r in json_records)
    c_cached = sum(int(r["cached_tokens"]) for r in csv_records)
    assert j_cached == c_cached == 9216

    j_uncached = sum(r["uncached_prompt_tokens"] for r in json_records)
    c_uncached = sum(int(r["uncached_prompt_tokens"]) for r in csv_records)
    assert j_uncached == c_uncached == 19044

    j_total = sum(r["total_tokens"] for r in json_records)
    c_total = sum(int(r["total_tokens"]) for r in csv_records)
    assert j_total == c_total == 33652


def test_cost_totals_match():
    with open(AUTH_JSON_PATH, "r", encoding="utf-8") as f:
        json_records = json.load(f)

    with open(AUTH_CSV_PATH, "r", encoding="utf-8") as f:
        csv_records = list(csv.DictReader(f))

    # Rate Card A
    j_rca_usd = sum(Decimal(str(r["cost_rate_card_a_usd"])) for r in json_records)
    c_rca_usd = sum(Decimal(str(r["cost_rate_card_a_usd"])) for r in csv_records)
    assert round(j_rca_usd, 8) == round(c_rca_usd, 8) == Decimal("0.00693500")

    j_rca_inr = sum(Decimal(str(r["cost_rate_card_a_inr"])) for r in json_records)
    c_rca_inr = sum(Decimal(str(r["cost_rate_card_a_inr"])) for r in csv_records)
    assert round(j_rca_inr, 4) == round(c_rca_inr, 4) == Decimal("0.6413")

    # Rate Card B
    j_rcb_usd = sum(Decimal(str(r["cost_rate_card_b_usd"])) for r in json_records)
    c_rcb_usd = sum(Decimal(str(r["cost_rate_card_b_usd"])) for r in csv_records)
    assert round(j_rcb_usd, 8) == round(c_rcb_usd, 8) == Decimal("0.00687758")

    j_rcb_inr = sum(Decimal(str(r["cost_rate_card_b_inr"])) for r in json_records)
    c_rcb_inr = sum(Decimal(str(r["cost_rate_card_b_inr"])) for r in csv_records)
    assert round(j_rcb_inr, 4) == round(c_rcb_inr, 4) == Decimal("0.6360")

    # Rate Card C
    j_rcc_usd = sum(Decimal(str(r["cost_rate_card_c_usd"])) for r in json_records)
    c_rcc_usd = sum(Decimal(str(r["cost_rate_card_c_usd"])) for r in csv_records)
    assert round(j_rcc_usd, 8) == round(c_rcc_usd, 8) == Decimal("0.00443397")

    j_rcc_inr = sum(Decimal(str(r["cost_rate_card_c_inr"])) for r in json_records)
    c_rcc_inr = sum(Decimal(str(r["cost_rate_card_c_inr"])) for r in csv_records)
    assert round(j_rcc_inr, 4) == round(c_rcc_inr, 4) == Decimal("0.4101")


def test_latency_totals_match():
    with open(AUTH_JSON_PATH, "r", encoding="utf-8") as f:
        json_records = json.load(f)

    with open(AUTH_CSV_PATH, "r", encoding="utf-8") as f:
        csv_records = list(csv.DictReader(f))

    j_lats = [r["latency_ms"] for r in json_records]
    c_lats = [int(r["latency_ms"]) for r in csv_records]

    assert sum(j_lats) == sum(c_lats) == 74683
    assert abs(statistics.mean(j_lats) - 3111.791666) < 0.01
    assert abs(statistics.mean(c_lats) - 3111.791666) < 0.01
    assert statistics.median(j_lats) == statistics.median(c_lats) == 1570.0
    assert min(j_lats) == min(c_lats) == 1080
    assert max(j_lats) == max(c_lats) == 9120


def test_unknown_cache_write_values_remain_unknown():
    with open(AUTH_JSON_PATH, "r", encoding="utf-8") as f:
        json_records = json.load(f)

    with open(AUTH_CSV_PATH, "r", encoding="utf-8") as f:
        csv_records = list(csv.DictReader(f))

    for r in json_records:
        assert r["cache_write_tokens"] is None, "Cache write tokens must be null/None in JSON"
        assert r["cache_write_status"] == "UNKNOWN_NOT_REPORTED"

    for r in csv_records:
        assert r["cache_write_tokens"] == "", "Cache write tokens must be empty string in CSV"
        assert r["cache_write_status"] == "UNKNOWN_NOT_REPORTED"


def test_rate_card_classifications_remain_distinct():
    with open(AUTH_JSON_PATH, "r", encoding="utf-8") as f:
        json_records = json.load(f)

    for r in json_records:
        rca_desc = r["rate_card_a_classification"]
        rcb_desc = r["rate_card_b_classification"]
        rcc_desc = r["rate_card_c_classification"]

        assert "Conservative Baseline" in rca_desc
        assert "Velona Provider Catalog" in rcb_desc
        assert "Illustrative Only" in rcc_desc
        assert len({rca_desc, rcb_desc, rcc_desc}) == 3


def test_task_completion_economics():
    with open(RAW_LEDGER_PATH, "r", encoding="utf-8") as f:
        sessions = json.load(f)

    total_attempts = len(sessions)
    assert total_attempts == 6

    successful_sessions = [s for s in sessions if s.get("verification_passed") is True]
    assert len(successful_sessions) == 1
    assert successful_sessions[0]["session_id"] == "live-trial-1-task-1-code--2531b0"

    success_rate = len(successful_sessions) / total_attempts
    assert abs(success_rate - 0.166666) < 0.001

    # Direct cost of successful session
    success_cost_usd = Decimal(str(successful_sessions[0]["total_task_usd"]))
    success_cost_inr = Decimal(str(successful_sessions[0]["total_task_inr"]))
    assert round(success_cost_usd, 8) == Decimal("0.00079005")
    assert round(success_cost_inr, 6) == Decimal("0.073064")

    # Amortized cost per successful completion (all spend divided by 1)
    tot_usd = sum(Decimal(str(s["total_task_usd"])) for s in sessions)
    tot_inr = sum(Decimal(str(s["total_task_inr"])) for s in sessions)
    assert round(tot_usd, 8) == Decimal("0.00693500")
    assert round(tot_inr, 6) == Decimal("0.641349")
