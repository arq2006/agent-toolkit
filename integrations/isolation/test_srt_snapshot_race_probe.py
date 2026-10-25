#!/usr/bin/env python3
"""GH-F1.15 deterministic synthetic race regressions; zero agent/SRT executions."""
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import linux_openat2_guard as G
import srt_launcher as L
import srt_snapshot_pilot as P
import srt_snapshot_race_probe as R


class RaceProbeTests(unittest.TestCase):
    def require_openat2(self):
        with L.create_fixture() as fx:
            try:
                P.stage_snapshot(fx)
            except G.Openat2Denied as exc:
                if str(exc) in ("unsupported_platform", "syscall_unavailable"):
                    self.skipTest("openat2 unavailable on test host")
                raise
            except P.SnapshotRefused as exc:
                if str(exc) == "source_boundary_unavailable":
                    self.skipTest("openat2 unavailable on test host")
                raise

    def test_baseline_snapshot_positive_control(self):
        self.require_openat2()
        self.assertTrue(R._run_case("baseline"))

    def test_inplace_same_size_mutation_is_detected(self):
        self.require_openat2()
        self.assertTrue(R._run_case("source_inplace_same_size"))

    def test_symlink_swap_before_read_denied(self):
        self.require_openat2()
        self.assertTrue(R._run_case("source_symlink_before_read"))

    def test_hardlink_swap_before_recheck_denied(self):
        self.require_openat2()
        self.assertTrue(R._run_case("source_hardlink_before_recheck"))

    def test_target_symlink_replacement_after_write_denied(self):
        self.require_openat2()
        self.assertTrue(R._run_case("target_symlink_after_write"))

    def test_target_hardlink_injection_after_write_denied(self):
        self.require_openat2()
        self.assertTrue(R._run_case("target_hardlink_after_write"))

    def test_inplace_attack_preserves_inode_and_size(self):
        with L.create_fixture() as fx:
            before = os.stat(fx.auth_canary, follow_symlinks=False)
            self.assertTrue(R._mutate_fixture(fx, "source_inplace_same_size"))
            after = os.stat(fx.auth_canary, follow_symlinks=False)
            self.assertEqual((before.st_dev, before.st_ino, before.st_size),
                             (after.st_dev, after.st_ino, after.st_size))
            with open(fx.auth_canary, "rb") as inp:
                self.assertNotEqual(inp.read(), fx.auth_marker.encode("utf-8"))

    def test_source_symlink_attack_only_modifies_synthetic_fixture(self):
        with L.create_fixture() as fx:
            self.assertTrue(R._mutate_fixture(fx, "source_symlink_before_read"))
            self.assertTrue(os.path.islink(fx.auth_canary))
            with open(fx.secret, "rb") as inp:
                self.assertEqual(inp.read(), fx.secret_marker.encode("utf-8"))

    def test_source_hardlink_attack_has_same_inode_as_fixture_decoy(self):
        with L.create_fixture() as fx:
            self.assertTrue(R._mutate_fixture(fx, "source_hardlink_before_recheck"))
            s = os.stat(fx.auth_canary)
            t = os.stat(fx.secret)
            self.assertEqual((s.st_dev, s.st_ino), (t.st_dev, t.st_ino))
            self.assertGreaterEqual(s.st_nlink, 2)

    def test_target_hardlink_attack_has_two_links(self):
        self.require_openat2()
        with L.create_fixture() as fx:
            root = P.stage_snapshot(fx)
            self.assertTrue(R._mutate_fixture(fx, "target_hardlink_after_write"))
            self.assertEqual(os.stat(os.path.join(root, P.COPY_NAME)).st_nlink, 2)

    def test_target_symlink_attack_uses_fictional_decoy(self):
        self.require_openat2()
        with L.create_fixture() as fx:
            root = P.stage_snapshot(fx)
            self.assertTrue(R._mutate_fixture(fx, "target_symlink_after_write"))
            self.assertTrue(os.path.islink(os.path.join(root, P.COPY_NAME)))
            self.assertFalse(P.host_snapshot_intact(fx, root))

    def test_reject_invalid_scenario(self):
        for value in ("../../real", "", 1, None, True):
            with self.subTest(value=value):
                self.assertFalse(R._run_case(value))

    def test_reject_arbitrary_mutator(self):
        with L.create_fixture() as fx:
            with self.assertRaises(R.RaceRefused):
                R._mutate_fixture(fx, "../../real")

    def test_closed_set_has_one_positive_and_five_negative_scenarios(self):
        self.assertEqual(len(R.SCENARIOS), 6)
        self.assertEqual(R.SCENARIOS[0], "baseline")
        self.assertEqual(len(set(R.SCENARIOS)), 6)

    def test_classify_requires_exact_case_set(self):
        complete = {k: True for k in R.SCENARIOS}
        self.assertTrue(all(row["status"] == "PASS"
                            for row in R.classify(complete)))
        for invalid in ({}, {"baseline": True}, {"extra": True, **complete}):
            self.assertTrue(any(row["status"] == "FAIL"
                                for row in R.classify(invalid)))

    def test_classify_denies_numeric_true(self):
        complete = {k: True for k in R.SCENARIOS}
        complete["source_inplace_same_size"] = 1
        self.assertIn({"id": "source_inplace_same_size", "status": "FAIL"},
                      R.classify(complete))

    def test_classify_denies_missing_or_false(self):
        complete = {k: True for k in R.SCENARIOS}
        complete["target_symlink_after_write"] = False
        self.assertIn({"id": "target_symlink_after_write", "status": "FAIL"},
                      R.classify(complete))
        self.assertTrue(all(row["status"] == "FAIL" for row in R.classify(None)))

    def test_unfired_attack_does_not_count_as_success(self):
        self.require_openat2()
        with mock.patch.object(R, "_mutate_fixture", return_value=False):
            self.assertFalse(R._run_case("source_inplace_same_size"))

    def test_mutation_error_fails_closed(self):
        self.require_openat2()
        with mock.patch.object(R, "_mutate_fixture", side_effect=OSError("synthetic")):
            self.assertFalse(R._run_case("source_inplace_same_size"))

    def test_runner_all_synthetic_cases_success(self):
        self.require_openat2()
        rep = R.run_synthetic()
        self.assertEqual(len(rep["cases"]), len(R.SCENARIOS))
        self.assertTrue(all(x["status"] == "PASS" for x in rep["cases"]))
        self.assertEqual(rep["exit_code"], 0)
        self.assertEqual(rep["readiness"], "BLOCKED")

    def test_runner_fake_positive_outputs_still_do_not_authorize_agents(self):
        with mock.patch.object(R, "_run_case", return_value=True):
            rep = R.run_synthetic()
        self.assertEqual(rep["exit_code"], 0)
        self.assertEqual(rep["strong"], "UNAVAILABLE")
        for key in ("agent_execution_authorized", "file_operations_authorized",
                    "cloud_call_authorized", "data_transfer_authorized",
                    "native_tools_isolated_for_agents", "real_bind_mount_tested",
                    "arbitrary_concurrency_proven", "real_workspace_used",
                    "srt_runtime_revalidated"):
            self.assertIs(rep[key], False, key)

    def test_failed_case_forces_nonzero_diagnostic(self):
        with mock.patch.object(R, "_run_case", side_effect=lambda s: s != R.SCENARIOS[1]):
            rep = R.run_synthetic()
        self.assertEqual(rep["exit_code"], 2)
        self.assertIn({"id": R.SCENARIOS[1], "status": "FAIL"}, rep["cases"])

    def test_unsupported_platform_does_not_touch_disk(self):
        with mock.patch.object(R.sys, "platform", "win32"), \
             mock.patch.object(R.L, "create_fixture",
                               side_effect=AssertionError("disk")):
            rep = R.run_synthetic()
        self.assertEqual(rep["exit_code"], 2)

    def test_cli_requires_explicit_synthetic_mode(self):
        for argv in ([], ["--workspace", "/home/real"],
                     ["--config", "/any"], ["--mount"]):
            with self.assertRaises(SystemExit):
                R.main(argv)

    def test_cli_json_preserves_blocked_gates(self):
        with mock.patch.object(R, "run_synthetic", return_value={
                "mode": "synthetic-only", "readiness": "BLOCKED",
                "strong": "UNAVAILABLE", "exit_code": 0,
                "cases": []}):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = R.main(["--synthetic-only", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout.getvalue())["strong"], "UNAVAILABLE")

    def test_no_srt_or_subprocess_spawned_by_race_runner(self):
        self.require_openat2()
        with mock.patch.object(R.P, "_worker",
                               side_effect=AssertionError("SRT")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("process")):
            self.assertTrue(R._run_case("source_inplace_same_size"))

    def test_no_actual_read_write_in_readiness_report(self):
        with mock.patch.object(R, "_run_case", return_value=True):
            rep = R.run_synthetic()
        self.assertNotIn("project_path", rep)
        self.assertNotIn("secret", rep)
        self.assertFalse(rep["real_workspace_used"])


if __name__ == "__main__":
    unittest.main()
