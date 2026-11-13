"""B-LIVE-001: natural-language callables must reach the contract.

The engineering contract used to recognise a symbol only when the name followed
the literal token ``def``/``function``. "Implement a divide(a, b) function"
therefore produced an empty symbol list and the plan gate rejected the request
before provider dispatch. These tests pin the natural forms AND the boundaries
that must not move: negation/preservation clauses, genuine ambiguity, unrelated
identifiers, and the historical LIVE7 prompt.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.orchestration.contract import extract_contract, parse_prompt_contract

REPO = Path(__file__).resolve().parents[2]
LIVE7_EVIDENCE = REPO / "diagnostics" / "p0_6_7" / "live7" / "evidence.json"

# The exact prompt that failed in the real-provider qualification run.
LIVE_DIVIDE_PROMPT = (
    "Implement a divide(a, b) function in the existing mini_math package. "
    "Division by zero must raise ZeroDivisionError. Export the function from the "
    "package, add appropriate tests covering positive values, negative values, "
    "floating-point values and division by zero, update README documentation, and "
    "run the complete test suite. Preserve the existing functions."
)


def _req(rid: str, description: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=rid,
        title=rid,
        description=description,
        classification="EXPLICIT",
        status=SimpleNamespace(value="ACCEPTED"),
        affected_files=[],
        acceptance_criteria=["Works"],
    )


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "src" / "mini_math").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "mini_math" / "ops.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# mini_math\n", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# extraction forms
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("prompt", "expected", "signature"),
    [
        ("Implement a divide(a, b) function.", ["divide"], ["a", "b"]),
        ("Create divide(a, b) in the existing package.", ["divide"], ["a", "b"]),
        ("Add a function called divide.", ["divide"], []),
        ("Add a Python function named clamp.", ["clamp"], []),
        ("Implement the public method `divide`.", ["divide"], []),
        ("Implement a public function divide(value).", ["divide"], ["value"]),
        ("Define function clamp(value, minimum, maximum).", ["clamp"], ["value", "minimum", "maximum"]),
    ],
)
def test_natural_language_forms_extract_the_named_callable(
    prompt: str, expected: list[str], signature: list[str],
) -> None:
    fields = parse_prompt_contract(prompt)
    assert fields["symbols"] == expected
    assert fields["signatures"][expected[0]] == signature


def test_name_before_argument_list_is_extracted() -> None:
    fields = parse_prompt_contract("Implement a divide(a, b) function.")
    assert fields["symbols"] == ["divide"]
    assert fields["signatures"]["divide"] == ["a", "b"]


def test_multiple_requested_symbols_keep_their_signatures() -> None:
    fields = parse_prompt_contract(
        "Add functions divide(a, b) and clamp(value, minimum, maximum)."
    )
    assert fields["symbols"] == ["divide", "clamp"]
    assert fields["signatures"] == {
        "divide": ["a", "b"],
        "clamp": ["value", "minimum", "maximum"],
    }


# --------------------------------------------------------------------------- #
# boundaries that must not move
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "prompt",
    [
        "Keep the existing divide implementation intact.",
        "Preserve the existing functions.",
        "Do not add a function called remove.",
        "Do not modify add() or subtract().",
        "Run pytest -q and python -m pytest, then implement divide(a, b).",
    ],
)
def test_preservation_and_negation_clauses_are_not_requests(prompt: str) -> None:
    fields = parse_prompt_contract(prompt)
    if "implement divide" in prompt:
        # The trailing creation clause is still a request; the preserved
        # existing names are not.
        assert fields["symbols"] == ["divide"]
        return
    assert fields["symbols"] == []


def test_unrelated_identifiers_are_not_symbols() -> None:
    fields = parse_prompt_contract(
        "Update README.md and run `pytest -q`. Supported units: h, m, s. "
        "Return an int and raise ValueError for negative values."
    )
    assert fields["symbols"] == []


def test_no_symbol_for_a_public_api_still_rejects() -> None:
    fields = parse_prompt_contract("Create src/x.py with a public function that returns int.")
    assert fields["symbols"] == []


def test_conflicting_public_symbols_still_reject(workspace: Path) -> None:
    prompt = "Create src/x.py with public function alpha() and public function beta()."
    contract = extract_contract(
        prompt, [_req("REQ-1", prompt)], ["src/x.py"],
        task_id="conflict", workspace=workspace,
    )
    assert any("conflicting" in item.lower() for item in contract.ambiguities)


# --------------------------------------------------------------------------- #
# gate-level: the natural request now passes
# --------------------------------------------------------------------------- #

def test_the_live_divide_prompt_passes_contract_validation(workspace: Path) -> None:
    contract = extract_contract(
        LIVE_DIVIDE_PROMPT,
        [_req("REQ-1", LIVE_DIVIDE_PROMPT)],
        ["src/mini_math/ops.py", "tests/test_ops.py"],
        task_id="live-divide", workspace=workspace,
    )
    assert not any("public symbol" in item.lower() for item in contract.ambiguities), contract.ambiguities
    source = next(c for c in contract.components if c.role == "SOURCE")
    assert source.symbols == ["divide"]
    assert source.signatures["divide"] == ["a", "b"]


def test_natural_multi_file_request_keeps_roles_and_symbols(workspace: Path) -> None:
    prompt = (
        "Implement a divide(a, b) function in src/mini_math/ops.py. "
        "Add tests in tests/test_ops.py and update README.md. "
        "Preserve the existing functions."
    )
    contract = extract_contract(
        prompt, [_req("REQ-1", prompt)],
        ["src/mini_math/ops.py", "tests/test_ops.py", "README.md"],
        task_id="multi-file", workspace=workspace,
    )
    roles = {c.target_file: c.role for c in contract.components}
    assert roles["src/mini_math/ops.py"] == "SOURCE"
    assert roles["tests/test_ops.py"] == "TEST"
    source = next(c for c in contract.components if c.role == "SOURCE")
    assert source.symbols == ["divide"]
    test_component = next(c for c in contract.components if c.role == "TEST")
    assert test_component.symbols == ["divide"]
    assert not any("public symbol" in item.lower() for item in contract.ambiguities)


@pytest.mark.skipif(not LIVE7_EVIDENCE.exists(), reason="LIVE7 evidence fixture is not present")
def test_historical_live7_prompt_is_unchanged() -> None:
    prompt = json.loads(LIVE7_EVIDENCE.read_text(encoding="utf-8"))["prompt"]
    fields = parse_prompt_contract(prompt)
    assert fields["symbols"] == ["parse_duration"]
    assert fields["signatures"]["parse_duration"] == ["value"]
