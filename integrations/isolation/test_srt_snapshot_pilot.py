#!/usr/bin/env python3
"""GH-F1.14 fixed-fixture snapshot tests. No real agents or SRT process in unit tests."""
import copy
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import fakes
import linux_openat2_guard as G
import srt_launcher as L
import srt_snapshot_pilot as P


def good_result():
    result = {name: True for name in P.REQUIRED_RESULTS}
    result["native_snapshot_read"] = {"opened": True, "matched": True}
    return result


class SnapshotPilotTests(unittest.TestCase):
    def stage(self, fx):
        try:
            return P.stage_snapshot(fx)
        except G.Openat2Denied as exc:
            if str(exc) in ("unsupported_platform", "syscall_unavailable"):
                self.skipTest("host kernel openat2 unavailable")
            raise
        except P.SnapshotRefused as exc:
            if str(exc) == "source_boundary_unavailable":
                self.skipTest("host openat2 unavailable")
            raise

    def test_source_hardlink_and_symlink_do_not_enter_snapshot(self):
        with L.create_fixture() as fx:
            root = self.stage(fx)
            self.assertEqual(os.listdir(root), ["sample.txt"])
            self.assertFalse(os.path.exists(os.path.join(root, "hard_to_external")))
            self.assertFalse(os.path.lexists(os.path.join(root, "link_to_external")))

    def test_source_and_copy_have_distinct_inodes_and_single_link(self):
        with L.create_fixture() as fx:
            root = self.stage(fx)
            src = os.stat(fx.auth_canary)
            dst = os.stat(os.path.join(root, P.COPY_NAME))
            self.assertNotEqual((src.st_dev, src.st_ino), (dst.st_dev, dst.st_ino))
            self.assertEqual(dst.st_nlink, 1)
            self.assertEqual(os.stat(fx.hardlink).st_ino, os.stat(fx.secret).st_ino)

    def test_source_and_copy_bytes_match_synthetic_canary(self):
        with L.create_fixture() as fx:
            root = self.stage(fx)
            with open(os.path.join(root, P.COPY_NAME), "rb") as inp:
                self.assertEqual(inp.read(), fx.auth_marker.encode("utf-8"))
            self.assertTrue(P.host_snapshot_intact(fx, root))

    def test_non_fixture_rejected(self):
        with self.assertRaisesRegex(P.SnapshotRefused, "invalid_fixture"):
            P.stage_snapshot({"authorized": "/tmp/example"})

    def test_absent_hardlink_fixture_fails_closed(self):
        with L.create_fixture() as fx:
            os.unlink(fx.hardlink)
            with self.assertRaisesRegex(P.SnapshotRefused, "hardlink_fixture_unavailable"):
                P.stage_snapshot(fx)

    def test_hardlink_fixture_must_match_outside_decoy_inode(self):
        with L.create_fixture() as fx:
            os.unlink(fx.hardlink)
            with open(fx.hardlink, "wb") as out:
                out.write(b"fake")
            with self.assertRaisesRegex(P.SnapshotRefused, "invalid_hardlink_fixture"):
                P.stage_snapshot(fx)

    def test_source_symlink_substitution_refused(self):
        with L.create_fixture() as fx:
            os.unlink(fx.auth_canary)
            os.symlink(fx.secret, fx.auth_canary)
            with self.assertRaises((G.Openat2Denied, P.SnapshotRefused)):
                P.stage_snapshot(fx)

    def test_source_new_hardlink_refused(self):
        with L.create_fixture() as fx:
            os.link(fx.auth_canary, os.path.join(fx.authorized, "extra-link"))
            with self.assertRaises((G.Openat2Denied, P.SnapshotRefused)):
                P.stage_snapshot(fx)

    def test_sealing_removes_write_bits(self):
        with L.create_fixture() as fx:
            root = self.stage(fx)
            try:
                P.seal_snapshot(root)
                self.assertEqual(stat.S_IMODE(os.stat(root).st_mode), 0o500)
                self.assertEqual(stat.S_IMODE(os.stat(os.path.join(root, "sample.txt")).st_mode), 0o400)
            finally:
                os.chmod(root, 0o700)

    def test_sealing_rejects_extra_link_on_copy(self):
        with L.create_fixture() as fx:
            root = self.stage(fx)
            os.link(os.path.join(root, "sample.txt"),
                    os.path.join(fx.authorized, "extra-link"))
            with self.assertRaisesRegex(P.SnapshotRefused, "snapshot_not_sealed"):
                P.seal_snapshot(root)
            os.chmod(root, 0o700)

    def test_host_detects_native_creation(self):
        with L.create_fixture() as fx:
            root = self.stage(fx)
            with open(os.path.join(root, "created.txt"), "wb") as out:
                out.write(b"bad")
            self.assertFalse(P.host_snapshot_intact(fx, root))

    def test_host_detects_native_truncation(self):
        with L.create_fixture() as fx:
            root = self.stage(fx)
            target = os.path.join(root, "sample.txt")
            # O snapshot é 0400 por design. Apenas o supervisor da
            # fixture fictícia simula uma alteração externa e restaura o
            # modo de leitura, para testar a detecção da perda de conteúdo.
            self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o400)
            os.chmod(target, 0o600)
            try:
                with open(target, "r+b") as out:
                    out.truncate(0)
            finally:
                os.chmod(target, 0o400)
            self.assertFalse(P.host_snapshot_intact(fx, root))

    def test_host_refuses_symlink_swapped_target_without_reading_decoy(self):
        with L.create_fixture() as fx:
            root = self.stage(fx)
            os.unlink(os.path.join(root, "sample.txt"))
            os.symlink(fx.secret, os.path.join(root, "sample.txt"))
            self.assertFalse(P.host_snapshot_intact(fx, root))

    def test_host_refuses_hardlink_swapped_target(self):
        with L.create_fixture() as fx:
            root = self.stage(fx)
            os.unlink(os.path.join(root, "sample.txt"))
            os.link(fx.secret, os.path.join(root, "sample.txt"))
            self.assertFalse(P.host_snapshot_intact(fx, root))

    def test_host_refuses_extra_destination_hardlink(self):
        with L.create_fixture() as fx:
            root = self.stage(fx)
            os.link(os.path.join(root, "sample.txt"),
                    os.path.join(fx.authorized, "another-link"))
            self.assertFalse(P.host_snapshot_intact(fx, root))

    def test_write_all_retries_short_writes(self):
        data = b"abcdefghij"
        with tempfile.TemporaryDirectory(prefix="test-snapshot-write-") as tmp:
            fd = os.open(os.path.join(tmp, "out"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            real_write = os.write
            try:
                def short_write(to_fd, buf):
                    return real_write(to_fd, buf[:2])
                with mock.patch.object(P.os, "write", side_effect=short_write):
                    P._write_all(fd, data)
            finally:
                os.close(fd)
            with open(os.path.join(tmp, "out"), "rb") as inp:
                self.assertEqual(inp.read(), data)

    def test_write_all_zero_fails_closed(self):
        with mock.patch.object(P.os, "write", return_value=0):
            with self.assertRaisesRegex(P.SnapshotRefused, "short_write"):
                P._write_all(777, b"a")

    def test_classification_requires_complete_set(self):
        checks = P.classify(good_result(), True, True, True)
        self.assertEqual(len(checks), len(P.REQUIRED_RESULTS) + 4)
        self.assertTrue(all(c["status"] == "PASS" for c in checks))

    def test_classification_requires_positive_authorized_read(self):
        r = good_result()
        r["native_snapshot_read"] = {"opened": True, "matched": False}
        self.assertTrue(any(c["status"] == "FAIL" for c in
                            P.classify(r, True, True, True)))

    def test_classification_denies_native_external_read(self):
        r = good_result()
        r["native_external_denied"] = False
        self.assertTrue(any(c["id"] == "native_external_denied" and c["status"] == "FAIL"
                            for c in P.classify(r, True, True, True)))

    def test_classification_denies_source_hardlink_read(self):
        r = good_result()
        r["native_hardlink_denied"] = False
        self.assertTrue(any(c["id"] == "native_hardlink_denied" and c["status"] == "FAIL"
                            for c in P.classify(r, True, True, True)))

    def test_classification_denies_source_authorized_read(self):
        r = good_result()
        r["native_source_denied"] = False
        self.assertTrue(any(c["status"] == "FAIL" for c in
                            P.classify(r, True, True, True)))

    def test_classification_denies_readonly_policy_missing(self):
        self.assertTrue(any(c["id"] == "readonly_policy_verified"
                            and c["status"] == "FAIL"
                            for c in P.classify(good_result(), True, False, True)))

    def test_classification_denies_host_snapshot_modified(self):
        self.assertTrue(any(c["id"] == "host_snapshot_unchanged"
                            and c["status"] == "FAIL"
                            for c in P.classify(good_result(), False, True, True)))

    def test_classification_denies_non_independent_snapshot(self):
        self.assertTrue(any(c["id"] == "snapshot_independent_inode"
                            and c["status"] == "FAIL"
                            for c in P.classify(good_result(), True, True, False)))

    def test_classification_denies_unexecuted_worker(self):
        self.assertTrue(any(c["id"] == "worker_executed" and c["status"] == "FAIL"
                            for c in P.classify(None, True, True, True)))

    def test_classification_missing_results_fail(self):
        for name in P.REQUIRED_RESULTS:
            r = good_result()
            del r[name]
            self.assertTrue(any(c["id"] == name and c["status"] == "FAIL"
                                for c in P.classify(r, True, True, True)))

    def test_classification_incorrect_boolean_types_fail(self):
        for item in ("native_symlink_denied", "native_create_denied", "native_truncate_denied"):
            r = good_result()
            r[item] = 1
            self.assertTrue(any(c["id"] == item and c["status"] == "FAIL"
                                for c in P.classify(r, True, True, True)))

    def test_invalid_timeout_cannot_spawn(self):
        for bad in (0, 121, True, -2, "3"):
            with mock.patch.object(P.L, "_spawn", side_effect=AssertionError("spawn")):
                with self.assertRaises(P.SnapshotRefused):
                    P._worker(None, None, "/fictional", bad)

    def test_spoofed_nonce_refused(self):
        with L.create_fixture() as fx:
            d = fakes.make_fake_deps(fx.tmp, "validate")
            root = fx.authorized
            with mock.patch.object(P.L, "_spawn",
                                   return_value=(0, b'{"nonce":"wrong","results":{}}', b"", False)):
                self.assertIsNone(P._worker(d, fx, root, 5))

    def test_nested_json_or_timeout_fails_closed(self):
        with L.create_fixture() as fx:
            d = fakes.make_fake_deps(fx.tmp, "validate")
            result = (0, (b"[" * 1500) + b"0" + (b"]" * 1500), b"", False)
            with mock.patch.object(P.L, "_spawn", return_value=result):
                self.assertIsNone(P._worker(d, fx, fx.authorized, 5))
            with mock.patch.object(P.L, "_spawn", return_value=(0, b"", b"", True)):
                self.assertIsNone(P._worker(d, fx, fx.authorized, 5))

    def test_fixed_worker_invocation_no_agent_or_arbitrary_shell(self):
        with L.create_fixture() as fx:
            d = fakes.make_fake_deps(fx.tmp, "validate")
            seen = []
            def spy(argv, env, cwd, timeout):
                seen.append((argv, env, cwd, timeout))
                return 1, b"", b"", False
            with mock.patch.object(P.L, "_spawn", side_effect=spy):
                self.assertIsNone(P._worker(d, fx, fx.authorized, 7))
            argv, env, cwd, timeout = seen[0]
            self.assertEqual(argv[1:4], ["--settings", fx.settings_path, "--"])
            self.assertEqual(argv[4:9], [L.INTERPRETER, "-I", "-B", "-c", P.WORKER_SRC])
            self.assertEqual(timeout, 7)
            self.assertEqual(cwd, fx.authorized)
            for key in ("ANTHROPIC_API_KEY", "SSH_AUTH_SOCK", "LD_PRELOAD", "NODE_OPTIONS"):
                self.assertNotIn(key, env)

    def test_fake_srt_cannot_prove_safe_snapshot(self):
        with L.create_fixture() as fx:
            d = fakes.make_fake_deps(fx.tmp, "ignore_settings_ok")
            with mock.patch.object(P.L, "runtime_read_paths",
                                   return_value=["/usr", d.get("apply-seccomp").path]):
                result = P.run_synthetic(deps=d, timeout=15)
            self.assertEqual(result["exit_code"], 2)
            self.assertEqual(result["strong"], "UNAVAILABLE")
            self.assertFalse(result["agent_execution_authorized"])

    def test_all_results_never_authorize_agents_even_if_all_checks_pass(self):
        with mock.patch.object(P.L, "detect_dependencies",
                               side_effect=P.SnapshotRefused("missing")):
            result = P.run_synthetic()
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["strong"], "UNAVAILABLE")
        self.assertEqual(result["readiness"], "BLOCKED")
        for key in ("agent_execution_authorized", "file_operations_authorized",
                    "cloud_call_authorized", "data_transfer_authorized",
                    "native_tools_isolated_for_agents", "real_bind_mount_tested",
                    "concurrency_verified", "real_workspace_used"):
            self.assertIs(result[key], False, key)

    def test_unknown_platform_does_not_run_any_pilot(self):
        with mock.patch.object(P.sys, "platform", "darwin"), \
             mock.patch.object(P.L, "detect_dependencies",
                               side_effect=AssertionError("deps")):
            self.assertEqual(P.run_synthetic()["exit_code"], 2)

    def test_cli_requires_synthetic_only(self):
        with self.assertRaises(SystemExit):
            P.main([])
        with self.assertRaises(SystemExit):
            P.main(["--workspace", "/home/real"])
        with self.assertRaises(SystemExit):
            P.main(["--config", "/real/config"])

    def test_cli_reports_blocked_status(self):
        with mock.patch.object(P, "run_synthetic",
                               return_value={"exit_code": 2, "strong": "UNAVAILABLE",
                                             "checks": [], "readiness": "BLOCKED"}):
            with redirect_stdout(io.StringIO()) as output:
                rc = P.main(["--synthetic-only", "--json"])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(output.getvalue())["strong"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
