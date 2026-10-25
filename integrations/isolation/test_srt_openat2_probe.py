#!/usr/bin/env python3
"""Tests synthetic SRT openat2 probe; never requests mounts or real agents."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import fakes
import srt_launcher as L
import srt_readonly_pilot as R
import srt_openat2_probe as P


class SrtOpenat2ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="srt-openat2-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def fake(self, mode="validate"):
        return fakes.make_fake_deps(self.tmp, mode)

    def test_stages_only_guard_in_fictional_root(self):
        with L.create_fixture() as fx:
            root = R.stage_fixture(fx)
            P.stage_guard(root)
            self.assertTrue(root.startswith(fx.authorized + os.sep))
            self.assertTrue(os.path.isfile(os.path.join(root, P.GUARD_FILE)))
            self.assertEqual(sorted(os.listdir(fx.external)),
                             ["secret.txt", "writable_target.txt"])

    def test_classification_requires_kernel_and_srt_controls(self):
        r = {
            "inside": {"ok": True, "text": "MARKER"},
            "list": {"ok": True, "entries": ["sample.txt", P.GUARD_FILE]},
            "symlink": {"ok": False, "code": "path_denied"},
            "hardlink": {"ok": False, "code": "unsafe_file"},
            "traversal": {"ok": False, "code": "invalid_path"},
            "absolute": {"ok": False, "code": "invalid_path"},
            "native_external_blocked": True,
            "native_write_blocked": True,
        }
        checks = P.classify(r, "MARKER")
        self.assertEqual(len(checks), 9)
        self.assertTrue(all(x["status"] == "PASS" for x in checks))
        for key in ("native_external_blocked", "native_write_blocked"):
            bad = dict(r)
            bad[key] = False
            self.assertTrue(any(c["status"] == "FAIL" for c in P.classify(bad, "MARKER")))
        self.assertEqual(P.classify(None, "MARKER"),
                         [{"id": "worker_executed", "status": "FAIL"}])

    def test_fake_runtime_without_isolation_cannot_pass(self):
        report = P.run_synthetic(deps=self.fake("validate"), timeout=20)
        self.assertEqual(report["exit_code"], 2)
        self.assertFalse(report["agent_execution_authorized"])
        self.assertEqual(report["strong"], "UNAVAILABLE")
        self.assertEqual(report["file_operations"], "BLOCKED_FOR_AGENTS")
        self.assertEqual(report["bind_mount_test"],
                         "NOT_TESTED_REQUIRES_ISOLATED_MOUNT_NAMESPACE")

    def test_fake_runtime_ignoring_settings_cannot_pass(self):
        report = P.run_synthetic(deps=self.fake("ignore_settings_ok"), timeout=20)
        self.assertEqual(report["exit_code"], 2)
        self.assertFalse(report["agent_execution_authorized"])

    def test_spoofed_nonce_rejected(self):
        with L.create_fixture() as fx:
            root = R.stage_fixture(fx)
            def spoof(argv, env, cwd, timeout):
                return 0, json.dumps({
                    "nonce": "wrong", "results": {"inside": {"ok": True}}}).encode(), b"", False
            with mock.patch.object(L, "_spawn", side_effect=spoof):
                self.assertIsNone(P._run_worker(self.fake(), fx, root, 5))

    def test_json_recursion_and_timeout_fail_closed(self):
        with L.create_fixture() as fx:
            root = R.stage_fixture(fx)
            deep = ("[" * 1500 + "0" + "]" * 1500 + "\n").encode()
            for response in ((0, deep, b"", False), (0, b"", b"", True),
                             (1, b"{}", b"", False)):
                with mock.patch.object(L, "_spawn", return_value=response):
                    self.assertIsNone(P._run_worker(self.fake(), fx, root, 5))

    def test_worker_invocation_fixed_without_agent_or_secrets(self):
        with L.create_fixture() as fx:
            root = R.stage_fixture(fx)
            seen = []
            def spy(argv, env, cwd, timeout):
                seen.append((argv, env, cwd, timeout))
                payload = json.loads(argv[-1])
                return 0, json.dumps({"nonce": payload["nonce"], "results": {}}).encode(), b"", False
            with mock.patch.object(L, "_spawn", side_effect=spy):
                self.assertEqual(P._run_worker(self.fake(), fx, root, 5), {})
            argv, env, cwd, timeout = seen[0]
            self.assertEqual(argv[1], "--settings")
            self.assertEqual(argv[3:8], ["--", L.INTERPRETER, "-I", "-B", "-c"])
            self.assertEqual(argv[8], P.WORKER_SRC)
            self.assertEqual(cwd, root)
            for key in ("ANTHROPIC_API_KEY", "SSH_AUTH_SOCK", "LD_PRELOAD"):
                self.assertNotIn(key, env)

    def test_invalid_platform_never_runs(self):
        with mock.patch.object(P.sys, "platform", "darwin"):
            with mock.patch.object(L, "_spawn", side_effect=AssertionError("spawn")):
                rep = P.run_synthetic(self.fake(), timeout=5)
        self.assertEqual(rep["exit_code"], 2)

    def test_invalid_timeout_rejected(self):
        for val in (0, 121, True, -3, "5"):
            with mock.patch.object(L, "_spawn", side_effect=AssertionError("spawn")):
                rep = P.run_synthetic(self.fake(), timeout=val)
            self.assertEqual(rep["exit_code"], 2)

    def test_cli_requires_explicit_synthetic_only(self):
        with self.assertRaises(SystemExit):
            P.main([])
        with self.assertRaises(SystemExit):
            P.main(["--config", "/home/user"])
        report = {"mode": "synthetic-only", "strong": "UNAVAILABLE",
                  "agent_execution_authorized": False, "checks": [], "exit_code": 2}
        with mock.patch.object(P, "run_synthetic", return_value=report):
            self.assertEqual(P.main(["--synthetic-only"]), 2)


if __name__ == "__main__":
    unittest.main()
