"""
scripts/update_and_verify_finance_spec.py - Updates specification with approved user decisions and verifies read-back.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.intelligence.requirement_models import (
    ProjectSpecification,
    RequirementCategory,
    RequirementClassification,
    RequirementItem,
    RequirementPriority,
    RequirementStatus,
    UserPersonaRole,
    UserWorkflow,
)


def main() -> int:
    req_dir = REPO_ROOT / ".crusorai" / "requirements"
    req_dir.mkdir(parents=True, exist_ok=True)
    spec_path = req_dir / "personal_finance_app_spec.json"

    spec = ProjectSpecification(
        spec_id="SPEC-FINANCE-2026-001",
        version=2,
        project_name="Personal Finance Management Application",
        workspace_root=str(REPO_ROOT),
        problem_statement="Users need an intuitive, local-first personal finance application to record income, categorize expenditures, manage monthly category budgets, analyze spending trends, and visualize financial health on an interactive dashboard.",
        desired_outcome="A self-contained modular monolith personal finance application featuring FastAPI backend, React TypeScript frontend, SQLite persistence, and comprehensive financial telemetry with zero cloud lock-in.",
        user_personas=[
            UserPersonaRole(
                role_name="Primary Account Holder",
                description="Single local-first user managing personal cash flow, living expenses, and monthly budgets.",
                permissions=["manage_transactions", "manage_budgets", "view_dashboard", "export_csv"],
            )
        ],
        functional_requirements=[
            RequirementItem(
                id="REQ-FUNC-001",
                category=RequirementCategory.FUNCTIONAL,
                priority=RequirementPriority.CRITICAL,
                description="Income and Expense Management: Create, view, edit, and delete transactions with date, amount, category, payment mode, and notes.",
                acceptance_criteria=[
                    "Create income and expense with amount > 0 and currency INR (₹)",
                    "Edit updates transaction details and recalculates totals immediately",
                    "Delete removes transaction and restores budget/balance",
                    "Categorization with default and custom categories",
                    "Payment mode tagging (UPI, Card, Cash, Bank Transfer)",
                ],
                classification=RequirementClassification.EXPLICIT,
                status=RequirementStatus.ACCEPTED,
            ),
            RequirementItem(
                id="REQ-FUNC-002",
                category=RequirementCategory.FUNCTIONAL,
                priority=RequirementPriority.HIGH,
                description="Category Management: Hierarchical category structure with preloaded defaults for essential income and expenditure categories.",
                acceptance_criteria=[
                    "Default categories: Salary, Freelance, Groceries, Rent, Utilities, Food & Dining, Entertainment, Healthcare, Transportation",
                    "Create custom user-defined categories",
                    "Validate category uniqueness",
                ],
                classification=RequirementClassification.EXPLICIT,
                status=RequirementStatus.ACCEPTED,
            ),
            RequirementItem(
                id="REQ-FUNC-003",
                category=RequirementCategory.FUNCTIONAL,
                priority=RequirementPriority.HIGH,
                description="Monthly Budget Management: Set monthly spending targets per category; calculate spending vs budget; standard reset without rollover.",
                acceptance_criteria=[
                    "Set monthly budget limit per category in INR",
                    "Calculate total spent in category for active month",
                    "Display percentage spent and remaining balance",
                    "Visual alert indicator when spending reaches or exceeds budget",
                    "Reset clean each month (no automatic rollover)",
                ],
                classification=RequirementClassification.EXPLICIT,
                status=RequirementStatus.ACCEPTED,
            ),
            RequirementItem(
                id="REQ-FUNC-004",
                category=RequirementCategory.FUNCTIONAL,
                priority=RequirementPriority.CRITICAL,
                description="Interactive Financial Dashboard: Real-time overview of financial health with KPI metrics and spending distribution charts.",
                acceptance_criteria=[
                    "Total Income KPI card for selected period",
                    "Total Expenses KPI card for selected period",
                    "Net Savings (Income - Expenses) and Savings Rate (%) card",
                    "Category breakdown charts (donut/bar distribution)",
                    "Monthly spending trend timeline",
                    "Instant update when transactions change",
                ],
                classification=RequirementClassification.EXPLICIT,
                status=RequirementStatus.ACCEPTED,
            ),
            RequirementItem(
                id="REQ-FUNC-005",
                category=RequirementCategory.FUNCTIONAL,
                priority=RequirementPriority.MEDIUM,
                description="Monthly Transaction Filtering & Date Navigation: Filter by year, month, or custom date window.",
                acceptance_criteria=[
                    "Month selector changes active view context",
                    "Filter transactions by category and payment mode",
                    "Display record count and filtered total sum",
                ],
                classification=RequirementClassification.EXPLICIT,
                status=RequirementStatus.ACCEPTED,
            ),
            RequirementItem(
                id="REQ-FUNC-006",
                category=RequirementCategory.FUNCTIONAL,
                priority=RequirementPriority.MEDIUM,
                description="CSV Data Export: Download transaction records in standard CSV format.",
                acceptance_criteria=[
                    "Export includes columns: ID, Date, Type, Category, Amount (INR), Payment Mode, Notes",
                    "Handles special characters safely (proper CSV quoting)",
                    "Direct file download with timestamped filename",
                ],
                classification=RequirementClassification.EXPLICIT,
                status=RequirementStatus.ACCEPTED,
            ),
            RequirementItem(
                id="REQ-FUNC-007",
                category=RequirementCategory.FUNCTIONAL,
                priority=RequirementPriority.HIGH,
                description="Input Validation & Meaningful Error Messages: Client and server-side validation rejecting invalid payloads.",
                acceptance_criteria=[
                    "Negative or zero amounts rejected with clear 422/400 error",
                    "Invalid dates rejected",
                    "Non-existent category IDs return descriptive 400/404 messages",
                    "Frontend displays inline validation messages",
                ],
                classification=RequirementClassification.EXPLICIT,
                status=RequirementStatus.ACCEPTED,
            ),
        ],
        nonfunctional_requirements=[
            RequirementItem(
                id="REQ-NFR-001",
                category=RequirementCategory.NONFUNCTIONAL,
                priority=RequirementPriority.CRITICAL,
                description="Local-First Privacy: 100% offline-capable with zero external cloud or third-party network dependencies.",
                acceptance_criteria=[
                    "Zero external API calls",
                    "Local SQLite database stored in user workspace directory",
                    "Zero tracking telemetry",
                ],
                classification=RequirementClassification.REASONABLE_DEFAULT,
                status=RequirementStatus.ACCEPTED,
            ),
            RequirementItem(
                id="REQ-NFR-002",
                category=RequirementCategory.NONFUNCTIONAL,
                priority=RequirementPriority.HIGH,
                description="Sub-50ms API Latency: High responsiveness for local database queries.",
                acceptance_criteria=[
                    "Database indexes on (date, category_id, type)",
                    "FastAPI asynchronous handlers respond in <50ms",
                ],
                classification=RequirementClassification.REASONABLE_DEFAULT,
                status=RequirementStatus.ACCEPTED,
            ),
            RequirementItem(
                id="REQ-NFR-003",
                category=RequirementCategory.NONFUNCTIONAL,
                priority=RequirementPriority.CRITICAL,
                description="Financial Arithmetic Precision: Strict integer or 2-decimal rounded math avoiding floating point inaccuracy.",
                acceptance_criteria=[
                    "Transactions stored with 2 decimal precision (DECIMAL/REAL rounded)",
                    "Sums reconcile to exact penny/paise value",
                ],
                classification=RequirementClassification.REASONABLE_DEFAULT,
                status=RequirementStatus.ACCEPTED,
            ),
        ],
        technical_constraints=[
            RequirementItem(
                id="REQ-TECH-001",
                category=RequirementCategory.TECHNICAL_CONSTRAINT,
                priority=RequirementPriority.CRITICAL,
                description="Frontend Architecture: React with TypeScript, modular component structure, and modern responsive CSS.",
                acceptance_criteria=["React 18+ TypeScript application", "Component-driven layout"],
                classification=RequirementClassification.EXPLICIT,
                status=RequirementStatus.ACCEPTED,
            ),
            RequirementItem(
                id="REQ-TECH-002",
                category=RequirementCategory.TECHNICAL_CONSTRAINT,
                priority=RequirementPriority.CRITICAL,
                description="Backend Architecture: Python FastAPI Modular Monolith with Pydantic validation.",
                acceptance_criteria=["FastAPI with clean routers and dependency injection", "OpenAPI docs generated"],
                classification=RequirementClassification.EXPLICIT,
                status=RequirementStatus.ACCEPTED,
            ),
            RequirementItem(
                id="REQ-TECH-003",
                category=RequirementCategory.TECHNICAL_CONSTRAINT,
                priority=RequirementPriority.CRITICAL,
                description="Database Engine: Embedded SQLite with WAL mode and foreign key integrity.",
                acceptance_criteria=["SQLite with PRAGMA foreign_keys = ON", "Schema migrations/initialization"],
                classification=RequirementClassification.EXPLICIT,
                status=RequirementStatus.ACCEPTED,
            ),
            RequirementItem(
                id="REQ-TECH-004",
                category=RequirementCategory.TECHNICAL_CONSTRAINT,
                priority=RequirementPriority.CRITICAL,
                description="Zero Prohibited Dependencies: Strictly NO Redis, NO microservices, NO Kubernetes, NO Docker.",
                acceptance_criteria=["Zero container dependencies", "Runs directly on host Python and Node/Vite runtimes"],
                classification=RequirementClassification.EXPLICIT,
                status=RequirementStatus.ACCEPTED,
            ),
        ],
        user_workflows=[
            UserWorkflow(
                id="WF-001",
                name="Daily Expense Logging",
                actor="Primary Account Holder",
                trigger="User makes a purchase",
                steps=[
                    "Navigate to Transactions tab",
                    "Click 'New Transaction'",
                    "Enter amount, select category, date, and description",
                    "Submit form",
                ],
                expected_outcome="Transaction recorded; dashboard figures and budget bars update immediately.",
            ),
            UserWorkflow(
                id="WF-002",
                name="Monthly Budget Setting & Review",
                actor="Primary Account Holder",
                trigger="Start of month or financial planning",
                steps=[
                    "Navigate to Budgets tab",
                    "Set monthly budget for categories",
                    "Review budget progress indicators on dashboard",
                ],
                expected_outcome="Budget limits enforced with visual progress and warning threshold.",
            ),
            UserWorkflow(
                id="WF-003",
                name="Monthly Report & CSV Export",
                actor="Primary Account Holder",
                trigger="End of month financial review",
                steps=[
                    "Select target month in date filter",
                    "Inspect category breakdown and net savings",
                    "Click 'Export CSV'",
                ],
                expected_outcome="CSV downloaded containing all transactions matching filter.",
            ),
        ],
        data_requirements=[
            "categories table (id, name, type, icon, color)",
            "transactions table (id, date, amount, type, category_id, payment_mode, notes, created_at)",
            "budgets table (id, category_id, year, month, amount)",
        ],
        integration_requirements=[
            "Local REST API on localhost:8000 (FastAPI)",
            "Local React application on localhost:5173",
        ],
        architecture_considerations=[
            "Modular Monolith with clean internal layer separation (api -> service -> repository -> db)",
            "Zero cross-process network latency beyond localhost",
            "Deterministic test suite runnable via pytest",
        ],
        assumptions_and_defaults=[
            "Currency: Indian Rupees (INR, ₹) - Approved by user",
            "Application Mode: Single-user local-first - Approved by user",
            "Budget Reset: Standard monthly reset without rollover - Approved by user",
            "Ledger Structure: Unified ledger with payment-mode tagging - Approved by user",
        ],
    )

    # 1. Save JSON
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec.to_dict(), f, indent=2)

    # 2. Verify Read-back
    with open(spec_path, "r", encoding="utf-8") as f:
        read_back = json.load(f)

    assert read_back["spec_id"] == "SPEC-FINANCE-2026-001", "Spec ID mismatch"
    assert len(read_back["functional_requirements"]) == 7, "Requirement count mismatch"
    assert read_back["version"] == 2, "Version mismatch"

    # 3. Save Markdown Specification
    docs_dir = REPO_ROOT / "docs" / "requirements"
    docs_dir.mkdir(parents=True, exist_ok=True)
    doc_md = docs_dir / "PERSONAL_FINANCE_SPECIFICATION.md"

    md_content = f"""# PERSONAL FINANCE MANAGEMENT APPLICATION — APPROVED SPECIFICATION
