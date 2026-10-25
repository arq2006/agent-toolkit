#!/usr/bin/env python3
"""GH-F1.13 readiness gate regressions; never run real SRT in unit tests."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

import native_boundary_readiness as P


def report(which="readonly"):
    keys = P.BASELINE_CHECKS if which == "readonly" else P.OPENAT2_CHECKS
    obj = {
        "mode": "synthetic-only", "strong": "UNAVAILABLE",
        "file_operations": "BLOCKED_FOR_AGENTS",
        "agent_execution_authorized": False, "exit_code": 0,
        "checks": [{"id": k, "status": "PASS"} for k in sorted(keys)],
    }
    if which == "readonly":
        obj["native_hardlink_limitation"] = "NATIVE_HARDLINK_LEAK_REPRODUCED"
    else:
        obj["bind_mount_test"] = P.EXPECTED_MOUNT_STATUS
    return obj


class ReadinessTests(unittest.TestCase):
    def test_complete_pilot_reports_still_blocked(self):
        out = P.assess_reports(report(), report("openat2"))
        self.assertTrue(out["readonly_canaries_complete"])
        self.assertTrue(out["openat2_canaries_complete"])
        self.assertEqual(out["strong"], "UNAVAILABLE")
        self.assertEqual(out["readiness"], "BLOCKED")
        self.assertEqual(out["exit_code"], 2)

    def test_native_hardlink_leak_is_explicit_mandatory_blocker(self):
        out = P.assess_reports(report(), report("openat2"))
        self.assertIn("NATIVE_HARDLINK_LEAK_REPRODUCED", out["reasons"])
        self.assertTrue(out["native_hardlink_leak_observed"])

    def test_no_native_read_observed_does_not_approve_strong(self):
        r = report()
        r["native_hardlink_limitation"] = "NATIVE_READ_NOT_OBSERVED"
        out = P.assess_reports(r, report("openat2"))
        self.assertIn("NATIVE_HARDLINK_DENIAL_NOT_PROVEN", out["reasons"])
        self.assertFalse(out["native_hardlink_leak_observed"])

    def test_not_tested_native_hardlink_fails_closed(self):
        r = report()
        r["native_hardlink_limitation"] = "NOT_TESTED"
        self.assertIn("NATIVE_HARDLINK_TEST_INCOMPLETE",
                      P.assess_reports(r, report("openat2"))["reasons"])

    def test_missing_native_hardlink_status_fails_closed(self):
        r = report()
        del r["native_hardlink_limitation"]
        out = P.assess_reports(r, report("openat2"))
        self.assertIn("NATIVE_HARDLINK_TEST_INCOMPLETE", out["reasons"])

    def test_unknown_native_status_fails_closed(self):
        r = report()
        r["native_hardlink_limitation"] = "MITIGATED"
        out = P.assess_reports(r, report("openat2"))
        self.assertIn("NATIVE_HARDLINK_TEST_INCOMPLETE", out["reasons"])

    def test_missing_bind_mount_report_fails_closed(self):
        o = report("openat2")
        del o["bind_mount_test"]
        out = P.assess_reports(report(), o)
        self.assertIn("BIND_MOUNT_REPORT_UNRECOGNIZED", out["reasons"])

    def test_forged_bind_mount_pass_does_not_approve(self):
        o = report("openat2")
        o["bind_mount_test"] = "PASS"
        out = P.assess_reports(report(), o)
        self.assertIn("BIND_MOUNT_REPORT_UNRECOGNIZED", out["reasons"])
        self.assertFalse(out["real_bind_mount_tested"])

    def test_even_declared_no_xdev_does_not_prove_actual_mounts(self):
        out = P.assess_reports(report(), report("openat2"))
        self.assertIn("REAL_BIND_MOUNT_ISOLATION_NOT_TESTED", out["reasons"])
        self.assertFalse(out["real_bind_mount_tested"])

    def test_concurrency_and_native_agent_tools_remain_unverified(self):
        out = P.assess_reports(report(), report("openat2"))
        self.assertIn("CONCURRENT_MUTATION_AND_TOCTOU_NOT_VERIFIED", out["reasons"])
        self.assertIn("NATIVE_AGENT_TOOL_BOUNDARY_NOT_VERIFIED", out["reasons"])
        self.assertFalse(out["native_tools_isolated"])

    def test_all_effective_permissions_remain_false(self):
        out = P.assess_reports(report(), report("openat2"))
        for field in ("agent_execution_authorized", "file_operations_authorized",
                      "cloud_call_authorized", "data_transfer_authorized",
                      "native_tools_isolated", "real_worktree_verified",
                      "root_fd_verified", "owner_approvals_verified"):
            self.assertIs(out[field], False, field)

    def test_empty_reports_fail_closed(self):
        out = P.assess_reports(None, None)
        self.assertFalse(out["readonly_canaries_complete"])
        self.assertFalse(out["openat2_canaries_complete"])
        self.assertEqual(out["exit_code"], 2)
        self.assertIn("SRT_READONLY_CANARIES_NOT_VERIFIED", out["reasons"])
        self.assertIn("OPENAT2_CANARIES_NOT_VERIFIED", out["reasons"])

    def test_malformed_report_types_fail_closed(self):
        for malformed in ("bad", [], True, 0, {}, {"checks": []}):
            out = P.assess_reports(malformed, malformed)
            self.assertFalse(out["readonly_canaries_complete"])
            self.assertFalse(out["openat2_canaries_complete"])
            self.assertEqual(out["readiness"], "BLOCKED")

    def test_missing_positive_check_is_denied(self):
        r = report()
        r["checks"].pop()
        self.assertFalse(P.assess_reports(r, report("openat2"))
                         ["readonly_canaries_complete"])

    def test_duplicate_positive_check_does_not_replace_missing_check(self):
        r = report()
        r["checks"][-1] = copy.deepcopy(r["checks"][0])
        self.assertFalse(P.assess_reports(r, report("openat2"))
                         ["readonly_canaries_complete"])

    def test_unknown_check_does_not_replace_required_check(self):
        o = report("openat2")
        o["checks"][0]["id"] = "forged-safe"
        self.assertFalse(P.assess_reports(report(), o)
                         ["openat2_canaries_complete"])

    def test_negative_canary_status_blocks_complete_evidence(self):
        for which in ("readonly", "openat2"):
            r, o = report(), report("openat2")
            target = r if which == "readonly" else o
            target["checks"][0]["status"] = "FAIL"
            out = P.assess_reports(r, o)
            self.assertFalse(out["readonly_canaries_complete"] if which == "readonly"
                             else out["openat2_canaries_complete"])

    def test_forged_exit_code_zero_bool_is_denied(self):
        r = report()
        r["exit_code"] = False
        self.assertFalse(P.assess_reports(r, report("openat2"))
                         ["readonly_canaries_complete"])

    def test_forged_report_strong_is_denied(self):
        r = report()
        r["strong"] = "AVAILABLE"
        self.assertFalse(P.assess_reports(r, report("openat2"))
                         ["readonly_canaries_complete"])

    def test_forged_agent_authorization_is_denied(self):
        o = report("openat2")
        o["agent_execution_authorized"] = True
        out = P.assess_reports(report(), o)
        self.assertFalse(out["openat2_canaries_complete"])
        self.assertFalse(out["agent_execution_authorized"])

    def test_forged_file_operations_enabled_denied(self):
        r = report()
        r["file_operations"] = "ALLOWED"
        self.assertFalse(P.assess_reports(r, report("openat2"))
                         ["readonly_canaries_complete"])

    def test_unknown_schema_in_check_list_is_denied(self):
        o = report("openat2")
        o["checks"][0] = False
        self.assertFalse(P.assess_reports(report(), o)
                         ["openat2_canaries_complete"])

    def test_report_reasons_are_stable_no_secret_marker_or_path(self):
        out = P.assess_reports(report(), report("openat2"))
        rendered = json.dumps(out)
        for text in ("FICTIONAL-SECRET", "/home/example", "secret.txt"):
            self.assertNotIn(text, rendered)
        self.assertEqual(out["reasons"], sorted(set(out["reasons"])))

    def test_inputs_are_not_modified(self):
        r, o = report(), report("openat2")
        original = copy.deepcopy((r, o))
        P.assess_reports(r, o)
        self.assertEqual((r, o), original)

    def test_synthetic_runner_invokes_only_known_fixed_pilots(self):
        with mock.patch.object(P.readonly_pilot, "run_synthetic",
                               return_value=report()) as readonly, \
             mock.patch.object(P.openat2_probe, "run_synthetic",
                               return_value=report("openat2")) as openat2:
            result = P.run_synthetic()
        readonly.assert_called_once_with()
        openat2.assert_called_once_with()
        self.assertEqual(result["exit_code"], 2)

    def test_synthetic_runner_catches_pilot_failure_and_blocks(self):
        with mock.patch.object(P.readonly_pilot, "run_synthetic",
                               side_effect=RuntimeError("synthetic failure")), \
             mock.patch.object(P.openat2_probe, "run_synthetic",
                               return_value=report("openat2")):
            out = P.run_synthetic()
        self.assertFalse(out["readonly_canaries_complete"])
        self.assertEqual(out["exit_code"], 2)

    def test_synthetic_runner_catches_second_pilot_failure_and_blocks(self):
        with mock.patch.object(P.readonly_pilot, "run_synthetic",
                               return_value=report()), \
             mock.patch.object(P.openat2_probe, "run_synthetic",
                               side_effect=OSError("no sandbox")):
            out = P.run_synthetic()
        self.assertFalse(out["openat2_canaries_complete"])
        self.assertEqual(out["exit_code"], 2)

    def test_cli_requires_synthetic_only(self):
        with self.assertRaises(SystemExit):
            P.main([])
        with self.assertRaises(SystemExit):
            P.main(["--config", "/home/user"])
        with self.assertRaises(SystemExit):
            P.main(["--workspace", "/home/user"])

    def test_cli_returns_two_and_never_lies_about_readiness(self):
        with mock.patch.object(P, "run_synthetic",
                               return_value=P.assess_reports(report(), report("openat2"))):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = P.main(["--synthetic-only", "--json"])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(output.getvalue())["strong"], "UNAVAILABLE")

    def test_no_command_execution_in_pure_assessment(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("spawn")), \
             mock.patch("socket.socket", side_effect=AssertionError("network")):
            P.assess_reports(report(), report("openat2"))


if __name__ == "__main__":
    unittest.main()
