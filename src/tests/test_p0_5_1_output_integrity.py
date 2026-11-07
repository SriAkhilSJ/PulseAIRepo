"""
test_p0_5_1_output_integrity.py - P0.5.1 Output Integrity & Pre-Mutation Validation.

Covers:
  1. Valid complete Python code is accepted.
  2. Complete Markdown Python fence is extracted correctly.
  3. Incomplete Markdown fence is rejected.
  4. Empty model output is rejected.
  5. Unterminated triple-quoted string is rejected (syntax error).
  6. Missing closing bracket is rejected (syntax error).
  7. finish_reason=length is rejected (IncompleteModelOutputError).
  8. finish_reason=stop with valid Python is accepted.
  9. Invalid output never reaches WorkspaceMutationBroker.
 10. Invalid output does not create a target file.
 11. Invalid output does not overwrite an existing file.
 12. A multi-file task does not partially mutate files if one generated output fails.
 13. Valid output still reaches the broker and produces a mutation receipt.
 14. Validation does not trigger another model invocation.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import src.orchestration.model_adapter as ma
from src.orchestration.finops_governor import OrchestrationFinOpsGovernor
from src.orchestration.implementation_engine import ControlledImplementationEngine
from src.orchestration.loop import BoundedAutonomousReasoningLoop
from src.orchestration.model_adapter import (
    EmptyModelOutputError,
    IncompleteModelOutputError,
    InvalidGeneratedSourceError,
    ModelExecutionAdapter,
    SourceExtractionError,
    extract_generated_source,
    validate_generated_source,
)
from src.orchestration.models import EngineeringTaskNode
from src.workspace.mutation_broker import WorkspaceMutationBroker


class TestP051OutputIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="crusor_p0_5_1_")
        self.ws = Path(self.tmp).resolve()
        self.broker = WorkspaceMutationBroker(str(self.ws))
        self.impl_engine = ControlledImplementationEngine(str(self.ws), broker=self.broker)
        self.finops = OrchestrationFinOpsGovernor("task_p0_5_1", budget_inr=100.0, token_budget=100000)
        self.loop = BoundedAutonomousReasoningLoop()
        self._orig_get_llm = ma.get_llm

    def tearDown(self) -> None:
        ma.get_llm = self._orig_get_llm
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_1_valid_complete_python_code_is_accepted(self) -> None:
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        extracted = extract_generated_source(code, "src/add.py")
        self.assertEqual(extracted, code.strip())
        validator = validate_generated_source("src/add.py", extracted)
        self.assertEqual(validator, "python_ast")

    def test_2_complete_markdown_python_fence_extracted_correctly(self) -> None:
        payload = "Here is the code:\n```python\ndef foo() -> str:\n    return 'bar'\n```\nEnjoy!"
        extracted = extract_generated_source(payload, "src/foo.py")
        self.assertIn("def foo", extracted)
        self.assertNotIn("```python", extracted)
        self.assertNotIn("Here is", extracted)
        validator = validate_generated_source("src/foo.py", extracted)
        self.assertEqual(validator, "python_ast")

    def test_3_incomplete_markdown_fence_rejected(self) -> None:
        payload = "```python\ndef incomplete():\n    pass"
        with self.assertRaises(SourceExtractionError):
            extract_generated_source(payload, "src/inc.py")

    def test_4_empty_model_output_rejected(self) -> None:
        for empty in ("", "   \n\t ", "```python\n\n```"):
            with self.subTest(empty=empty):
                with self.assertRaises((EmptyModelOutputError, SourceExtractionError)):
                    extract_generated_source(empty, "src/empty.py")

    def test_5_unterminated_string_rejected_by_syntax(self) -> None:
        code = 'def unterm():\n    """Unterminated docstring'
        extracted = extract_generated_source(code, "src/unterm.py")
        with self.assertRaises(InvalidGeneratedSourceError):
            validate_generated_source("src/unterm.py", extracted)

    def test_6_missing_closing_bracket_rejected_by_syntax(self) -> None:
        code = "def bad():\n    return [1, 2, 3\n"
        extracted = extract_generated_source(code, "src/bad.py")
        with self.assertRaises(InvalidGeneratedSourceError):
            validate_generated_source("src/bad.py", extracted)

    def test_7_finish_reason_length_rejected(self) -> None:
        class LengthLLM:
            def invoke(self, prompt: str, **kwargs):
                return type(
                    "Resp",
                    (),
                    {
                        "content": "```python\ndef partial():\n```",
                        "response_metadata": {"finish_reason": "length"},
                        "usage_metadata": {"input_tokens": 10, "output_tokens": 256, "total_tokens": 266},
                    },
                )()

        ma.get_llm = lambda provider=None, model=None: LengthLLM()
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="custom", model="z-ai/glm-5.3-flash")
        node = EngineeringTaskNode(
            node_id="node_len",
            description="Length truncation test",
            objective="Reject length-truncated output",
            target_files=["src/length_target.py"],
        )

        with self.assertRaises(IncompleteModelOutputError):
            adapter.execute_node(
                task_id="task_p0_5_1",
                node=node,
                specification=None,
                blueprint=None,
                project_knowledge=None,
                impl_engine=self.impl_engine,
                finops=self.finops,
                reasoning_loop=self.loop,
            )

    def test_8_finish_reason_stop_with_valid_python_accepted(self) -> None:
        class StopLLM:
            def invoke(self, prompt: str, **kwargs):
                return type(
                    "Resp",
                    (),
                    {
                        "content": "```python\ndef success() -> int:\n    return 42\n```",
                        "response_metadata": {"finish_reason": "stop"},
                        "usage_metadata": {"input_tokens": 15, "output_tokens": 20, "total_tokens": 35},
                    },
                )()

        ma.get_llm = lambda provider=None, model=None: StopLLM()
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="custom", model="z-ai/glm-5.3-flash")
        node = EngineeringTaskNode(
            node_id="node_stop",
            description="Stop success test",
            objective="Accept stop-terminated valid python",
            target_files=["src/stop_target.py"],
        )

        res = adapter.execute_node(
            task_id="task_p0_5_1",
            node=node,
            specification=None,
            blueprint=None,
            project_knowledge=None,
            impl_engine=self.impl_engine,
            finops=self.finops,
            reasoning_loop=self.loop,
        )
        self.assertTrue(res)
        self.assertTrue((self.ws / "src" / "stop_target.py").exists())

    def test_9_to_11_invalid_output_never_reaches_broker_or_disk(self) -> None:
        invocations = [0]

        class InvalidSyntaxLLM:
            def invoke(self, prompt: str, **kwargs):
                invocations[0] += 1
                return type(
                    "Resp",
                    (),
                    {
                        "content": "```python\ndef syntax_error(:\n    pass\n```",
                        "response_metadata": {"finish_reason": "stop"},
                        "usage_metadata": {"input_tokens": 10, "output_tokens": 15, "total_tokens": 25},
                    },
                )()

        ma.get_llm = lambda provider=None, model=None: InvalidSyntaxLLM()
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="custom", model="z-ai/glm-5.3-flash")
        target_rel = "src/protected_target.py"
        full_target = self.ws / target_rel

        # Test 11: Pre-existing file content must not be overwritten
        full_target.parent.mkdir(parents=True, exist_ok=True)
        full_target.write_text("# Original user content", encoding="utf-8")

        node = EngineeringTaskNode(
            node_id="node_invalid",
            description="Invalid output test",
            objective="Prevent invalid mutation",
            target_files=[target_rel],
        )

        with self.assertRaises(InvalidGeneratedSourceError):
            adapter.execute_node(
                task_id="task_p0_5_1",
                node=node,
                specification=None,
                blueprint=None,
                project_knowledge=None,
                impl_engine=self.impl_engine,
                finops=self.finops,
                reasoning_loop=self.loop,
            )

        # Assertions for 9, 10, 11, and 14:
        self.assertEqual(invocations[0], 1, "Model was invoked once")
        # File must retain original content (not overwritten)
        self.assertEqual(full_target.read_text(encoding="utf-8"), "# Original user content")
        # Broker ledger must have zero records for this task
        records = self.broker.ledger.get_records("task_p0_5_1")
        self.assertEqual(len(records), 0, "No mutation record permitted in broker ledger")

    def test_12_multi_file_task_no_partial_mutation(self) -> None:
        """A multi-file task does not partially mutate files if one generated output fails."""
        target_a = "src/file_a.py"
        target_b = "src/file_b.py"

        class MultiFileLLM:
            def __init__(self):
                self.calls = 0

            def invoke(self, prompt: str, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    # First file: valid code
                    content = "```python\ndef file_a_ok():\n    return True\n```"
                else:
                    # Second file: syntax error
                    content = "```python\ndef file_b_bad(:\n    pass\n```"
                return type(
                    "Resp",
                    (),
                    {
                        "content": content,
                        "response_metadata": {"finish_reason": "stop"},
                        "usage_metadata": {"input_tokens": 10, "output_tokens": 15, "total_tokens": 25},
                    },
                )()

        multi_llm = MultiFileLLM()
        ma.get_llm = lambda provider=None, model=None: multi_llm
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="custom", model="z-ai/glm-5.3-flash")

        node = EngineeringTaskNode(
            node_id="node_multifile",
            description="Multi-file test",
            objective="All-or-nothing multi-file mutation",
            target_files=[target_a, target_b],
        )

        with self.assertRaises(InvalidGeneratedSourceError):
            adapter.execute_node(
                task_id="task_p0_5_1_multi",
                node=node,
                specification=None,
                blueprint=None,
                project_knowledge=None,
                impl_engine=self.impl_engine,
                finops=self.finops,
                reasoning_loop=self.loop,
            )

        # Neither file must be mutated/created on disk
        self.assertFalse((self.ws / target_a).exists(), "File A must not be partially created")
        self.assertFalse((self.ws / target_b).exists(), "File B must not be created")
        self.assertEqual(len(self.broker.ledger.get_records("task_p0_5_1_multi")), 0)

    def test_13_valid_output_reaches_broker_and_produces_receipt(self) -> None:
        class ValidLLM:
            def invoke(self, prompt: str, **kwargs):
                return type(
                    "Resp",
                    (),
                    {
                        "content": "```python\ndef valid_service():\n    return 100\n```",
                        "response_metadata": {"finish_reason": "stop"},
                        "usage_metadata": {"input_tokens": 20, "output_tokens": 30, "total_tokens": 50},
                    },
                )()

        ma.get_llm = lambda provider=None, model=None: ValidLLM()
        adapter = ModelExecutionAdapter(str(self.ws), mock_mode=False, provider="custom", model="z-ai/glm-5.3-flash")
        target_rel = "src/valid_target.py"

        node = EngineeringTaskNode(
            node_id="node_valid",
            description="Valid output test",
            objective="Produce mutation receipt",
            target_files=[target_rel],
        )

        res = adapter.execute_node(
            task_id="task_p0_5_1_valid",
            node=node,
            specification=None,
            blueprint=None,
            project_knowledge=None,
            impl_engine=self.impl_engine,
            finops=self.finops,
            reasoning_loop=self.loop,
        )
        self.assertTrue(res)
        self.assertTrue((self.ws / target_rel).exists())
        records = self.broker.ledger.get_records("task_p0_5_1_valid")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].file_path, target_rel)
        self.assertEqual(records[0].verification_status, "VERIFIED")


if __name__ == "__main__":
    unittest.main()