**Specification ID:** {spec.spec_id}  
**Version:** {spec.version} (APPROVED)  
**Approval Date:** {time.strftime("%Y-%m-%d %H:%M:%S")}  
**Status:** `APPROVED FOR IMPLEMENTATION`  

## 1. Approved Business Decisions
1. **Primary Currency:** Indian Rupees (INR, ₹)
2. **User Scope:** Single-user, local-first application (zero cloud dependency, zero authentication friction)
3. **Budgeting Strategy:** Standard monthly reset without rollover (clean allocation per month)
4. **Ledger Model:** Unified transaction ledger with payment-mode tagging (UPI, Card, Cash, Bank Transfer)

## 2. Functional Requirements
"""
    for req in spec.functional_requirements:
        md_content += f"- **[{req.id}] {req.description}**\n  - *Acceptance Criteria:* {'; '.join(req.acceptance_criteria)}\n  - *Classification:* `{req.classification.value}`\n"

    md_content += "\n## 3. Explicit Technical Constraints\n"
    for req in spec.technical_constraints:
        md_content += f"- **[{req.id}]:** {req.description}\n"

    md_content += "\n## 4. Non-Functional Requirements\n"
    for req in spec.nonfunctional_requirements:
        md_content += f"- **[{req.id}]:** {req.description}\n"

    with open(doc_md, "w", encoding="utf-8") as f:
        f.write(md_content)

    print("SUCCESS: Specification updated and verified on disk.")
    print(f"Spec Path: {spec_path}")
    print(f"Read-back items: {len(read_back['functional_requirements'])} functional requirements verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
