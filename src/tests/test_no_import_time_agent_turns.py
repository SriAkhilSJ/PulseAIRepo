"""No test module may reach the agent (or the provider) while it is being imported.

``pytest`` executes module scope during *collection*, before any test is
selected, before ``-k``/``-m`` filters apply, and before a timeout guard
counts.  A module-level ``invoke_agent(...)`` therefore bills the configured
provider on every run and can stall a suite for minutes on a machine that has
a working ``.env`` — the failure mode that cost a Windows verification round
its full-suite baseline and made a healthy interpreter look hung.

This is a cheap structural pin: module-level *statements that call into the
agent* are forbidden.  Imports, constants, ``print`` and fixtures stay legal.

Recipe for converting one (``test_agent_status_checkpoint.py`` is the worked
example): move the ``from src...`` imports into the test body, wrap the script
in a ``def test_...``, write into ``tmp_path`` instead of ``generated/``, give
the thread a unique id so a previous run's checkpoint cannot vouch for this
one, and gate it with

    pytestmark = pytest.mark.skipif(
        os.environ.get("PULSEAI_ALLOW_LIVE_AGENT_TEST") != "1",
        reason="performs a real, billed provider turn",
    )
"""

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

#: Billed `invoke_agent`/`stream_agent` turns at module scope in KNOWN_IMPORT_TIME_TURNS.
KNOWN_IMPORT_TIME_TURN_COUNT = 11
#: ... plus provider-free calls the pin also flags (a module-level `get_agent_status`).
KNOWN_IMPORT_TIME_STATEMENT_COUNT = 12

#: Calls that reach a provider: these bill money when pytest merely collects.
BILLED_CALLEES = {"invoke_agent", "stream_agent", "ainvoke", "abatch"}

FORBIDDEN_CALLEES = BILLED_CALLEES | {
    "invoke_agent",
    "stream_agent",
    "ainvoke",
    "abatch",
    "build_graph",
    "get_agent_status",
}


def _called_name(node):
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _module_level_value(node):
    """The expression a module-level statement would evaluate, if it is one."""
    if isinstance(node, ast.Expr):
        return node.value
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return node.value
    return None


def _billed_turns_in(tree):
    return [
        node.lineno
        for node in tree.body
        if isinstance(_module_level_value(node), ast.Call)
        and _called_name(_module_level_value(node)) in BILLED_CALLEES
    ]


def _offenders_in(tree):
    found = []
    for node in tree.body:  # module level only; function bodies are fine
        value = _module_level_value(node)
        if isinstance(value, ast.Call) and _called_name(value) in FORBIDDEN_CALLEES:
            found.append(node.lineno)
    return found


#: Pre-existing debt, recorded so the pin can fail on *new* offenders without
#: rewriting six owner-authored files mid-verification.  Every entry below runs a
#: real, billed agent turn at collection time and writes into ``generated/``; on a
#: host without the checkpointer extra it errors during collection instead.
#: Delete an entry when you convert its file (see the recipe in this module's
#: docstring and the worked example in ``test_agent_status_checkpoint.py``).
#: Measured by AST, not by eye: 11 billed turns + 1 read-only checkpoint call.
KNOWN_IMPORT_TIME_TURNS = {
    "test_keep_recovery.py",
    "test_plan_approval.py",
    "test_plan_cancel.py",
    "test_plan_mode.py",
    "test_plan_revision.py",
    "test_replan_recovery.py",
}


def test_no_test_module_calls_the_agent_at_import_time():
    offenders = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # a file that will not parse needs no pin
            raise AssertionError(f"{path.name} does not parse: {exc}") from exc
        for lineno in _offenders_in(tree):
            if path.name in KNOWN_IMPORT_TIME_TURNS:
                continue
            offenders.append(f"{path.name}:{lineno}")
    assert not offenders, (
        "a test module executes the agent while pytest collects, which bills the "
        "configured provider before anything is selected (no -k/-m filter has run "
        "yet) and can stall the suite for minutes; move it into a test function "
        "and gate provider-touching ones behind PULSEAI_ALLOW_LIVE_AGENT_TEST: "
        + ", ".join(offenders)
    )


def test_known_import_time_turns_do_not_grow():
    """The debt list is exact: it may shrink as files are converted, never grow."""
    found = {}
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        lines = _offenders_in(tree)
        if lines:
            found[path.name] = lines
    assert set(found) == KNOWN_IMPORT_TIME_TURNS, (
        "import-time agent turns changed shape: "
        f"still there = {sorted(set(found))}, "
        f"newly clean = {sorted(KNOWN_IMPORT_TIME_TURNS - set(found))}. "
        "If you converted one, delete it from KNOWN_IMPORT_TIME_TURNS; if you "
        "added one, move it into a gated test function instead."
    )
    total = sum(len(v) for v in found.values())
    assert total <= KNOWN_IMPORT_TIME_STATEMENT_COUNT, (
        f"import-time agent statements grew from {KNOWN_IMPORT_TIME_STATEMENT_COUNT} to {total}"
    )
    billed = sum(
        len(_billed_turns_in(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))))
        for path in (TESTS_DIR / name for name in found)
    )
    assert billed <= KNOWN_IMPORT_TIME_TURN_COUNT, (
        f"import-time *billed* agent turns grew from {KNOWN_IMPORT_TIME_TURN_COUNT} to {billed}: "
        "each one runs against the configured provider during collection, before "
        "-k/-m filters apply. Gate it behind PULSEAI_ALLOW_LIVE_AGENT_TEST."
    )
