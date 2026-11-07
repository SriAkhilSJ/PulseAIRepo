"""P0.6.4 — Desktop observability harness: offline regression suite.

Covers the evidence substrate only (no Electron launch, no bridge process,
no provider call):

  1. Run identity is immutable: a second run cannot adopt an existing evidence dir.
  2. The ledger is append-only and re-readable from disk.
  3. Records from a foreign run id are rejected by the correlator.
  4. Records that never came from a desktop UI submission are "disconnected".
  5. Criteria classification is driven by record presence (3-state).
  6. A provider dispatch record without real ids is refused.
  7. The bridge probe refuses every provider-capable frame type.
  8. The bridge probe allows only the offline probe allowlist.
  9. CDP target parsing keeps page targets and ignores non-page targets.
 10. CDP target selection prefers the app's workbench page.
 11. CDP refuses a non-loopback endpoint; loopback bind detection is exact.
 12. The DOM snapshot expression is pure and quotes the selector safely.
 13. Renderer page identity rejects non-Electron / non-workbench pages.
 14. Invariant 7 detects both a matching manifest and a drifted file.
 15. Offline budget preflight computes a cost and never dispatches.
 16. Prompt correlation uses a content hash, never the prompt text.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from benchmarks.crusor_desktop_acceptance.bridge_probe import (
    PAID_FRAME_TYPES,
    PROBE_ALLOWED_FRAMES,
    PaidCallRefused,
    assert_frame_is_offline,
    prompt_fingerprint,
)
from benchmarks.crusor_desktop_acceptance.cdp_client import (
    CdpError,
    assert_loopback,
    build_dom_snapshot_expression,
    parse_targets,
    pick_page_target,
)
from benchmarks.crusor_desktop_acceptance.correlation import (
    CorrelationError,
    Correlator,
    RunContext,
)
from benchmarks.crusor_desktop_acceptance.invariant7 import check_invariant7, sha256_file
from benchmarks.crusor_desktop_acceptance.processes import is_loopback_bind
from benchmarks.crusor_desktop_acceptance.provider_finops import (
    DispatchObservation,
    EvidenceIncomplete,
    preflight_estimate,
    record_dispatch,
)
from benchmarks.crusor_desktop_acceptance.renderer_observer import page_belongs_to_crusor


class TestRunIdentity(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="crusor_p0_6_4_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_1_run_id_is_immutable_per_evidence_dir(self) -> None:
        first = RunContext(self.tmp / "evidence", run_id="run_a")
        self.assertEqual(first.run_id, "run_a")
        with self.assertRaises(CorrelationError):
            RunContext(self.tmp / "evidence", run_id="run_b")

    def test_2_ledger_is_append_only_and_rereadable(self) -> None:
        ctx = RunContext(self.tmp / "evidence", run_id="run_ledger")
        ctx.record("electron", "electron.launch", {"pid": 123}, pid=123)
        ctx.record("bridge", "bridge.handshake", {"engine": "crusorai"})
        on_disk = ctx.read_ledger()
        self.assertEqual(len(on_disk), 2)
        self.assertEqual(on_disk[0]["kind"], "electron.launch")
        self.assertEqual(on_disk[1]["layer"], "bridge")
        # A second append must not rewrite the earlier lines.
        ctx.record("renderer", "cdp.target", {"id": "page-1"})
        self.assertEqual(len(ctx.read_ledger()), 3)
        self.assertEqual(ctx.read_ledger()[0], on_disk[0])


class TestCorrelation(unittest.TestCase):
    def _record(self, layer: str, kind: str, *, run_id: str = "run_1",
                session: str = "s1", turn: str = "t1") -> dict:
        return {
            "layer": layer, "kind": kind, "run_id": run_id,
            "session_id": session, "turn_id": turn, "timestamp": "t",
            "task_id": "task_shared", "payload": {},
        }

    def test_3_foreign_run_records_are_rejected(self) -> None:
        correlator = Correlator([
            self._record("renderer", "ui.submit"),
            self._record("provider", "provider.dispatch", run_id="run_other"),
        ])
        with self.assertRaises(CorrelationError):
            correlator.require_single_execution("run_1")
        self.assertEqual(len(correlator.foreign_run_records("run_1")), 1)

    def test_4_records_without_ui_submission_are_disconnected(self) -> None:
        correlator = Correlator([
            self._record("provider", "provider.dispatch"),
            self._record("mutation", "mutation.receipt"),
        ])
        self.assertEqual(correlator.submitted_turns(), [])
        self.assertEqual(len(correlator.disconnected_records()), 2)

    def test_4b_shared_task_name_is_not_a_join_key(self) -> None:
        correlator = Correlator([
            self._record("renderer", "ui.submit", turn="t1"),
            self._record("provider", "provider.dispatch", turn="t2"),
        ])
        connected = correlator.records_for(("run_1", "s1", "t1"))
        self.assertEqual([rec["kind"] for rec in connected], ["ui.submit"])
        self.assertEqual(len(correlator.disconnected_records()), 1)

    def test_5_criteria_classification_is_three_state(self) -> None:
        correlator = Correlator([
            self._record("electron", "electron.launch"),
            self._record("electron", "electron.identity"),
            self._record("renderer", "cdp.version"),
        ])
        result = correlator.classify("run_1", {
            "electron": [("electron", "electron.launch"), ("electron", "electron.identity")],
            "cdp": [("renderer", "cdp.version"), ("renderer", "cdp.target")],
            "composer": [("renderer", "composer.inspect")],
        })
        self.assertEqual(result["electron"], "VERIFIED")
        self.assertEqual(result["cdp"], "PARTIALLY VERIFIED")
        self.assertEqual(result["composer"], "NOT VERIFIED")


class TestProviderBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="crusor_p0_6_4_prov_"))
        self.ctx = RunContext(self.tmp, run_id="run_prov")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_6_dispatch_record_requires_real_ids(self) -> None:
        incomplete = DispatchObservation(
            provider="custom", model="m", provider_request_id="",
            output_token_ceiling=512, reservation_id="res_1",
            turn_id="t1", session_id="s1",
        )
        with self.assertRaises(EvidenceIncomplete):
            record_dispatch(self.ctx, incomplete)

    def test_6b_complete_dispatch_record_is_written(self) -> None:
        record_dispatch(self.ctx, DispatchObservation(
            provider="custom", model="m", provider_request_id="req_1",
            output_token_ceiling=512, reservation_id="res_1",
            turn_id="t1", session_id="s1",
        ))
        records = self.ctx.read_ledger()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["provider_request_id"], "req_1")
        self.assertEqual(records[0]["reservation_id"], "res_1")

    def test_15_offline_preflight_computes_cost_without_dispatch(self) -> None:
        estimate = preflight_estimate(
            prompt="offline preflight only",
            provider="custom",
            model="z-ai/glm-5.3-flash",
            max_output_tokens=512,
            budget_inr=5.0,
        )
        self.assertIn("max_cost_inr", estimate)
        self.assertGreaterEqual(estimate["prompt_upper_bound_tokens"], 1)
        self.assertTrue(estimate["fits_budget"])
        self.assertEqual(self.ctx.read_ledger(), [])


class TestBridgeProbeGuard(unittest.TestCase):
    def test_7_every_provider_capable_frame_is_refused(self) -> None:
        for frame_type in sorted(PAID_FRAME_TYPES):
            with self.assertRaises(PaidCallRefused, msg=frame_type):
                assert_frame_is_offline({"type": frame_type, "text": "x"})
        self.assertIn("prompt", PAID_FRAME_TYPES)
        self.assertIn("oneshot", PAID_FRAME_TYPES)

    def test_8_only_the_offline_allowlist_is_accepted(self) -> None:
        for frame_type in sorted(PROBE_ALLOWED_FRAMES):
            assert_frame_is_offline({"type": frame_type})
        with self.assertRaises(PaidCallRefused):
            assert_frame_is_offline({"type": "cancel"})  # not on the allowlist
        self.assertNotIn("prompt", PROBE_ALLOWED_FRAMES)

    def test_16_prompt_correlation_is_a_hash_not_the_text(self) -> None:
        prompt = "Create a Python file named src/secret_task.py"
        digest = prompt_fingerprint(prompt)
        self.assertTrue(digest.startswith("sha256:"))
        self.assertNotIn("secret_task", digest)
        self.assertEqual(digest, prompt_fingerprint(prompt))


class TestCdpPrimitives(unittest.TestCase):
    def test_9_parse_targets_keeps_pages_only(self) -> None:
        payload = json.dumps([
            {"id": "p1", "type": "page", "title": "CrusorAI", "url": "vscode-file://x",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9333/devtools/page/p1"},
            {"id": "w1", "type": "worker", "title": "w", "url": "", "webSocketDebuggerUrl": "ws://x"},
        ])
        targets = parse_targets(payload)
        self.assertEqual([t.id for t in targets], ["p1"])

    def test_10_target_selection_prefers_workbench_page(self) -> None:
        payload = json.dumps([
            {"id": "ext", "type": "page", "title": "Extension", "url": "vscode-file://ext",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9333/devtools/page/ext"},
            {"id": "main", "type": "page", "title": "CrusorAI IDE",
             "url": "vscode-file://vscode-app/out/vs/code/electron-main/workbench.html",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9333/devtools/page/main"},
        ])
        target = pick_page_target(parse_targets(payload), prefer_title="CrusorAI")
        self.assertEqual(target.id, "main")

    def test_11_non_loopback_endpoint_is_refused(self) -> None:
        assert_loopback("ws://127.0.0.1:9333/devtools/page/x")
        with self.assertRaises(CdpError):
            assert_loopback("ws://10.0.0.5:9333/devtools/page/x")
        self.assertTrue(is_loopback_bind("127.0.0.1"))
        self.assertTrue(is_loopback_bind("::1"))
        self.assertFalse(is_loopback_bind("0.0.0.0"))
        self.assertFalse(is_loopback_bind("192.168.1.10"))

    def test_12_dom_expression_quotes_selector_safely(self) -> None:
        expression = build_dom_snapshot_expression("textarea.crusorai-composer-input")
        self.assertIn("textarea.crusorai-composer-input", expression)
        self.assertIn("querySelectorAll", expression)
        self.assertNotIn("require(", expression)
        tricky = build_dom_snapshot_expression("a'b\"c")
        self.assertIn(json.dumps("a'b\"c"), tricky)


class TestRendererIdentity(unittest.TestCase):
    def test_13_non_electron_page_is_rejected(self) -> None:
        ok, reason = page_belongs_to_crusor({
            "title": "CrusorAI — Chrome",
            "url": "https://example.com",
            "hasWorkbench": True,
            "isElectron": False,
            "bodyClasses": "",
        })
        self.assertFalse(ok)
        self.assertIn("Electron", reason)

    def test_13b_plain_web_workbench_is_rejected(self) -> None:
        ok, _ = page_belongs_to_crusor({
            "title": "CrusorAI",
            "url": "http://localhost:8080/",
            "hasWorkbench": True,
            "isElectron": True,
            "bodyClasses": "",
        })
        self.assertFalse(ok)

    def test_13c_real_electron_workbench_is_accepted(self) -> None:
        ok, reason = page_belongs_to_crusor({
            "title": "CrusorAI IDE",
            "url": "vscode-file://vscode-app/out/vs/code/electron-main/workbench.html",
            "hasWorkbench": True,
            "isElectron": True,
            "bodyClasses": "monaco-workbench",
        })
        self.assertTrue(ok)
        self.assertIn("Electron workbench", reason)


class TestInvariant7(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="crusor_p0_6_4_inv7_"))
        self.vscode = self.repo / "desktop" / "vscode"
        (self.vscode / "src" / "vs").mkdir(parents=True)
        declared = self.vscode / "build" / "buildfile.ts"
        declared.parent.mkdir(parents=True)
        declared.write_text("// overlay\n", encoding="utf-8")
        manifest = {
            "upstream_commit": "deadbeef",
            "custom_root": "src/vs/workbench/contrib/crusorai/",
            "files": {"build/buildfile.ts": {
                "overlay_sha256": sha256_file(declared),
                "modified": True,
            }},
        }
        (self.repo / "desktop" / "SELECTIVE_MANIFEST.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_14_matching_manifest_is_maintained(self) -> None:
        report = check_invariant7(self.repo, vscode_root=self.vscode)
        self.assertTrue(report.manifest_present)
        self.assertEqual(report.drift_files, [])
        self.assertTrue(report.maintained)

    def test_14b_drifted_declared_file_is_detected(self) -> None:
        (self.vscode / "build" / "buildfile.ts").write_text("// edited\n", encoding="utf-8")
        report = check_invariant7(self.repo, vscode_root=self.vscode)
        self.assertEqual(report.drift_files, ["build/buildfile.ts"])
        self.assertFalse(report.maintained)

    def test_14c_missing_manifest_is_not_maintained(self) -> None:
        (self.repo / "desktop" / "SELECTIVE_MANIFEST.json").unlink()
        report = check_invariant7(self.repo, vscode_root=self.vscode)
        self.assertFalse(report.maintained)
        self.assertFalse(report.manifest_present)

    def test_14d_git_status_paths_are_relativized_to_the_vscode_root(self) -> None:
        from benchmarks.crusor_desktop_acceptance.invariant7 import relativize

        prefix = "desktop/vscode/"
        self.assertEqual(
            relativize("desktop/vscode/out/main.js", prefix), "out/main.js"
        )
        self.assertEqual(relativize("out/main.js", prefix), "out/main.js")
        self.assertEqual(
            relativize("desktop/vscode\\out\\x.js", prefix), "out/x.js"
        )
        self.assertEqual(
            relativize("src/vs/other.ts", prefix), "src/vs/other.ts"
        )


class TestDevToolsDiscovery(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="crusor_p0_6_4_stderr_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_17_endpoint_is_read_from_the_apps_own_stderr(self) -> None:
        from benchmarks.crusor_desktop_acceptance.desktop_launcher import scan_stderr_for_devtools

        log = self.tmp / "electron.stderr.log"
        log.write_text(
            "noise\n"
            "DevTools listening on ws://127.0.0.1:9222/devtools/browser/abc-123\n"
            "[main] TypeError: boom\n",
            encoding="utf-8",
        )
        found = scan_stderr_for_devtools(log)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found["port"], 9222)
        self.assertEqual(found["host"], "127.0.0.1")
        self.assertTrue(found["loopback"])
        self.assertEqual(found["source"], "electron_stderr")
        self.assertIsNone(scan_stderr_for_devtools(self.tmp / "missing.log"))

    def test_18_crash_signature_extracts_fatal_lines(self) -> None:
        from benchmarks.crusor_desktop_acceptance.desktop_launcher import crash_signature

        log = self.tmp / "electron.stderr.log"
        log.write_text(
            "DevTools listening on ws://127.0.0.1:9222/x\n"
            "[main] TypeError: this._win.webContents.session.setProxy is not a function\n"
            "    at CodeWindow.onConfigurationUpdated\n",
            encoding="utf-8",
        )
        signature = crash_signature(log)
        self.assertTrue(signature["available"])
        self.assertTrue(any("setProxy" in line for line in signature["fatal_lines"]))
        self.assertFalse(crash_signature(self.tmp / "nope.log")["available"])

    def test_19_devtools_active_port_is_read_from_the_profile(self) -> None:
        from benchmarks.crusor_desktop_acceptance.desktop_launcher import read_devtools_active_port

        profile = self.tmp / "profile"
        profile.mkdir()
        (profile / "DevToolsActivePort").write_text(
            "9222\n/devtools/browser/abc\n", encoding="utf-8"
        )
        found = read_devtools_active_port(profile)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found["port"], 9222)
        self.assertEqual(found["source"], "DevToolsActivePort")
        self.assertIsNone(read_devtools_active_port(self.tmp / "no-profile"))


class TestCdpPortResolution(unittest.TestCase):
    """P0.6.4.1 — the forced 9222 port and its resolution."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="crusor_p0_6_4_1_port_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_21_dynamic_port_is_a_usable_loopback_port(self) -> None:
        from benchmarks.crusor_desktop_acceptance.desktop_launcher import allocate_loopback_port

        port = allocate_loopback_port()
        self.assertIsInstance(port, int)
        self.assertGreater(port, 0)
        self.assertLess(port, 65536)

    def test_22_portable_profile_names_the_requested_port(self) -> None:
        from benchmarks.crusor_desktop_acceptance.desktop_launcher import prepare_portable_profile

        portable = prepare_portable_profile(self.tmp / "portable", 51999)
        argv = json.loads((portable / "argv.json").read_text(encoding="utf-8"))
        self.assertEqual(argv["remote-debugging-port"], "51999")
        self.assertFalse(argv["enable-crash-reporter"])

    def test_22b_effective_user_data_dir_follows_portable_layout(self) -> None:
        from benchmarks.crusor_desktop_acceptance.desktop_launcher import LaunchedApp

        app = LaunchedApp(
            exe=Path("x"), pid=1, args=[], env_keys=[], workspace="w", port=1,
            user_data_dir=r"C:\ignored", started_at=0.0, portable_dir=r"C:\port",
        )
        self.assertEqual(app.effective_user_data_dir, str(Path(r"C:\port") / "user-data"))
        app.portable_dir = ""
        self.assertEqual(app.effective_user_data_dir, r"C:\ignored")

    def test_23_user_argv_override_is_reported_not_mutated(self) -> None:
        from benchmarks.crusor_desktop_acceptance.desktop_launcher import read_argv_config_override

        before = read_argv_config_override()
        after = read_argv_config_override()
        self.assertEqual(before, after, "reading the user's argv.json must not mutate it")
        self.assertTrue(before["candidates"])
        for candidate in before["candidates"]:
            self.assertIn("argv.json", candidate)
        if "content" in before and isinstance(before["content"], dict):
            # The dev profile is the one VS Code reads under VSCODE_DEV.
            self.assertIn("remote-debugging-port", before["content"])


class TestLaunchEnvironment(unittest.TestCase):
    def test_20_launch_env_scrubs_proxy_and_ipc_vars(self) -> None:
        import os

        from benchmarks.crusor_desktop_acceptance.desktop_launcher import build_launch_environment

        injected = {
            "NO_PROXY": "127.0.0.1,localhost",
            "HTTP_PROXY": "http://proxy.invalid:8080",
            "ELECTRON_RUN_AS_NODE": "1",
            "VSCODE_PID": "4242",
        }
        saved = {key: os.environ.get(key) for key in injected}
        os.environ.update(injected)
        try:
            env = build_launch_environment(user_data_dir="unused")
            for key in injected:
                self.assertNotIn(key, env, f"{key} must not reach the desktop app")
            self.assertEqual(env["VSCODE_DEV"], "1")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
