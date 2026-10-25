#!/usr/bin/env python3
"""Testes do piloto offline: todos os dados são sintéticos; SRT real não é iniciado."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import fakes
import pathguard
import srt_launcher as L
import srt_readonly_pilot as P


class SyntheticPilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="srt-ro-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def fake(self, mode="validate"):
        return fakes.make_fake_deps(self.tmp, mode)

    def test_stage_uses_private_synthetic_directory_and_no_indirect_links(self):
        with L.create_fixture() as fx:
            root = P.stage_fixture(fx)
            self.assertTrue(root.startswith(fx.authorized + os.sep))
            self.assertEqual(oct(os.stat(root).st_mode & 0o777), "0o700")
            self.assertTrue(os.path.isfile(os.path.join(root, "readonly_executor.py")))
            self.assertTrue(os.path.isfile(os.path.join(root, "pathguard.py")))
            self.assertTrue(P.existing_files_intact(root, fx.auth_marker))
            fd = pathguard.open_root(root)
            try:
                self.assertEqual(pathguard.scan_tree(fd), [])
            finally:
                os.close(fd)

    def test_policy_restricts_read_network_and_all_writes(self):
        with L.create_fixture() as fx:
            root = P.stage_fixture(fx)
            reads = ["/usr", "/etc/ld.so.cache", "/fake/vendor/seccomp/x64/apply-seccomp"]
            settings = P.build_readonly_settings(root, reads)
            self.assertEqual(settings["filesystem"]["denyRead"], ["/"])
            self.assertEqual(settings["filesystem"]["allowRead"], [root, *reads])
            self.assertEqual(settings["filesystem"]["allowWrite"], [])
            self.assertEqual(settings["filesystem"]["denyWrite"], [])
            self.assertEqual(settings["network"]["allowedDomains"], [])
            self.assertFalse(settings["network"]["allowAllUnixSockets"])
            self.assertFalse(settings["enableWeakerNestedSandbox"])
            self.assertFalse(settings["allowNestedUserNamespaces"])

    def test_allowlist_is_not_configurable(self):
        with L.create_fixture() as fx:
            root = P.stage_fixture(fx)
            settings = P.build_readonly_settings(root, ["/usr"])
            self.assertEqual(settings["network"]["allowedDomains"], [])
            self.assertEqual(settings["filesystem"]["allowWrite"], [])

    def test_invalid_worker_suite_refused_before_spawn(self):
        with L.create_fixture() as fx:
            root = P.stage_fixture(fx)
            with mock.patch.object(L, "_spawn", side_effect=AssertionError("spawn chamado")):
                with self.assertRaises(P.SyntheticPilotError):
                    P._worker(self.fake(), fx, root, "agent", timeout=5)

    def test_worker_invocation_is_fixed_and_minimal(self):
        deps = self.fake()
        with L.create_fixture() as fx:
            root = P.stage_fixture(fx)
            seen = []

            def fake_spawn(argv, env, cwd, timeout):
                seen.append((argv, env, cwd, timeout))
                payload = json.loads(argv[-1])
                message = json.dumps({"nonce": payload["nonce"], "suite": payload["suite"],
                                      "results": {"dummy": 1}})
                return 0, message.encode(), b"", False

            with mock.patch.object(L, "_spawn", side_effect=fake_spawn):
                result = P._worker(deps, fx, root, "baseline", timeout=5)
            self.assertEqual(result, {"dummy": 1})
            argv, env, cwd, timeout = seen[0]
            self.assertEqual(argv[0:2], [deps.get("srt").path, "--settings"])
            self.assertEqual(argv[2], fx.settings_path)
            self.assertEqual(argv[3:8], ["--", L.INTERPRETER, "-I", "-B", "-c"])
            self.assertEqual(argv[8], P.WORKER_SRC)
            self.assertEqual(cwd, root)
            for var in ("ANTHROPIC_API_KEY", "SSH_AUTH_SOCK", "LD_PRELOAD", "NODE_OPTIONS"):
                self.assertNotIn(var, env)
            self.assertNotIn("claude", repr(argv[:8]).lower())

    def test_spoofed_nonce_rejected(self):
        with L.create_fixture() as fx:
            root = P.stage_fixture(fx)
            def spoof(argv, env, cwd, timeout):
                msg = {"nonce": "spoofed", "suite": "baseline", "results": {"read_inside": True}}
                return 0, json.dumps(msg).encode(), b"", False
            with mock.patch.object(L, "_spawn", side_effect=spoof):
                self.assertIsNone(P._worker(self.fake(), fx, root, "baseline", 5))

    def test_nonzero_and_timeout_rejected(self):
        with L.create_fixture() as fx:
            root = P.stage_fixture(fx)
            for r in ((1, b"", b"denied", False), (0, b"", b"", True)):
                with mock.patch.object(L, "_spawn", return_value=r):
                    self.assertIsNone(P._worker(self.fake(), fx, root, "baseline", 5))

    def test_classification_requires_positive_controls(self):
        checks = P.classify(None, None, "fictional")
        self.assertEqual(checks, [{"id": "baseline_executed", "status": "FAIL"}])
        baseline = {
            "read_inside": {"ok": True, "response": {"ok": True, "op":"read", "text":"fictional"}},
            "list_inside": {"ok": True, "response": {"entries": ["sample.txt","pathguard.py","readonly_executor.py"]}},
            "reject_traversal": {"ok": False, "code":"invalid_path"},
            "reject_absolute": {"ok": False, "code":"invalid_path"},
            "reject_write_request": {"ok": False, "code":"operation_denied"},
            "native_external_read": {"opened": False},
            "native_write_denied": True,
            "native_existing_overwrite_denied": True,
            "native_existing_truncate_denied": True,
        }
        hardlink = {
            "hardlink_denied": {"ok": False, "code": "unsafe_tree"},
            "normal_read_denied_with_hardlink": {"ok": False, "code": "unsafe_tree"},
            "native_hardlink": {"opened": True, "matched": True},
        }
        self.assertTrue(all(c["status"] == "PASS" for c in P.classify(baseline, hardlink, "fictional", host_intact=True)))
        for key in ("native_write_denied", "native_external_read"):
            broken = dict(baseline)
            broken[key] = False if key == "native_write_denied" else {"opened": True}
            self.assertTrue(any(c["status"] == "FAIL" for c in P.classify(broken, hardlink, "fictional", host_intact=True)))
        broken = dict(hardlink)
        broken["hardlink_denied"] = {"ok": True}
        self.assertTrue(any(c["status"] == "FAIL" for c in P.classify(baseline, broken, "fictional", host_intact=True)))

    def test_malformed_canary_results_fail_closed(self):
        bads = (
            {"read_inside": None, "list_inside": True},
            {"read_inside": {"ok": True, "response": "not-a-dict"},
             "list_inside": {"ok": True, "response": 123}},
            {"read_inside": {"ok": True, "response": {"ok": True, "op": "read", "text": "x"}},
             "list_inside": {"ok": True, "response": {"entries": "wrong-type"}}},
        )
        for baseline in bads:
            checks = P.classify(baseline, {"hardlink_denied": None,
                        "normal_read_denied_with_hardlink": 123, "native_hardlink": []}, "x")
            self.assertTrue(any(c["status"] == "FAIL" for c in checks))

    def test_native_hardlink_inconsistent_fails_closed(self):
        baseline = {
            "read_inside": {"ok": True, "response": {"ok": True, "op": "read", "text": "x"}},
            "list_inside": {"ok": True, "response": {"entries": [
                "sample.txt", "pathguard.py", "readonly_executor.py"]}},
            "reject_traversal": {"ok": False, "code": "invalid_path"},
            "reject_absolute": {"ok": False, "code": "invalid_path"},
            "reject_write_request": {"ok": False, "code": "operation_denied"},
            "native_external_read": {"opened": False},
            "native_write_denied": True,
            "native_existing_overwrite_denied": True,
            "native_existing_truncate_denied": True,
        }
        hardlink = {
            "hardlink_denied": {"ok": False, "code": "unsafe_tree"},
            "normal_read_denied_with_hardlink": {"ok": False, "code": "unsafe_tree"},
            "native_hardlink": {"opened": True, "matched": False},
        }
        checks = {c["id"]: c["status"] for c in P.classify(baseline, hardlink, "x", host_intact=True)}
        self.assertEqual(checks["native_hardlink_result_consistent"], "FAIL")

    def test_recursion_error_from_worker_json_is_fail_closed(self):
        # Mesmo se o JSON puder ser lido em bytes, um aninhamento excessivo
        # precisa virar None/código 2, e não traceback/código 1.
        with L.create_fixture() as fx:
            root = P.stage_fixture(fx)
            deep = ("[" * 1600 + "0" + "]" * 1600 + "\n").encode()
            with mock.patch.object(L, "_spawn", return_value=(0, deep, b"", False)):
                self.assertIsNone(P._worker(self.fake(), fx, root, "baseline", 5))
            with mock.patch.object(P.json, "loads", side_effect=RecursionError("deep")):
                with mock.patch.object(L, "_spawn", return_value=(0, b"{}", b"", False)):
                    self.assertIsNone(P._worker(self.fake(), fx, root, "baseline", 5))

    def test_supervisor_rejects_overwrite_and_truncation_of_existing_files(self):
        for name, _suffix in P.EXISTING_WRITE_FILES:
            with L.create_fixture() as fx:
                root = P.stage_fixture(fx)
                self.assertTrue(P.existing_files_intact(root, fx.auth_marker))
                with open(os.path.join(root, name), "wb") as file:
                    if "overwrite" in name:
                        file.write(b"MODIFIED-BY-TEST")
                    # No caso de truncamento, abertura em wb ja removeu bytes.
                self.assertFalse(P.existing_files_intact(root, fx.auth_marker))

    def test_new_file_denial_does_not_prove_existing_files_immutable(self):
        baseline = {
            "read_inside": {"ok": True, "response": {
                "ok": True, "op": "read", "text": "fixture"}},
            "list_inside": {"ok": True, "response": {"entries": [
                "sample.txt", "pathguard.py", "readonly_executor.py"]}},
            "reject_traversal": {"ok": False, "code": "invalid_path"},
            "reject_absolute": {"ok": False, "code": "invalid_path"},
            "reject_write_request": {"ok": False, "code": "operation_denied"},
            "native_external_read": {"opened": False},
            "native_write_denied": True,
            "native_existing_overwrite_denied": True,
            "native_existing_truncate_denied": True,
        }
        hardlink = {
            "hardlink_denied": {"ok": False, "code": "unsafe_tree"},
            "normal_read_denied_with_hardlink": {"ok": False, "code": "unsafe_tree"},
            "native_hardlink": {"opened": True, "matched": True},
        }
        def statuses(baseline_value, host_intact=True):
            return {c["id"]: c["status"] for c in P.classify(
                baseline_value, hardlink, "fixture", host_intact=host_intact)}
        self.assertTrue(all(x == "PASS" for x in statuses(baseline).values()))
        for key, failed_id in (
            ("native_existing_overwrite_denied", "native_existing_overwrite_blocked"),
            ("native_existing_truncate_denied", "native_existing_truncate_blocked"),
        ):
            bypass = dict(baseline)
            bypass[key] = False
            self.assertEqual(statuses(bypass)[failed_id], "FAIL")
        self.assertEqual(statuses(baseline, host_intact=False)[
            "host_existing_files_intact"], "FAIL")

    def test_fake_srt_without_isolation_must_fail(self):
        # Fake valida JSON mas executa o processo diretamente. NUNCA PASS.
        result = P.run_synthetic(deps=self.fake("validate"), timeout=20)
        self.assertEqual(result["exit_code"], 2)
        self.assertFalse(result["agent_execution_authorized"])
        self.assertEqual(result["strong"], "UNAVAILABLE")
        self.assertEqual(result["file_operations"], "BLOCKED_FOR_AGENTS")
        checks = {c["id"]: c["status"] for c in result["checks"]}
        self.assertEqual(checks.get("authorized_read"), "PASS")
        self.assertEqual(checks.get("native_write_blocked"), "FAIL")
        self.assertEqual(checks.get("native_existing_overwrite_blocked"), "FAIL")
        self.assertEqual(checks.get("native_existing_truncate_blocked"), "FAIL")
        self.assertEqual(checks.get("host_existing_files_intact"), "FAIL")
        self.assertEqual(checks.get("native_external_read_blocked"), "FAIL")

    def test_fake_srt_ignoring_policy_must_fail(self):
        result = P.run_synthetic(deps=self.fake("ignore_settings_ok"), timeout=20)
        self.assertEqual(result["exit_code"], 2)
        self.assertFalse(result["agent_execution_authorized"])

    def test_wrong_platform_never_launches(self):
        with mock.patch.object(P.sys, "platform", "darwin"):
            with mock.patch.object(L, "_spawn", side_effect=AssertionError("nunca deve iniciar")):
                report = P.run_synthetic(deps=self.fake())
        self.assertEqual(report["exit_code"], 2)
        self.assertFalse(report["agent_execution_authorized"])

    def test_cli_requires_explicit_synthetic_only(self):
        with self.assertRaises(SystemExit):
            P.main([])
        with self.assertRaises(SystemExit):
            P.main(["--config", "/home/user"])
        with mock.patch.object(P, "run_synthetic", return_value={
            "mode":"synthetic-only","strong":"UNAVAILABLE","file_operations":"BLOCKED_FOR_AGENTS",
            "agent_execution_authorized":False,"checks":[],"native_hardlink_limitation":"NOT_TESTED",
            "exit_code":2
        }):
            self.assertEqual(P.main(["--synthetic-only"]), 2)


if __name__ == "__main__":
    unittest.main()
