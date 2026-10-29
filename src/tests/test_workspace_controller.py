"""Unit tests for Workspace Revision and Invalidation Ledger (Decision B)."""
from __future__ import annotations

import pytest
from src.runtime.workspace_controller import WorkspaceController


def test_monotonic_revision_increment():
    controller = WorkspaceController(initial_revision=0)
    assert controller.revision == 0

    rev1 = controller.record_mutation("src/server.py", "write_file")
    assert rev1 == 1
    assert controller.revision == 1

    rev2 = controller.record_mutation("src/server.py", "edit_file")
    assert rev2 == 2
    assert controller.revision == 2
    assert len(controller.mutation_ledger) == 2


def test_verification_and_stale_invalidation():
    controller = WorkspaceController()

    # Step 1: Write code (Rev 1)
    controller.record_mutation("backend/server.py", "write_file")
    assert controller.revision == 1

    # Step 2: Run tests and pass (Receipt at Rev 1)
    controller.record_verification("backend-tests", passed=True, kind="unit_tests")
    assert controller.is_receipt_stale("backend-tests") is False
    assert controller.get_effective_verification_status() == "verified"

    # Step 3: Edit code file (Rev 2) -> Previous receipt becomes STALE
    controller.record_mutation("backend/server.py", "edit_file")
    assert controller.revision == 2
    assert controller.is_receipt_stale("backend-tests") is True
    assert controller.get_effective_verification_status() == "stale"

    # Step 4: Re-run tests at Rev 2 -> Verification is restored!
    controller.record_verification("backend-tests", passed=True, kind="unit_tests")
    assert controller.is_receipt_stale("backend-tests") is False
    assert controller.get_effective_verification_status() == "verified"


def test_documentation_only_exemption():
    controller = WorkspaceController()

    # Step 1: Write code & pass tests at Rev 1
    controller.record_mutation("app.py", "write_file")
    controller.record_verification("test-suite", passed=True)
    assert controller.get_effective_verification_status() == "verified"

    # Step 2: Edit documentation file (README.md at Rev 2)
    controller.record_mutation("README.md", "edit_file")
    assert controller.revision == 2

    # Step 3: Doc-only mutation does NOT invalidate code verification!
    assert controller.is_receipt_stale("test-suite") is False
    assert controller.get_effective_verification_status() == "verified"
