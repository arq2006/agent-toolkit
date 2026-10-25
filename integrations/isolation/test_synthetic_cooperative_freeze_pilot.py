#!/usr/bin/env python3
"""GH-F1.17: cooperative-only freeze experiments and fail-closed guarantees."""
import io
import json
import os
import stat
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

import linux_openat2_guard as G
import pathguard
import srt_launcher as L
import srt_snapshot_pilot as P
import synthetic_cooperative_freeze_pilot as F


class CooperativeFreezeTests(unittest.TestCase):
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

    def test_baseline_cooperative_stage(self):
        self.require_openat2()
        self.assertEqual(F._fixture_snapshot(), "STAGED_UNDER_LOCK")

    def test_cooperating_writer_cannot_mutate_during_stage(self):
        self.require_openat2()
        self.assertEqual(F._writer_waits(), "WRITER_DEFERRED_UNTIL_RELEASE")

    def test_root_path_rebind_fails_closed(self):
        self.require_openat2()
        self.assertEqual(F._root_rebind(), "STALE_PATH_REFUSED")

    def test_symlink_lock_name_rejected(self):
        self.assertEqual(F._preexisting_lock(), "UNTRUSTED_LOCK_NAME_REFUSED")

    def test_uncooperative_writer_still_bypasses_advisory_flock(self):
        self.assertEqual(F._uncooperative_bypass(), "ADVISORY_BYPASS_REPRODUCED")

    def test_fixture_baseline_source_unchanged(self):
        self.require_openat2()
        with L.create_fixture() as fx:
            before = os.stat(fx.auth_canary, follow_symlinks=False)
            root = F._cooperative_stage(fx)
            after = os.stat(fx.auth_canary, follow_symlinks=False)
            self.assertEqual((before.st_dev, before.st_ino, before.st_size),
                             (after.st_dev, after.st_ino, after.st_size))
            self.assertTrue(P.host_snapshot_intact(fx, root))

    def test_lock_created_only_within_fixture(self):
        with L.create_fixture() as fx:
            fd = F._new_lock_fd(fx)
            try:
                self.assertEqual(stat.S_IMODE(os.fstat(fd).st_mode), 0o600)
                self.assertEqual(os.fstat(fd).st_nlink, 1)
                self.assertEqual(os.stat(os.path.join(fx.root, F.LOCK_NAME)).st_ino,
                                 os.fstat(fd).st_ino)
            finally:
                os.close(fd)

    def test_lock_is_regular_file_owned_by_supervisor(self):
        with L.create_fixture() as fx:
            fd = F._new_lock_fd(fx)
            try:
                st = os.fstat(fd)
                self.assertTrue(stat.S_ISREG(st.st_mode))
                self.assertEqual(st.st_uid, os.getuid())
            finally:
                os.close(fd)

    def test_second_lock_creation_refused(self):
        with L.create_fixture() as fx:
            fd = F._new_lock_fd(fx)
            os.close(fd)
            with self.assertRaisesRegex(F.FreezeRefused, "lock_creation_refused"):
                F._new_lock_fd(fx)

    def test_preexisting_regular_lock_refused(self):
        with L.create_fixture() as fx:
            with open(os.path.join(fx.root, F.LOCK_NAME), "xb") as out:
                out.write(b"fixed")
            with self.assertRaisesRegex(F.FreezeRefused, "lock_creation_refused"):
                F._new_lock_fd(fx)

    def test_preexisting_hardlinked_lock_refused(self):
        with L.create_fixture() as fx:
            os.link(fx.secret, os.path.join(fx.root, F.LOCK_NAME))
            with self.assertRaisesRegex(F.FreezeRefused, "lock_creation_refused"):
                F._new_lock_fd(fx)

    def test_lock_symlink_does_not_change_fictional_decoy(self):
        with L.create_fixture() as fx:
            with open(fx.secret, "rb") as inp:
                before = inp.read()
            os.symlink(fx.secret, os.path.join(fx.root, F.LOCK_NAME))
            with self.assertRaises(F.FreezeRefused):
                F._new_lock_fd(fx)
            with open(fx.secret, "rb") as inp:
                self.assertEqual(inp.read(), before)

    def test_nonfixture_dict_rejected_without_side_effect(self):
        with self.assertRaisesRegex(F.FreezeRefused, "invalid_fixture"):
            F._new_lock_fd({"root": "/tmp"})

    def test_nonfixture_none_rejected(self):
        with self.assertRaisesRegex(F.FreezeRefused, "invalid_fixture"):
            F._new_lock_fd(None)

    def test_type_substitution_refused(self):
        class FakeFixture:
            root = "/tmp/not-created"
        with self.assertRaisesRegex(F.FreezeRefused, "invalid_fixture"):
            F._new_lock_fd(FakeFixture())

    def test_cooperative_stage_refuses_already_used_lock(self):
        with L.create_fixture() as fx:
            fd = F._new_lock_fd(fx)
            os.close(fd)
            with self.assertRaisesRegex(F.FreezeRefused, "lock_creation_refused"):
                F._cooperative_stage(fx)

    def test_invalid_source_binding_refused_before_stage(self):
        with L.create_fixture() as fx:
            with mock.patch.object(F.D, "_root_path_binding_matches", return_value=False), \
                 mock.patch.object(F.P, "stage_snapshot",
                                   side_effect=AssertionError("staging must not run")):
                with self.assertRaisesRegex(F.FreezeRefused, "root_rebound"):
                    F._cooperative_stage(fx)

    def test_binding_refused_after_stage(self):
        self.require_openat2()
        with L.create_fixture() as fx:
            with mock.patch.object(F.D, "_root_path_binding_matches",
                                   side_effect=[True, False]):
                with self.assertRaisesRegex(F.FreezeRefused, "root_rebound"):
                    F._cooperative_stage(fx)

    def test_snapshot_integrity_failure_refuses(self):
        self.require_openat2()
        with L.create_fixture() as fx:
            with mock.patch.object(F.P, "host_snapshot_intact", return_value=False):
                with self.assertRaisesRegex(F.FreezeRefused, "snapshot_changed"):
                    F._cooperative_stage(fx)

    def test_flock_is_exclusive_during_staging(self):
        self.require_openat2()
        import fcntl
        with L.create_fixture() as fx:
            original = F.P.stage_snapshot
            seen = []
            def inspect_lock(obj):
                other = os.open(os.path.join(fx.root, F.LOCK_NAME),
                                os.O_RDWR | os.O_NOFOLLOW)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    seen.append(True)
                finally:
                    os.close(other)
                return original(obj)
            with mock.patch.object(F.P, "stage_snapshot", side_effect=inspect_lock):
                F._cooperative_stage(fx)
            self.assertEqual(seen, [True])

    def test_lock_released_on_stage_exception(self):
        import fcntl
        with L.create_fixture() as fx:
            with mock.patch.object(F.P, "stage_snapshot",
                                   side_effect=F.FreezeRefused("synthetic")):
                with self.assertRaises(F.FreezeRefused):
                    F._cooperative_stage(fx)
            fd = os.open(os.path.join(fx.root, F.LOCK_NAME), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)

    def test_lock_stays_exclusive_during_post_stage_checks(self):
        self.require_openat2()
        import fcntl
        with L.create_fixture() as fx:
            original = F.P.host_snapshot_intact
            checked = []
            def check_while_locked(fixture, root):
                other = os.open(os.path.join(fx.root, F.LOCK_NAME), os.O_RDWR)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    checked.append(True)
                finally:
                    os.close(other)
                return original(fixture, root)
            with mock.patch.object(F.P, "host_snapshot_intact",
                                   side_effect=check_while_locked):
                F._cooperative_stage(fx)
            self.assertEqual(checked, [True])

    def test_expected_closed_catalog(self):
        self.assertEqual(len(F.EXPECTED), 5)
        self.assertEqual(set(F.CASES), set(F.EXPECTED))
        self.assertIn("ADVISORY_BYPASS_REPRODUCED", F.EXPECTED.values())

    def test_classifier_only_exact_expected_values(self):
        self.assertEqual(
            [x["observation"] for x in F.classify(dict(F.EXPECTED))],
            list(F.EXPECTED.values()))

    def test_classifier_does_not_depend_on_input_order(self):
        self.assertEqual(F.classify(dict(reversed(list(F.EXPECTED.items())))),
                         F.classify(dict(F.EXPECTED)))

    def test_classifier_rejects_missing_or_extra(self):
        for value in (None, [], {}, {"extra": "STAGED_UNDER_LOCK"},
                      {**F.EXPECTED, "extra": "STAGED_UNDER_LOCK"}):
            with self.subTest(value=str(value)):
                self.assertTrue(all(x["observation"] == "NOT_VERIFIED"
                                    for x in F.classify(value)))

    def test_classifier_rejects_numeric_and_boolean_values(self):
        for value in (True, 1, 1.0, False, "STAGED_UNDER_LOCK ", None):
            with self.subTest(value=repr(value)):
                fake = dict(F.EXPECTED)
                fake["fixture_cooperative_snapshot"] = value
                self.assertIn({"id": "fixture_cooperative_snapshot",
                               "observation": "NOT_VERIFIED"},
                              F.classify(fake))

    def test_runner_always_exit_two_with_all_expected_evidence(self):
        fake = {key: (lambda value=val: value)
                for key, val in F.EXPECTED.items()}
        with mock.patch.dict(F.CASES, fake, clear=True):
            report = F.run_synthetic()
        self.assertEqual(report["exit_code"], 2)
        self.assertEqual(report["readiness"], "BLOCKED")
        self.assertEqual(report["strong"], "UNAVAILABLE")
        self.assertIn("UNCOOPERATIVE_WRITE_BYPASS_REPRODUCED", report["reasons"])

    def test_runner_all_cases_in_real_synthetic_fixtures(self):
        self.require_openat2()
        report = F.run_synthetic()
        self.assertEqual(report["exit_code"], 2)
        self.assertEqual(len(report["observations"]), 5)
        self.assertEqual(report["observations"], F.classify(dict(F.EXPECTED)))
        self.assertNotIn("SYNTHETIC_EVIDENCE_INCOMPLETE", report["reasons"])

    def test_runner_failure_stays_blocked(self):
        with mock.patch.dict(F.CASES, {
                key: (lambda: "NOT_VERIFIED") for key in F.EXPECTED}, clear=True):
            report = F.run_synthetic()
        self.assertEqual(report["exit_code"], 2)
        self.assertIn("SYNTHETIC_EVIDENCE_INCOMPLETE", report["reasons"])

    def test_case_errors_never_echo_paths(self):
        def raise_error():
            raise OSError("secret-fake-file")
        with mock.patch.dict(F.CASES, {
                key: raise_error for key in F.EXPECTED}, clear=True):
            report = F.run_synthetic()
        self.assertEqual(report["exit_code"], 2)
        self.assertNotIn("secret-fake-file", json.dumps(report))

    def test_all_grant_and_provenance_flags_false_even_on_faked_success(self):
        fake = {key: (lambda value=val: value)
                for key, val in F.EXPECTED.items()}
        with mock.patch.dict(F.CASES, fake, clear=True):
            report = F.run_synthetic()
        for field in ("agent_execution_authorized", "file_operations_authorized",
                      "cloud_call_authorized", "data_transfer_authorized",
                      "trusted_owner_provenance_verified", "uncooperative_writers_isolated",
                      "aba_protection_proven", "native_tools_isolated_for_agents",
                      "real_bind_mount_tested", "real_worktree_verified",
                      "real_workspace_used", "srt_runtime_revalidated"):
            self.assertIs(report[field], False, field)

    def test_unsupported_platform_exits_before_fixture(self):
        with mock.patch.object(F.sys, "platform", "darwin"), \
             mock.patch.object(F.L, "create_fixture",
                               side_effect=AssertionError("fixture must not run")):
            report = F.run_synthetic()
        self.assertEqual(report["exit_code"], 2)
        self.assertIn("PLATFORM_NOT_VERIFIED", report["reasons"])

    def test_cli_rejects_no_synthetic_flag_and_arbitrary_paths(self):
        for argv in ([], ["--workspace", "/project"], ["--path", "/tmp"],
                     ["--config", "/secret"]):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit):
                    F.main(argv)

    def test_cli_json_returns_always_blocked(self):
        with mock.patch.object(F, "run_synthetic", return_value={
                "mode": "synthetic-only-diagnostic", "readiness": "BLOCKED",
                "strong": "UNAVAILABLE", "exit_code": 2,
                "observations": [], "reasons": []}):
            with redirect_stdout(io.StringIO()) as out:
                result = F.main(["--synthetic-only", "--json"])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(out.getvalue())["strong"], "UNAVAILABLE")

    def test_cli_text_reports_unavailable_and_advisory_risk(self):
        with mock.patch.object(F, "run_synthetic", return_value={
                "mode": "synthetic-only-diagnostic", "exit_code": 2,
                "observations": [{"id": "uncooperative_writer_bypass",
                                  "observation": "ADVISORY_BYPASS_REPRODUCED"}]}):
            with redirect_stdout(io.StringIO()) as out:
                result = F.main(["--synthetic-only"])
        self.assertEqual(result, 2)
        self.assertIn("STRONG: UNAVAILABLE", out.getvalue())
        self.assertIn("ADVISORY_BYPASS_REPRODUCED", out.getvalue())

    def test_no_srt_worker_or_subprocess(self):
        self.require_openat2()
        with mock.patch.object(F.P, "_worker",
                               side_effect=AssertionError("SRT worker")), \
             mock.patch("subprocess.Popen",
                        side_effect=AssertionError("external process")):
            report = F.run_synthetic()
        self.assertEqual(report["exit_code"], 2)
        self.assertFalse(report["srt_runtime_revalidated"])


if __name__ == "__main__":
    unittest.main()
