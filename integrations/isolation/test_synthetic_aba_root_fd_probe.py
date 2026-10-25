#!/usr/bin/env python3
"""GH-F1.16 synthetic ABA and pinned root-FD regression tests (no real agents)."""
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

import linux_openat2_guard as G
import pathguard
import srt_launcher as L
import synthetic_aba_root_fd_probe as P


class RootFdAbaTests(unittest.TestCase):
    def require_openat2(self):
        with L.create_fixture() as fx:
            fd = pathguard.open_root(fx.authorized)
            try:
                try:
                    self.assertEqual(G.read_bytes(fd, "canary_read.txt"),
                                     fx.auth_marker.encode("utf-8"))
                except G.Openat2Denied as exc:
                    if str(exc) in ("unsupported_platform", "syscall_unavailable"):
                        self.skipTest("openat2 unavailable on host")
                    raise
            finally:
                os.close(fd)

    def test_baseline_root_fd_matches_named_fixture(self):
        self.assertEqual(P._fd_baseline(), "BOUND")

    def test_foreign_fd_does_not_match_fixture_root(self):
        self.assertEqual(P._fd_foreign(), "REJECTED")

    def test_detached_pinned_fd_is_detected_while_it_remains_readable(self):
        self.require_openat2()
        self.assertEqual(P._fd_path_replaced(), "STALE_FD_DETECTED")

    def test_aba_write_restore_between_guarded_reads_remains_undetected(self):
        self.require_openat2()
        self.assertEqual(P._aba_reversion(), "ABA_UNDETECTED")

    def test_open_root_fd_accepted_only_for_matching_fixture(self):
        with L.create_fixture() as fx:
            fd = pathguard.open_root(fx.authorized)
            try:
                self.assertTrue(P._root_path_binding_matches(fx, fd))
            finally:
                os.close(fd)

    def test_duplicate_fd_identity_remains_same(self):
        with L.create_fixture() as fx:
            fd = pathguard.open_root(fx.authorized)
            copy = os.dup(fd)
            try:
                self.assertTrue(P._root_path_binding_matches(fx, copy))
            finally:
                os.close(copy)
                os.close(fd)

    def test_unrelated_fixture_fd_rejected(self):
        with L.create_fixture() as a, L.create_fixture() as b:
            fd = pathguard.open_root(a.authorized)
            try:
                self.assertFalse(P._root_path_binding_matches(b, fd))
            finally:
                os.close(fd)

    def test_directory_fd_to_external_fixture_rejected(self):
        with L.create_fixture() as fx:
            fd = pathguard.open_root(fx.external)
            try:
                self.assertFalse(P._root_path_binding_matches(fx, fd))
            finally:
                os.close(fd)

    def test_regular_file_descriptor_rejected(self):
        with L.create_fixture() as fx:
            fd = os.open(fx.auth_canary, os.O_RDONLY)
            try:
                self.assertFalse(P._root_path_binding_matches(fx, fd))
            finally:
                os.close(fd)

    def test_closed_descriptor_rejected(self):
        with L.create_fixture() as fx:
            fd = pathguard.open_root(fx.authorized)
            os.close(fd)
            self.assertFalse(P._root_path_binding_matches(fx, fd))

    def test_invalid_fd_types_fail_closed(self):
        with L.create_fixture() as fx:
            for invalid in (-1, None, True, False, "3", 1.0, object()):
                with self.subTest(invalid=repr(invalid)):
                    self.assertFalse(P._root_path_binding_matches(fx, invalid))

    def test_nonfixture_cannot_be_used_as_owner_evidence(self):
        with self.subTest("ordinary_dictionary"):
            self.assertFalse(P._root_path_binding_matches({"authorized": "/tmp"}, 0))
        self.assertFalse(P._root_path_binding_matches(None, 0))

    def test_symlink_rebind_does_not_make_original_fd_match(self):
        with L.create_fixture() as fx:
            fd = pathguard.open_root(fx.authorized)
            try:
                os.rename(fx.authorized,
                          os.path.join(fx.root, "old-authorized-synthetic"))
                os.symlink(fx.external, fx.authorized)
                self.assertFalse(P._root_path_binding_matches(fx, fd))
            finally:
                os.close(fd)

    def test_path_disappears_while_old_fd_stays_valid(self):
        with L.create_fixture() as fx:
            fd = pathguard.open_root(fx.authorized)
            try:
                os.rename(fx.authorized,
                          os.path.join(fx.root, "old-authorized-synthetic"))
                self.assertFalse(P._root_path_binding_matches(fx, fd))
                self.assertGreaterEqual(os.fstat(fd).st_nlink, 1)
            finally:
                os.close(fd)

    def test_closed_case_catalog_has_four_unique_cases(self):
        self.assertEqual(len(P.EXPECTED), 4)
        self.assertEqual(set(P.EXPECTED), set(P.CASES))
        self.assertEqual(P.EXPECTED["aba_reverted_between_reads"], "ABA_UNDETECTED")

    def test_classify_all_exact_observations(self):
        observations = P.classify(dict(P.EXPECTED))
        self.assertEqual(len(observations), len(P.EXPECTED))
        self.assertEqual([x["id"] for x in observations], list(P.EXPECTED))
        self.assertTrue(all(x["observation"] != "NOT_VERIFIED" for x in observations))

    def test_classify_observations_has_stable_catalog_order(self):
        reversed_observations = dict(reversed(list(P.EXPECTED.items())))
        self.assertEqual(P.classify(reversed_observations),
                         P.classify(dict(P.EXPECTED)))

    def test_classify_rejects_missing_or_extra_cases(self):
        for sample in ({}, {"root_fd_baseline": "BOUND"},
                       dict(P.EXPECTED, unexpected="BOUND")):
            with self.subTest(sample=str(sample)):
                observations = P.classify(sample)
                self.assertTrue(all(x["observation"] == "NOT_VERIFIED"
                                    for x in observations))

    def test_classify_rejects_non_dict_reports(self):
        for sample in (None, True, False, [], "report", 1):
            with self.subTest(sample=repr(sample)):
                self.assertTrue(all(x["observation"] == "NOT_VERIFIED"
                                    for x in P.classify(sample)))

    def test_classify_rejects_boolean_and_numeric_impersonation(self):
        for value in (True, 1, 1.0, None, "ABA_UNDETECTED ", "SAFE"):
            with self.subTest(value=repr(value)):
                example = dict(P.EXPECTED)
                example["aba_reverted_between_reads"] = value
                self.assertIn(
                    {"id": "aba_reverted_between_reads",
                     "observation": "NOT_VERIFIED"}, P.classify(example))

    def test_no_srt_execution_in_diagnostic(self):
        self.require_openat2()
        with mock.patch("subprocess.Popen",
                        side_effect=AssertionError("external process")), \
             mock.patch.object(P.L, "_spawn",
                               side_effect=AssertionError("SRT process")):
            result = P.run_synthetic()
        self.assertEqual(result["exit_code"], 2)
        self.assertFalse(result["srt_runtime_revalidated"])

    def test_diagnostic_records_confirmed_aba_as_blocker(self):
        self.require_openat2()
        result = P.run_synthetic()
        self.assertEqual(result["exit_code"], 2)
        self.assertIn("ABA_UNDETECTED_REPRODUCED", result["reasons"])
        self.assertIn({"id": "aba_reverted_between_reads",
                       "observation": "ABA_UNDETECTED"}, result["observations"])

    def test_diagnostic_records_stale_fd_with_correct_scope(self):
        self.require_openat2()
        result = P.run_synthetic()
        self.assertIn({"id": "root_fd_replaced_path",
                       "observation": "STALE_FD_DETECTED"}, result["observations"])
        self.assertFalse(result["root_fd_owner_provenance_verified"])

    def test_synthetic_positive_evidence_cannot_unlock_agents(self):
        with mock.patch.dict(P.CASES,
                             {name: (lambda value=val: value)
                              for name, val in P.EXPECTED.items()}, clear=True):
            result = P.run_synthetic()
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["strong"], "UNAVAILABLE")
        self.assertEqual(result["readiness"], "BLOCKED")
        for key in ("agent_execution_authorized", "file_operations_authorized",
                    "cloud_call_authorized", "data_transfer_authorized",
                    "native_tools_isolated_for_agents",
                    "root_fd_owner_provenance_verified",
                    "aba_protection_proven", "real_bind_mount_tested",
                    "real_worktree_verified", "real_workspace_used",
                    "srt_runtime_revalidated"):
            self.assertIs(result[key], False, key)

    def test_missing_or_malformed_evidence_stays_blocked(self):
        with mock.patch.dict(P.CASES, {
                name: (lambda: 1) for name in P.EXPECTED}, clear=True):
            result = P.run_synthetic()
        self.assertEqual(result["exit_code"], 2)
        self.assertIn("SYNTHETIC_EVIDENCE_INCOMPLETE", result["reasons"])
        self.assertTrue(all(x["observation"] == "NOT_VERIFIED"
                            for x in result["observations"]))

    def test_diagnostic_case_error_does_not_echo_paths(self):
        def fail():
            raise OSError("confidential-fake-path")
        cases = {name: (lambda value=val: value)
                 for name, val in P.EXPECTED.items()}
        cases["root_fd_foreign"] = fail
        with mock.patch.dict(P.CASES, cases, clear=True):
            result = P.run_synthetic()
        self.assertEqual(result["exit_code"], 2)
        self.assertNotIn("confidential-fake-path", json.dumps(result))
        self.assertIn("SYNTHETIC_EVIDENCE_INCOMPLETE", result["reasons"])

    def test_unsupported_platform_short_circuits_before_fixture(self):
        with mock.patch.object(P.sys, "platform", "win32"), \
             mock.patch.object(P.L, "create_fixture",
                               side_effect=AssertionError("fixture")):
            result = P.run_synthetic()
        self.assertEqual(result["exit_code"], 2)
        self.assertIn("PLATFORM_NOT_VERIFIED", result["reasons"])

    def test_cli_requires_explicit_synthetic_only(self):
        for argv in ([], ["--workspace", "/real"],
                     ["--file", "/private"], ["--config", "foo"]):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit):
                    P.main(argv)

    def test_cli_json_returns_blocking_status(self):
        with mock.patch.object(P, "run_synthetic", return_value={
                "mode": "diagnostic_only", "exit_code": 2,
                "readiness": "BLOCKED", "strong": "UNAVAILABLE",
                "observations": [], "reasons": []}):
            with redirect_stdout(io.StringIO()) as out:
                rc = P.main(["--synthetic-only", "--json"])
        self.assertEqual(rc, 2)
        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed["strong"], "UNAVAILABLE")

    def test_cli_text_does_not_claim_strong(self):
        with mock.patch.object(P, "run_synthetic", return_value={
                "exit_code": 2, "readiness": "BLOCKED",
                "strong": "UNAVAILABLE", "observations": [
                    {"id": "aba_reverted_between_reads",
                     "observation": "ABA_UNDETECTED"}]}):
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(P.main(["--synthetic-only"]), 2)
        self.assertIn("STRONG: UNAVAILABLE", out.getvalue())
        self.assertIn("ABA_UNDETECTED", out.getvalue())


if __name__ == "__main__":
    unittest.main()
