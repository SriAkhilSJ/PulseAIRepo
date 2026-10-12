"""Task Quality and User Intent Fulfillment Evaluator for CrusorAI / PulseAI.

Evaluates an AI coding agent's final deliverables and response against the user's
specific prompt and explicit instructions, matching industry benchmarks:
  - Aider (Aider-AI): Anti-laziness/stub detection, syntax & deliverable completeness.
  - SWE-bench / SWE-agent (Princeton NLP): Attributable exit codes & verification receipts.
  - OpenHands (All-Hands-AI): Realized workspace artifact verification vs instructions.
  - Cline (cline/cline): Statistical reliability & multi-action satisfaction.
  - NousResearch Hermes Agent: Verification ledger & Stop Contract compliance.

Scores across 4 grounded dimensions (100-point rubric):
  1. Requirement & Deliverable Fulfillment (35 pts)
  2. Instruction & Constraint Adherence (25 pts)
  3. Verification & Functional Soundness (25 pts)
  4. Polish, Production-Readiness & Presentation (15 pts)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.runtime.reliability_metrics import (
    cost_per_correct_edit,
    detect_malformed_response,
    parse_test_execution,
    tool_efficiency,
)


# =========================================================================
# 1. LAZINESS & STUB PATTERNS (Aider & SWE-bench Standard)
# =========================================================================

STUB_PATTERNS = [
    (re.compile(r"(?i)\b(?:TODO|FIXME|HACK|XXX)\b(?:\s*[:\-]\s*.*)?"), "Unresolved TODO/FIXME comment"),
    (re.compile(r"pass\s*(?:#\s*(?:implement|add|fill|todo|later).*)?$", re.MULTILINE), "Stubbed Python pass statement"),
    (re.compile(r"raise\s+NotImplementedError(?:\(.*\))?"), "NotImplementedError exception stub"),
    (re.compile(r"//\s*\.\.\.\s*(?:rest of|existing|remaining|code).*", re.IGNORECASE), "Lazy Aider-style truncated code comment"),
    (re.compile(r"//\s*(?:implement|add|write)\s+(?:your\s+)?code\s+here.*", re.IGNORECASE), "Unimplemented placeholder comment"),
    (re.compile(r"/\*\s*(?:implement|add|todo|code goes here).*\*/", re.IGNORECASE), "Unimplemented block placeholder"),
    (re.compile(r"<!--\s*(?:add|insert|todo|content goes here).*\-->", re.IGNORECASE), "HTML placeholder comment"),
    (re.compile(r"(?i)\blorem\s+ipsum\b"), "Lorem ipsum placeholder text"),
    (re.compile(r"(?i)\b(?:placeholder\s+text|your\s+code\s+here|replace\s+me)\b"), "Generic placeholder string"),
]

PROHIBITED_INDICATORS: dict[str, list[str]] = {
    "jquery": ["jquery", "$(", "$.", "$[", "jQuery"],
    "lodash": ["lodash", "_.map", "_.filter", "_.get"],
    "bootstrap": ["bootstrap", "bootstrap.min.css", "bootstrap.min.js"],
    "tailwind": ["tailwind", "tailwindcss"],
    "external libraries": ["cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com"],
    "third-party": ["cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com"],
}
NEGATIVE_CONSTRAINT_RE = re.compile(
    r"(?i)\b(?:do\s+not\s+use|don't\s+use|no\s+|without\s+|never\s+use|avoid\s+|prohibit\s+)"
    r"([a-zA-Z0-9_\-\.\s]{2,30}?)(?:[\.,;!\n]|(?:\s+(?:and|or|but|because)\b))"
)

# Common explicit deliverable filename regex
FILE_DELIVERABLE_RE = re.compile(
    r"\b([a-zA-Z0-9_\-\./]+\.(?:html|css|js|ts|tsx|jsx|py|json|md|sql|sh|yml|yaml|svg|png|jpg|jpeg|vue|svelte|go|rs|cpp|c|h|java|kt))\b",
    re.IGNORECASE,
)


@dataclass
class PillarScore:
    name: str
    score: float
    max_score: float
    status: str  # "pass", "warning", "fail"
    details: list[str] = field(default_factory=list)
    deductions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 1),
            "max_score": self.max_score,
            "status": self.status,
            "details": self.details,
            "deductions": self.deductions,
        }


@dataclass
class QualityReport:
    session_id: str
    user_ask: str
    quality_score: float  # 0 - 100
    quality_grade: str    # A+, A, B, C, D
    runtime_score: float  # 0 - 100
    unified_score: float  # 0.60 * quality + 0.40 * runtime
    unified_grade: str
    pillars: dict[str, PillarScore]
    identified_gaps: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    artifacts_inspected: list[str] = field(default_factory=list)
    stub_audit: dict[str, Any] = field(default_factory=dict)
    verification_summary: dict[str, Any] = field(default_factory=dict)
    economics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_ask": self.user_ask,
            "quality_score": round(self.quality_score, 1),
            "quality_grade": self.quality_grade,
            "runtime_score": round(self.runtime_score, 1),
            "unified_score": round(self.unified_score, 1),
            "unified_grade": self.unified_grade,
            "pillars": {k: v.to_dict() for k, v in self.pillars.items()},
            "identified_gaps": self.identified_gaps,
            "recommendations": self.recommendations,
            "artifacts_inspected": self.artifacts_inspected,
            "stub_audit": self.stub_audit,
            "verification_summary": self.verification_summary,
            "economics": self.economics,
        }


class UserAskQualityEvaluator:
    """Evaluates how effectively the agent fulfilled the user's prompt and delivered production-grade code."""

    def __init__(self, workspace_path: Optional[str] = None):
        self.workspace_path = Path(workspace_path or os.getcwd()).resolve()

    def evaluate(
        self,
        user_ask: str,
        session_id: str = "session-eval",
        runtime_score: float = 85.0,
        marked_edits: Optional[list[str]] = None,
        tool_records: Optional[list[dict[str, Any]]] = None,
        verification_status: str = "passed",
        final_assistant_message: str = "",
        verification_receipts: Optional[dict[str, Any]] = None,
    ) -> QualityReport:
        """Run the comprehensive 4-pillar quality evaluation."""
        user_ask = (user_ask or "").strip()
        marked_edits = marked_edits or []
        tool_records = tool_records or []
        verification_receipts = verification_receipts or {}

        # Collect all referenced/created artifacts
        all_artifacts = set(marked_edits)
        for tr in tool_records:
            name = tr.get("name", "")
            args = tr.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if name in ("write_file", "edit_file", "generate_image", "media_download"):
                path_val = args.get("path") or args.get("filename") or args.get("file_path")
                if path_val:
                    all_artifacts.add(str(path_val))

        # Check if the prompt requested creating or modifying software
        is_creation_intent = any(
            marker in user_ask.lower()
            for marker in (
                "build", "create", "implement", "make", "scaffold", "write",
                "develop", "add", "fix", "setup", "craft", "design", "compose",
                "generate", "construct", "app", "application", "server", "api",
                "dashboard", "portfolio", "timer", "component", "screen"
            )
        )

        # -----------------------------------------------------------------
        # Pillar 1: Requirement & Deliverable Fulfillment (35.0 pts)
        # -----------------------------------------------------------------
        p1 = self._eval_requirement_and_deliverables(user_ask, all_artifacts, is_creation_intent)

        # -----------------------------------------------------------------
        # Pillar 2: Instruction & Constraint Adherence (25.0 pts)
        # -----------------------------------------------------------------
        p2 = self._eval_instruction_and_constraints(user_ask, all_artifacts)

        # -----------------------------------------------------------------
        # Pillar 3: Verification & Functional Soundness (25.0 pts)
        # -----------------------------------------------------------------
        p3 = self._eval_verification_and_soundness(
            verification_status=verification_status,
            verification_receipts=verification_receipts,
            tool_records=tool_records,
            all_artifacts=all_artifacts,
            is_creation_intent=is_creation_intent,
        )

        # -----------------------------------------------------------------
        # Pillar 4: Polish, Production-Readiness & Presentation (15.0 pts)
        # -----------------------------------------------------------------
        p4 = self._eval_polish_and_presentation(
            final_message=final_assistant_message,
            all_artifacts=all_artifacts,
        )

        quality_score = max(0.0, min(100.0, p1.score + p2.score + p3.score + p4.score))

        # Quality Grade
        if quality_score >= 95.0:
            quality_grade = "A+ (Flawless)"
        elif quality_score >= 88.0:
            quality_grade = "A (Elite)"
        elif quality_score >= 78.0:
            quality_grade = "B (Strong)"
        elif quality_score >= 68.0:
            quality_grade = "C (Needs Polish)"
        else:
            quality_grade = "D (Deficient / Incomplete)"

        # Unified Champion Agent Score: 60% Quality + 40% Runtime Execution
        unified_score = round((0.60 * quality_score) + (0.40 * runtime_score), 1)
        if unified_score >= 92.0:
            unified_grade = "A (Elite Champion)"
        elif unified_score >= 82.0:
            unified_grade = "B (Strong Contender)"
        elif unified_score >= 72.0:
            unified_grade = "C (Moderate Bottlenecks)"
        else:
            unified_grade = "D (Needs Optimization)"

        # Compile Gaps & Recommendations
        gaps = p1.deductions + p2.deductions + p3.deductions + p4.deductions
        recs = []
        if p1.deductions:
            recs.append("🎯 **Deliverable Completeness:** Ensure every explicitly requested file and feature is fully authored without stubbed TODOs or empty templates.")
        if p2.deductions:
            recs.append("🛡️ **Constraint Discipline:** Strictly respect negative constraints (e.g. 'do not use external libraries' or framework restrictions).")
        if p3.deductions:
            recs.append("🧪 **Verification Rigor:** Run end-to-end typechecks, test suites, or live browser verification before finalizing the turn.")
        if p4.deductions:
            recs.append("✨ **User Presentation:** Provide concise, structured walkthroughs with direct run commands and deliverable links.")

        if not recs:
            recs.append("🚀 **Outstanding Output Quality:** All deliverables created, zero stubbed code, constraints adhered to, and verified sound.")

        stub_audit = self._scan_stubs_across_artifacts(all_artifacts)

        # Economics: cost-per-correct-edit (Aider CFO-grade) + tool efficiency
        n_deliverables = len([a for a in all_artifacts if Path(a).suffix in (".html", ".css", ".js", ".ts", ".py", ".json")])
        cpe = cost_per_correct_edit(runtime_score / 100.0 * 0.5, n_deliverables) if n_deliverables else None
        efficiency = tool_efficiency(tool_records)

        return QualityReport(
            session_id=session_id,
            user_ask=user_ask,
            quality_score=round(quality_score, 1),
            quality_grade=quality_grade,
            runtime_score=round(runtime_score, 1),
            unified_score=unified_score,
            unified_grade=unified_grade,
            pillars={
                "deliverables": p1,
                "constraints": p2,
                "soundness": p3,
                "presentation": p4,
            },
            identified_gaps=gaps,
            recommendations=recs,
            artifacts_inspected=sorted(list(all_artifacts)),
            stub_audit=stub_audit,
            verification_summary={
                "status": verification_status,
                "receipts": verification_receipts,
            },
            economics={
                "cost_per_correct_edit_usd": cpe,
                "n_deliverables": n_deliverables,
                "tool_efficiency": efficiency,
            },
        )

    # ---------------------------------------------------------------------
    # Internal Pillar Evaluators
    # ---------------------------------------------------------------------

    def _eval_requirement_and_deliverables(
        self,
        user_ask: str,
        artifacts: set[str],
        is_creation_intent: bool = False,
    ) -> PillarScore:
        score = 35.0
        details = []
        deductions = []

        if not user_ask:
            return PillarScore("Requirement & Deliverables", 35.0, 35.0, "pass", ["No explicit user ask specified."])

        # 1. Check explicitly requested files
        requested_files = set(m.lower() for m in FILE_DELIVERABLE_RE.findall(user_ask))
        # Filter out common false positives (e.g., node.js or vue.js mentioned as frameworks)
        framework_names = {"node.js", "vue.js", "react.js", "next.js", "express.js", "three.js"}
        requested_files = {f for f in requested_files if f not in framework_names}

        if requested_files:
            matched_files = set()
            missing_files = set()
            for rf in requested_files:
                rf_base = Path(rf).name.lower()
                found = any(Path(art).name.lower() == rf_base or rf_base in art.lower() for art in artifacts)
                # Also check disk directly in workspace
                if not found:
                    disk_matches = list(self.workspace_path.glob(f"**/{rf_base}"))
                    if disk_matches:
                        found = True
                        artifacts.add(str(disk_matches[0]))

                if found:
                    matched_files.add(rf)
                else:
                    missing_files.add(rf)

            if missing_files:
                # If nothing was created at all, penalize full deliverable budget
                if not artifacts:
                    score = 0.0
                    deductions.append(f"🚨 [Zero Mutation Failure] Zero files created. Missing all {len(missing_files)} requested deliverable(s): {', '.join(sorted(missing_files))} (-35.0 pts)")
                else:
                    penalty = min(25.0, len(missing_files) * 10.0)
                    score -= penalty
                    deductions.append(f"Missing {len(missing_files)} requested file(s): {', '.join(sorted(missing_files))} (-{penalty:.1f} pts)")
            else:
                details.append(f"All {len(matched_files)} explicitly requested file deliverables created successfully.")
        else:
            if not artifacts and is_creation_intent:
                score = 0.0
                deductions.append("🚨 [Zero Mutation Failure] User requested building software, but ZERO files were created or modified (-35.0 pts)")
            elif artifacts:
                details.append(f"Created/modified {len(artifacts)} workspace artifact(s).")
            else:
                # If the user ask was a question or chat prompt, no files were needed
                details.append("Informational prompt (no standalone files requested).")

        # 2. Anti-Laziness / Stub Check across created artifacts (Aider standard)
        stub_results = self._scan_stubs_across_artifacts(artifacts)
        total_stubs = stub_results["total_stubs"]
        if total_stubs > 0:
            stub_penalty = min(12.0, total_stubs * 3.0)
            score -= stub_penalty
            deductions.append(f"Detected {total_stubs} unresolved code stub(s) / lazy placeholder(s) across {len(stub_results['stubbed_files'])} file(s) (-{stub_penalty:.1f} pts)")
        else:
            if artifacts:
                details.append("Zero lazy placeholders or unresolved TODO stubs detected across deliverables.")

        # 3. Artifact Substance & Non-Emptiness Check
        empty_files = []
        for art in artifacts:
            p = self._resolve_path(art)
            if p and p.exists() and p.is_file():
                try:
                    content = p.read_text(encoding="utf-8", errors="ignore").strip()
                    if len(content) < 15 and p.suffix not in (".png", ".jpg", ".jpeg", ".ico"):
                        empty_files.append(art)
                except Exception:
                    pass

        if empty_files:
            empty_penalty = min(8.0, len(empty_files) * 4.0)
            score -= empty_penalty
            deductions.append(f"{len(empty_files)} created artifact(s) appear empty or stub-only: {', '.join(empty_files)} (-{empty_penalty:.1f} pts)")

        final_score = max(0.0, min(35.0, score))
        status = "pass" if final_score >= 28.0 else ("warning" if final_score >= 20.0 else "fail")
        return PillarScore("Requirement & Deliverables", final_score, 35.0, status, details, deductions)

    def _eval_instruction_and_constraints(self, user_ask: str, artifacts: set[str]) -> PillarScore:
        score = 25.0
        details = []
        deductions = []

        if not user_ask:
            return PillarScore("Instruction & Constraints", 25.0, 25.0, "pass", ["No negative constraints present."])

        # 1. Negative Constraint Prohibitions
        neg_matches = NEGATIVE_CONSTRAINT_RE.findall(user_ask)
        prohibited_terms = [m.strip().lower() for m in neg_matches if len(m.strip()) > 2]

        violated_terms = []
        for term in prohibited_terms:
            # Clean common words
            clean_term = re.sub(r"^(any|the|a|an)\s+", "", term).strip()
            if clean_term in ("error", "bug", "crash", "warning", "delay"):
                continue  # Skip generic desires like "no errors"

            indicators = [clean_term]
            for p_key, p_inds in PROHIBITED_INDICATORS.items():
                if p_key in clean_term or clean_term in p_key:
                    indicators.extend(p_inds)

            # Check if prohibited term or indicator appears in created source files or package.json
            for art in artifacts:
                p = self._resolve_path(art)
                if p and p.exists() and p.is_file() and p.suffix in (".html", ".js", ".ts", ".tsx", ".py", ".json", ".css"):
                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        content_lower = content.lower()
                        if any(ind in content or ind.lower() in content_lower for ind in indicators if ind not in ("code", "file")):
                            violated_terms.append((clean_term, art))
                            break
                    except Exception:
                        pass

        if violated_terms:
            penalty = min(15.0, len(violated_terms) * 5.0)
            score -= penalty
            viol_str = ", ".join([f"'{t}' in {p}" for t, p in violated_terms])
            deductions.append(f"Violated negative constraint prohibition: {viol_str} (-{penalty:.1f} pts)")
        elif prohibited_terms:
            details.append(f"Successfully respected {len(prohibited_terms)} negative instruction constraint(s).")
        else:
            details.append("No explicit negative constraints specified in prompt.")

        # 2. Key Framework / Tech Stack Directives
        tech_keywords = {
            "typescript": [".ts", ".tsx", "tsconfig.json"],
            "react": ["react", "jsx", "tsx"],
            "tailwind": ["tailwind", "tailwindcss"],
            "fastapi": ["fastapi"],
            "flask": ["flask"],
            "docker": ["dockerfile", "docker-compose"],
            "sqlite": ["sqlite", ".db", "sqlite3"],
        }

        user_ask_lower = user_ask.lower()
        requested_tech = [tech for tech in tech_keywords if tech in user_ask_lower]
        if requested_tech:
            matched_tech = []
            missing_tech = []
            for tech in requested_tech:
                expected_indicators = tech_keywords[tech]
                found = False
                for art in artifacts:
                    art_lower = art.lower()
                    if any(ind in art_lower for ind in expected_indicators):
                        found = True
                        break
                    p = self._resolve_path(art)
                    if p and p.exists() and p.is_file():
                        try:
                            content = p.read_text(encoding="utf-8", errors="ignore").lower()
                            if any(ind in content for ind in expected_indicators):
                                found = True
                                break
                        except Exception:
                            pass
                if found:
                    matched_tech.append(tech)
                else:
                    missing_tech.append(tech)

            if missing_tech:
                penalty = min(10.0, len(missing_tech) * 3.5)
                score -= penalty
                deductions.append(f"Requested tech stack directive not evidenced in artifacts: {', '.join(missing_tech)} (-{penalty:.1f} pts)")
            else:
                details.append(f"Evidenced requested tech stack directives: {', '.join(matched_tech)}.")

        final_score = max(0.0, min(25.0, score))
        status = "pass" if final_score >= 20.0 else ("warning" if final_score >= 15.0 else "fail")
        return PillarScore("Instruction & Constraints", final_score, 25.0, status, details, deductions)

    def _eval_verification_and_soundness(
        self,
        verification_status: str,
        verification_receipts: dict[str, Any],
        tool_records: list[dict[str, Any]],
        all_artifacts: Optional[set[str]] = None,
        is_creation_intent: bool = False,
    ) -> PillarScore:
        score = 25.0
        details = []
        deductions = []

        all_artifacts = all_artifacts or set()

        if is_creation_intent and not all_artifacts:
            score = 0.0
            deductions.append("Zero deliverables created: cannot verify soundness on non-existent code (-25.0 pts)")
            return PillarScore("Verification & Soundness", 0.0, 25.0, "fail", details, deductions)

        # 1. Overall Status check (from gates / evidence ledger)
        status_clean = (verification_status or "passed").lower()
        if status_clean == "passed":
            details.append("Verification status verified as PASSED in evidence ledger.")
        elif status_clean == "stale":
            score -= 5.0
            deductions.append("Verification status is STALE (code was edited after the last test run) (-5.0 pts)")
        elif status_clean in ("failed", "unverified"):
            score -= 12.0
            deductions.append(f"Verification status is {status_clean.upper()} (-12.0 pts)")

        # 2. Check for tool failure exit codes in verification tools
        test_tools = [
            tc for tc in tool_records
            if any(k in tc.get("name", "").lower() for k in ("terminal", "test", "typecheck", "browser", "preview"))
        ]
        test_failures = [
            tc for tc in test_tools
            if tc.get("status") != "success" or (tc.get("exit_code") is not None and tc.get("exit_code") != 0)
        ]

        if test_failures:
            penalty = min(10.0, len(test_failures) * 3.0)
            score -= penalty
            deductions.append(f"{len(test_failures)} verification/terminal command(s) returned non-zero exit codes (-{penalty:.1f} pts)")
        elif test_tools:
            details.append(f"All {len(test_tools)} executed terminal/verification command(s) exited cleanly with code 0.")

        # 2b. Attributable test-execution proof (SWE-bench grading.py lesson:
        # "Executed 0 of 0" under FAIL_ONLY eval scores every test as passing —
        # a zero-count read as evidence turns a suite that never ran into a
        # resolved instance). Parse the actual test output for executed counts.
        test_outputs = " ".join(
            str(tc.get("output") or tc.get("result") or "")
            for tc in test_tools
        )
        exec_proof = parse_test_execution(test_outputs)
        if test_tools:
            if exec_proof["invalid"]:
                score -= 15.0
                deductions.append(
                    f"Test suite never actually ran: '{exec_proof['evidence']}' — "
                    f"zero-count execution is INVALID, not a pass (-15.0 pts)"
                )
            elif exec_proof["ran"] and exec_proof["executed"] > 0:
                details.append(
                    f"Attributable verification: {exec_proof['evidence']} "
                    f"({exec_proof['executed']} test(s) executed)."
                )

        # 3. Browser & Console Errors (for UI tasks)
        console_errors = verification_receipts.get("console_errors") or []
        if console_errors:
            penalty = min(8.0, len(console_errors) * 2.0)
            score -= penalty
            deductions.append(f"Encountered {len(console_errors)} uncaught JavaScript console error(s) during browser run (-{penalty:.1f} pts)")
        elif verification_receipts.get("browser_verified"):
            details.append("Headless browser verification completed with ZERO uncaught console errors.")

        final_score = max(0.0, min(25.0, score))
        status = "pass" if final_score >= 20.0 else ("warning" if final_score >= 14.0 else "fail")
        return PillarScore("Verification & Soundness", final_score, 25.0, status, details, deductions)

    def _eval_polish_and_presentation(self, final_message: str, all_artifacts: set[str]) -> PillarScore:
        score = 15.0
        details = []
        deductions = []

        msg = (final_message or "").strip()

        # 1. Presentation clarity check
        if msg:
            # Malformed response detection (Aider standard): truncated JSON,
            # unbalanced braces, leaked reasoning, trailing commas.
            malformed = detect_malformed_response(msg)
            if malformed:
                penalty = min(5.0, len(malformed) * 1.5)
                score -= penalty
                deductions.append(
                    f"Malformed/truncated response detected: {', '.join(malformed)} (-{penalty:.1f} pts)"
                )
            # Check for leaked thought blocks or repetitive internal monologues
            if "<think>" in msg or "</think>" in msg:
                score -= 3.0
                deductions.append("Leaked raw internal reasoning `<think>` tags into final user response (-3.0 pts)")

            # Check if final message provides clear summary or run instructions
            has_run_instructions = any(
                term in msg.lower()
                for term in ("open", "run", "npm", "python", "visit", "http", "view", "created", "deliverable", "preview")
            )
            if has_run_instructions:
                details.append("Final response provides clear summary and actionable usage/run instructions.")
            else:
                score -= 2.0
                deductions.append("Final response lacks explicit usage or launch instructions (-2.0 pts)")
        else:
            # Empty final message
            if all_artifacts:
                score -= 3.0
                deductions.append("No final completion walkthrough message provided to the user (-3.0 pts)")

        # 2. Code Quality & Styling Polish across artifacts
        html_files = [art for art in all_artifacts if art.endswith(".html")]
        css_files = [art for art in all_artifacts if art.endswith(".css")]

        if html_files:
            # Check if HTML has viewport meta tag for mobile responsiveness
            for hf in html_files:
                p = self._resolve_path(hf)
                if p and p.exists():
                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        if "viewport" not in content.lower():
                            score -= 1.5
                            deductions.append(f"HTML artifact `{Path(hf).name}` missing responsive `<meta name='viewport'>` tag (-1.5 pts)")
                            break
                    except Exception:
                        pass

        if not deductions:
            details.append("Output exhibits high polish, responsive structure, and clean presentation.")

        final_score = max(0.0, min(15.0, score))
        status = "pass" if final_score >= 12.0 else ("warning" if final_score >= 8.0 else "fail")
        return PillarScore("Polish & Presentation", final_score, 15.0, status, details, deductions)

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    def _resolve_path(self, path_str: str) -> Optional[Path]:
        try:
            p = Path(path_str)
            if p.is_absolute():
                return p
            return (self.workspace_path / path_str).resolve()
        except Exception:
            return None

    def _scan_stubs_across_artifacts(self, artifacts: set[str]) -> dict[str, Any]:
        """Scan all provided artifact paths for lazy comments and incomplete stubs."""
        stubbed_files = {}
        total_stubs = 0

        for art in artifacts:
            p = self._resolve_path(art)
            if not p or not p.exists() or not p.is_file():
                continue
            if p.suffix not in (".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".md", ".json", ".sql", ".sh"):
                continue

            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            file_stubs = []
            for pattern, desc in STUB_PATTERNS:
                matches = pattern.findall(content)
                if matches:
                    for m in matches:
                        match_preview = m.strip() if isinstance(m, str) else str(m)
                        if len(match_preview) > 60:
                            match_preview = match_preview[:60] + "..."
                        file_stubs.append({"pattern": desc, "preview": match_preview})
                        total_stubs += 1

            if file_stubs:
                stubbed_files[p.name] = file_stubs

        return {
            "total_stubs": total_stubs,
            "stubbed_files": stubbed_files,
        }
