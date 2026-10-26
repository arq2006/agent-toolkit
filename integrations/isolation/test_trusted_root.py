#!/usr/bin/env python3
import contextlib
import ctypes
import dataclasses as dc
import errno
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import trusted_root as T

HERE = os.path.dirname(os.path.abspath(__file__))


def open_fds():
    return set(os.listdir("/proc/self/fd"))


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.parent, self.name = T.make_synthetic_fixture()
        self.anchor = T.open_anchor(self.parent)
        self.addCleanup(shutil.rmtree, self.parent, ignore_errors=True)
        self.addCleanup(self._close_anchor)

    def _close_anchor(self):
        try:
            os.close(self.anchor)
        except OSError:
            pass

    def path(self, name):
        return os.path.join(self.parent, name)

    def refused(self, code, fn, *args):
        with self.assertRaises(T.RootRefused) as caught:
            fn(*args)
        self.assertEqual(caught.exception.code, code)

    def open_root(self):
        return T.open_synthetic_root(self.anchor, self.name)

    def make_second_root(self, name):
        os.mkdir(self.path(name), 0o700)
        with open(os.path.join(self.path(name), T.MARKER_NAME), "wb") as marker:
            marker.write(T.MARKER_CONTENT)


class KernelTests(FixtureCase):
    def setUp(self):
        super().setUp()
        try:
            with self.open_root():
                pass
        except T.RootRefused as e:
            if e.code in ("syscall_unavailable", "unsupported_platform"):
                self.skipTest("openat2/statx indisponível: NÃO é evidência")
            raise

    def test_positive_control_synthetic_root(self):
        with self.open_root() as root:
            ident = root.identity
            st = os.fstat(root.fd)
            self.assertEqual((ident.dev, ident.ino), (st.st_dev, st.st_ino))
            self.assertIn(ident.mnt_id_variant, ("unique", "legacy"))
            self.assertTrue(ident.statx_mask & T.STATX_INO)
            self.assertTrue(ident.statx_mask & T.STATX_TYPE)
            expected_bit = (T.STATX_MNT_ID_UNIQUE if ident.mnt_id_variant == "unique"
                            else T.STATX_MNT_ID)
            self.assertTrue(ident.statx_mask & expected_bit)
            root.revalidate_fd()
            root.reopen_and_compare(self.anchor, self.name)
            report = root.describe()
            self.assertEqual(report["strong"], "UNAVAILABLE")
            self.assertEqual(report["readiness"], "BLOCKED")
            self.assertIs(report["owner_authenticated"], False)
            self.assertIs(report["identity_scope"] == "comparison_only", True)

    def test_kernel_dev_matches_fstat_and_struct_size(self):
        # Verificação empírica pedida pela ADR-012 (7.2): dev de statx vs fstat.
        self.assertEqual(ctypes.sizeof(T._Statx), 256)
        fd = os.open(self.parent, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, fd)
        stx = T._sys_statx(fd, T.STATX_TYPE | T.STATX_INO)
        st = os.fstat(fd)
        self.assertEqual(stx.stx_ino, st.st_ino)
        self.assertEqual(os.makedev(stx.stx_dev_major, stx.stx_dev_minor), st.st_dev)

    def test_kernel_legacy_mnt_id_request(self):
        fd = os.open(self.parent, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, fd)
        stx = T._sys_statx(fd, T.STATX_TYPE | T.STATX_INO | T.STATX_MNT_ID)
        if not stx.stx_mask & T.STATX_MNT_ID:
            self.skipTest("STATX_MNT_ID não devolvido: NOT_VERIFIED")
        self.assertGreater(stx.stx_mnt_id, 0)

    def test_closed_fd_refused_with_positive_control(self):
        with self.open_root() as root:
            root.revalidate_fd()
            dead = os.dup(root.fd)
            os.close(dead)
            self.refused("invalid_fd", T.observe, dead)
        closed_anchor = os.dup(self.anchor)
        os.close(closed_anchor)
        self.refused("invalid_anchor", T.open_synthetic_root, closed_anchor, self.name)

    def test_regular_file_instead_of_directory(self):
        with self.open_root():
            pass  # controle positivo
        name = T.SYNTHETIC_PREFIX + "file"
        with open(self.path(name), "wb") as out:
            out.write(T.MARKER_CONTENT)
        before = open_fds()
        self.refused("not_directory", T.open_synthetic_root, self.anchor, name)
        self.assertEqual(open_fds(), before)
        fd = os.open(self.path(name), os.O_RDONLY)
        self.addCleanup(os.close, fd)
        self.refused("not_directory", T.observe, fd)

    def test_symlink_replacing_root_component(self):
        with self.open_root():
            pass  # controle positivo
        link = T.SYNTHETIC_PREFIX + "link"
        os.symlink(self.path(self.name), self.path(link))
        before = open_fds()
        with self.assertRaises(T.RootRefused) as caught:
            T.open_synthetic_root(self.anchor, link)
        self.assertIn(caught.exception.code, ("symlink_refused", "not_directory"))
        self.assertEqual(open_fds(), before)

    def test_marker_symlink_is_not_accepted(self):
        marker = os.path.join(self.path(self.name), T.MARKER_NAME)
        outside = self.path("elsewhere")
        with open(outside, "wb") as out:
            out.write(T.MARKER_CONTENT)
        os.unlink(marker)
        os.symlink(outside, marker)
        before = open_fds()
        self.refused("not_synthetic", self.open_root)
        self.assertEqual(open_fds(), before)

    def test_rename_and_rebind_are_detected_by_reopen_only(self):
        with self.open_root() as root:
            root.reopen_and_compare(self.anchor, self.name)  # controle positivo
            os.rename(self.path(self.name), self.path("moved-away"))
            # FD obsoleto ainda passa: prova que revalidate_fd NÃO vê o nome.
            root.revalidate_fd()
            self.refused("root_missing", root.reopen_and_compare, self.anchor, self.name)
            self.make_second_root(self.name)  # outro objeto com o mesmo nome
            self.refused("identity_diverged", root.reopen_and_compare,
                         self.anchor, self.name)

    def test_removed_root_is_refused(self):
        with self.open_root() as root:
            root.revalidate_fd()
            os.unlink(os.path.join(self.path(self.name), T.MARKER_NAME))
            os.rmdir(self.path(self.name))
            self.refused("root_unlinked", root.revalidate_fd)

    def test_divergent_identity_between_distinct_roots(self):
        other = T.SYNTHETIC_PREFIX + "other"
        self.make_second_root(other)
        with self.open_root() as first, T.open_synthetic_root(self.anchor, other) as second:
            T.compare(first.identity, first.identity)  # controle positivo
            self.refused("identity_diverged", T.compare, first.identity, second.identity)

    def test_real_mountpoint_is_refused_by_no_xdev(self):
        if not os.path.ismount("/proc"):
            self.skipTest("/proc não é mountpoint: NOT_VERIFIED")
        slash = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, slash)
        self.refused("xdev_refused", T._open_dir, slash, "proc")  # nenhum mount criado
        os.close(T._open_dir(self.anchor, self.name))  # controle: sem mount, abre

    def test_invalid_names_and_non_synthetic_directories(self):
        with self.open_root():
            pass  # controle positivo
        for bad in ("", ".", "..", "a/b", "/abs", "x\x00y", None, b"bytes", 7):
            self.refused("invalid_name", T.open_synthetic_root, self.anchor, bad)
        os.mkdir(self.path("plain"))
        self.refused("not_synthetic", T.open_synthetic_root, self.anchor, "plain")
        bare = T.SYNTHETIC_PREFIX + "bare"
        os.mkdir(self.path(bare))  # prefixo certo, sem marcador
        self.refused("not_synthetic", T.open_synthetic_root, self.anchor, bare)



class MixedTests(FixtureCase):
    """Preparação real + falha injetada: prova a lógica, não o kernel."""

    def real_statx(self, fd, mask):
        return T._sys_statx(fd, mask)

    def setUp(self):
        super().setUp()
        try:
            with self.open_root():
                pass
        except T.RootRefused as e:
            if e.code in ("syscall_unavailable", "unsupported_platform"):
                self.skipTest("openat2/statx indisponível: NÃO é evidência")
            raise

    def patched_statx(self, mutate):
        real = T._sys_statx

        def fake(fd, mask):
            stx = real(fd, mask)
            mutate(stx, mask)
            return stx
        return mock.patch.object(T, "_sys_statx", side_effect=fake)

    def test_required_mask_bit_missing_is_refused(self):
        with self.patched_statx(lambda s, m: setattr(s, "stx_mask", s.stx_mask & ~T.STATX_INO)):
            self.refused("identity_incomplete", self.open_root)
        with self.patched_statx(lambda s, m: setattr(s, "stx_mask", s.stx_mask & ~T.STATX_TYPE)):
            self.refused("identity_incomplete", self.open_root)
        with self.open_root():
            pass  # controle positivo sem mock

    def test_no_mount_id_variant_is_refused(self):
        both = T.STATX_MNT_ID | T.STATX_MNT_ID_UNIQUE
        with self.patched_statx(lambda s, m: setattr(s, "stx_mask", s.stx_mask & ~both)):
            self.refused("identity_incomplete", self.open_root)

    def test_legacy_variant_is_recorded_when_unique_missing(self):
        def drop_unique(stx, mask):
            if mask & T.STATX_MNT_ID_UNIQUE:
                stx.stx_mask &= ~T.STATX_MNT_ID_UNIQUE
        with self.patched_statx(drop_unique) as fake:
            with self.open_root() as root:
                self.assertEqual(root.identity.mnt_id_variant, "legacy")
                self.assertTrue(root.identity.statx_mask & T.STATX_MNT_ID)
            self.assertGreaterEqual(fake.call_count, 2)  # tentou unique, depois legacy

    def test_dev_ino_mismatch_between_statx_and_fstat(self):
        with self.patched_statx(lambda s, m: setattr(s, "stx_ino", s.stx_ino + 1)):
            self.refused("ino_mismatch", self.open_root)
        with self.patched_statx(lambda s, m: setattr(s, "stx_dev_minor", s.stx_dev_minor + 1)):
            self.refused("dev_mismatch", self.open_root)

    def test_statx_syscall_failures(self):
        for err, code in ((errno.ENOSYS, "syscall_unavailable"),
                          (errno.EPERM, "syscall_unavailable"),
                          (errno.EBADF, "invalid_fd")):
            with mock.patch.object(T, "_sys_statx", side_effect=OSError(err, "x")):
                self.refused(code, self.open_root)

    def test_unstable_observation_between_fstat_calls(self):
        real = T._fstat
        calls = []

        def flip(fd):
            st = real(fd)
            calls.append(1)
            if len(calls) < 3:
                return st
            return os.stat_result((st.st_mode, st.st_ino + 5) + tuple(st)[2:])
        # open_synthetic_root usa _fstat no marcador; observe usa duas chamadas.
        fd = T._open_dir(self.anchor, self.name)
        self.addCleanup(os.close, fd)
        T.observe(fd)  # controle positivo
        calls.clear()
        calls.extend([1])  # a próxima chamada do observe será a 2ª, a seguinte a 3ª
        with mock.patch.object(T, "_fstat", side_effect=flip):
            self.refused("unstable_observation", T.observe, fd)

    def test_openat2_failure_mapping(self):
        for err, code in ((errno.EXDEV, "xdev_refused"),       # mountpoint simulado
                          (errno.ELOOP, "symlink_refused"),
                          (errno.ENOENT, "root_missing"),
                          (errno.EAGAIN, "resolution_race"),
                          (errno.EPERM, "syscall_unavailable"),
                          (errno.ENOSYS, "syscall_unavailable"),
                          (errno.EIO, "open_failed")):
            with mock.patch.object(T, "_sys_openat2", side_effect=OSError(err, "x")):
                self.refused(code, self.open_root)
        with self.open_root():
            pass  # controle positivo

    def test_eagain_is_a_fail_closed_resolution_race_without_retry(self):
        with self.open_root():
            pass  # controle positivo: resolução normal
        calls = []

        def racing(dirfd, name, flags):
            calls.append(name)
            raise OSError(errno.EAGAIN, "x")
        before = open_fds()
        with mock.patch.object(T, "_sys_openat2", side_effect=racing):
            self.refused("resolution_race", self.open_root)
            self.refused("resolution_race", T._open_dir, self.anchor, self.name)
        self.assertEqual(len(calls), 2)            # uma chamada por tentativa: sem retry
        self.assertEqual(open_fds(), before)       # nenhum FD concedido
        self.assertEqual(T._OPEN_ERRORS[errno.EAGAIN], "resolution_race")
        self.assertEqual(T._RESOLVE_ALL, T._RESOLVE_NO_XDEV | T._RESOLVE_NO_MAGICLINKS
                         | T._RESOLVE_NO_SYMLINKS | T._RESOLVE_BENEATH)  # flags intactas
        with mock.patch.object(T, "_sys_openat2", side_effect=racing):
            rc, out, err, _ = self._cli_report()
        self.assertEqual(rc, 2)
        report = json.loads(out)
        self.assertEqual((report["result"], report["reason"]), ("REFUSED", "resolution_race"))
        self.assertIs(report["file_operations_authorized"], False)

    def _cli_report(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = T.main(["--synthetic-only", "--json"])
        return rc, out.getvalue(), err.getvalue(), None

    def test_unsupported_platform(self):
        with mock.patch.object(T.sys, "platform", "darwin"):
            self.refused("unsupported_platform", self.open_root)
        with mock.patch.object(T.platform, "machine", return_value="riscv64"):
            self.refused("unsupported_platform", self.open_root)
        fd = T._open_dir(self.anchor, self.name)
        self.addCleanup(os.close, fd)
        with mock.patch.object(T.sys, "platform", "win32"):
            self.refused("unsupported_platform", T.observe, fd)



class CliSubprocessTests(unittest.TestCase):
    """A CLI real em subprocesso, sem mocks."""

    script = os.path.join(HERE, "trusted_root.py")

    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, self.script, *args],
                              capture_output=True, text=True, timeout=60, env=env)

    def test_cli_is_closed_and_never_exits_zero(self):
        proc = self.run_cli("--synthetic-only", "--json")
        self.assertEqual(proc.returncode, 2)
        report = json.loads(proc.stdout)
        self.assertEqual(report["strong"], "UNAVAILABLE")
        self.assertIs(report["agent_execution_authorized"], False)
        self.assertIn(report["result"], ("IDENTITY_OBSERVED_NOT_AUTHORIZED", "REFUSED"))
        self.assertEqual(report["cleanup_failures"], [])
        self.assertEqual(self.run_cli("/etc").returncode, 64)
        self.assertEqual(self.run_cli("--synthetic-only", "--extra").returncode, 64)

    def test_real_fd_exhaustion_is_sanitized_exit_2(self):
        iso = os.path.realpath(tempfile.mkdtemp(prefix="gh-f1-18-iso-"))
        self.addCleanup(shutil.rmtree, iso, ignore_errors=True)
        code = ("import sys, json, resource\nsys.path.insert(0, %r)\n"
                "import trusted_root as T\n"
                "resource.setrlimit(resource.RLIMIT_NOFILE, (3, 3))\n"
                "sys.exit(T.main(['--synthetic-only', '--json']))\n" % HERE)
        proc = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True,
                              text=True, timeout=60, env={"TMPDIR": iso})
        self.assertEqual(proc.returncode, 2)
        report = json.loads(proc.stdout)
        self.assertEqual(report["result"], "REFUSED")
        # mkdtemp sem fd falha como ENOENT ("sem diretório temporário utilizável")
        self.assertIn(report["reason"], ("infrastructure_EMFILE", "infrastructure_ENOENT"))
        # o resíduo, se houver, é declarado e não escondido
        leftovers = os.listdir(iso)
        self.assertEqual(bool(leftovers), "fixture_remove" in report["cleanup_failures"])
        for text in (proc.stdout, proc.stderr):
            self.assertNotIn(iso, text)
            self.assertNotIn("Traceback", text)
        control = subprocess.run([sys.executable, self.script, "--synthetic-only"],
                                 capture_output=True, text=True, timeout=60,
                                 env={"TMPDIR": iso})  # controle positivo, mesmo TMPDIR
        self.assertEqual((control.returncode, control.stdout.strip()),
                         (2, "IDENTITY_OBSERVED_NOT_AUTHORIZED"))

def mkdir_failing_for_root(err=errno.EACCES):
    """os.mkdir que só falha para a pasta-raiz sintética (mkdtemp segue normal)."""
    real = os.mkdir

    def fn(path, *a, **k):
        if os.path.basename(str(path)).startswith(T.SYNTHETIC_PREFIX):
            raise OSError(err, "/secret")
        return real(path, *a, **k)
    return mock.patch.object(T.os, "mkdir", side_effect=fn)


class IsolatedTmpCase(unittest.TestCase):
    """tempdir isolado para contar resíduos de FDs e diretórios."""

    def setUp(self):
        self.iso = os.path.realpath(tempfile.mkdtemp(prefix="gh-f1-18-iso-"))
        self.addCleanup(shutil.rmtree, self.iso, ignore_errors=True)
        patcher = mock.patch.object(tempfile, "tempdir", self.iso)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        before = open_fds()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = T.main(list(args) or ["--synthetic-only", "--json"])
        return rc, out.getvalue(), err.getvalue(), before

    def assert_sanitized(self, out, err, secret=None):
        for text in (out, err):
            self.assertNotIn("Traceback", text)
            self.assertNotIn(self.iso, text)
            if secret:
                self.assertNotIn(secret, text)

    def assert_refused(self, reason, *, leaked_dir=False, **kw):
        rc, out, err, before = self.run_main()
        report = json.loads(out)
        self.assertEqual(rc, 2)
        self.assertEqual((report["result"], report["reason"]), ("REFUSED", reason))
        self.assertIs(report["agent_execution_authorized"], False)
        self.assert_sanitized(out, err, kw.get("secret"))
        self.assertEqual(open_fds(), before)
        self.assertEqual(bool(os.listdir(self.iso)), leaked_dir)
        return report



class CliFaultInjectionTests(IsolatedTmpCase):
    """_run_synthetic/main com falhas injetadas (mocks)."""

    def test_fixture_creation_failure(self):
        with mock.patch.object(T, "make_synthetic_fixture",
                               side_effect=OSError(errno.ENOSPC, "/secret/path")):
            self.assert_refused("infrastructure_ENOSPC", secret="/secret/path")

    def test_partial_fixture_is_removed_when_mkdir_fails(self):
        with mkdir_failing_for_root():
            self.assert_refused("infrastructure_EACCES")  # nenhum diretório sobrou

    def test_open_anchor_failure(self):
        with mock.patch.object(T, "open_anchor", side_effect=OSError(errno.EMFILE, "x")):
            self.assert_refused("infrastructure_EMFILE")

    def test_kernel_call_failures_are_sanitized(self):
        with mock.patch.object(T, "_sys_openat2", side_effect=OSError(errno.EPERM, "/p")):
            self.assert_refused("syscall_unavailable", secret="/p")
        with mock.patch.object(T, "_sys_statx", side_effect=OSError(errno.ENOSYS, "/p")):
            self.assert_refused("syscall_unavailable", secret="/p")

    def test_refusal_codes_pass_through(self):
        with mock.patch.object(T, "open_synthetic_root", side_effect=T.RootRefused("xdev_refused")):
            self.assert_refused("xdev_refused")

    def test_unexpected_exceptions_do_not_leak_details(self):
        with mock.patch.object(T, "observe", side_effect=RuntimeError("/secret/path boom")):
            self.assert_refused("unexpected_failure", secret="/secret/path")
        with mock.patch.object(T, "open_synthetic_root", side_effect=KeyError("/secret/path")):
            self.assert_refused("unexpected_failure", secret="/secret/path")

    def test_anchor_close_failure_is_reported_not_swallowed(self):
        real_open_anchor, real_close, seen = T.open_anchor, os.close, {}

        def tracking_open_anchor(path):
            seen["fd"] = real_open_anchor(path)
            return seen["fd"]

        def failing_close(fd):
            real_close(fd)  # libera de verdade; só a notificação de erro é simulada
            if fd == seen.get("fd") and not seen.get("raised"):
                seen["raised"] = True
                raise OSError(errno.EIO, "/secret/path")
        with mock.patch.object(T, "open_anchor", side_effect=tracking_open_anchor), \
                mock.patch.object(T.os, "close", side_effect=failing_close):
            rc, out, err, before = self.run_main()
        report = json.loads(out)
        self.assertEqual(rc, 2)
        self.assertEqual(report["cleanup_failures"], ["anchor_close"])
        # limpeza falha nunca aparece como sucesso integral
        self.assertEqual(report["result"], "OBSERVED_WITH_CLEANUP_FAILURE")
        self.assert_sanitized(out, err, "/secret/path")
        self.assertEqual(open_fds(), before)

    def test_fixture_removal_failure_is_reported_not_swallowed(self):
        with mock.patch.object(T.shutil, "rmtree", side_effect=OSError(errno.EBUSY, "/secret")):
            rc, out, err, before = self.run_main()
        report = json.loads(out)
        self.assertEqual(rc, 2)
        self.assertEqual(report["cleanup_failures"], ["fixture_remove"])
        self.assertEqual(report["result"], "OBSERVED_WITH_CLEANUP_FAILURE")
        self.assert_sanitized(out, err, "/secret")
        self.assertEqual(len(os.listdir(self.iso)), 1)  # o resíduo é declarado, não escondido

    def test_fixture_creation_and_cleanup_can_both_fail(self):
        # mkdir falha E a remoção da fixture parcial também falha (duas falhas seguidas)
        with mkdir_failing_for_root(), \
                mock.patch.object(T.shutil, "rmtree", side_effect=OSError(errno.EBUSY, "/secret")):
            rc, out, err, before = self.run_main()
        report = json.loads(out)
        self.assertEqual((rc, report["result"], report["reason"]),
                         (2, "REFUSED", "infrastructure_EACCES"))
        self.assertEqual(report["cleanup_failures"], ["fixture_remove"])
        self.assert_sanitized(out, err, "/secret")
        self.assertEqual(open_fds(), before)
        self.assertEqual(len(os.listdir(self.iso)), 1)   # resíduo declarado, não escondido

    def test_marker_write_failure_cleans_up_or_reports(self):
        with mock.patch.object(T.os, "write", side_effect=OSError(errno.EIO, "/secret")):
            self.assert_refused("infrastructure_EIO", secret="/secret")  # limpou tudo
        with mock.patch.object(T.os, "write", side_effect=OSError(errno.EIO, "/secret")), \
                mock.patch.object(T.shutil, "rmtree", side_effect=OSError(errno.EBUSY, "x")):
            rc, out, err, before = self.run_main()
        report = json.loads(out)
        self.assertEqual((report["reason"], report["cleanup_failures"]),
                         ("infrastructure_EIO", ["fixture_remove"]))
        self.assertEqual(open_fds(), before)             # o FD do marcador foi fechado
        self.assertEqual(len(os.listdir(self.iso)), 1)

    def test_short_marker_write_is_a_failure(self):
        with mock.patch.object(T.os, "write", return_value=1):
            self.assert_refused("infrastructure_EIO")

    def test_direct_fixture_error_carries_only_codes(self):
        with mkdir_failing_for_root(), \
                mock.patch.object(T.shutil, "rmtree", side_effect=OSError(errno.EBUSY, "x")):
            with self.assertRaises(T.FixtureSetupError) as caught:
                T.make_synthetic_fixture()
        self.assertEqual((caught.exception.reason, caught.exception.cleanup_failures),
                         ("infrastructure_EACCES", ["fixture_remove"]))
        self.assertNotIn(self.iso, str(caught.exception))
        parent, name = T.make_synthetic_fixture()          # controle positivo
        self.assertEqual(T._remove_fixture(parent), [])
        self.assertFalse(os.path.lexists(parent))

    def test_root_close_failure_is_reported(self):
        real_close = T.OpenedRoot.close

        def failing(self_):
            real_close(self_)
            raise OSError(errno.EIO, "/secret")
        with mock.patch.object(T.OpenedRoot, "close", failing):
            rc, out, err, before = self.run_main()
        report = json.loads(out)
        self.assertEqual((rc, report["cleanup_failures"], report["result"]),
                         (2, ["root_close"], "OBSERVED_WITH_CLEANUP_FAILURE"))
        self.assert_sanitized(out, err, "/secret")
        self.assertEqual(open_fds(), before)

    def test_several_cleanup_failures_are_all_reported(self):
        real_open_anchor, real_close, seen = T.open_anchor, os.close, {}

        def tracking(path):
            seen["fd"] = real_open_anchor(path)
            return seen["fd"]

        def failing_close(fd):
            real_close(fd)
            if fd == seen.get("fd"):
                raise OSError(errno.EIO, "x")
        with mock.patch.object(T, "open_anchor", side_effect=tracking), \
                mock.patch.object(T.os, "close", side_effect=failing_close), \
                mock.patch.object(T.shutil, "rmtree", side_effect=OSError(errno.EBUSY, "x")):
            rc, out, err, before = self.run_main()
        report = json.loads(out)
        self.assertEqual(report["cleanup_failures"], ["anchor_close", "fixture_remove"])
        self.assertEqual(report["result"], "OBSERVED_WITH_CLEANUP_FAILURE")

    def test_incoherent_report_is_replaced_by_a_refusal(self):
        with mock.patch.object(T, "check_root_report", side_effect=[ValueError("x"), None]) as chk:
            chk.side_effect = [ValueError("x"), {"ok": True}]
            report = T._run_synthetic()
        self.assertEqual(report, {"ok": True})
        self.assertEqual(chk.call_count, 2)

    def test_text_mode_reports_cleanup_failures(self):
        with mock.patch.object(T.shutil, "rmtree", side_effect=OSError(errno.EBUSY, "x")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = T.main(["--synthetic-only"])
        self.assertEqual(rc, 2)
        self.assertEqual(out.getvalue().strip(),
                         "OBSERVED_WITH_CLEANUP_FAILURE; cleanup_failures=fixture_remove")

class CleanupRealTests(IsolatedTmpCase):
    """Sistema de arquivos e descritores reais, sem mocks."""

    def test_positive_control_leaves_no_descriptors_or_directories(self):
        rc, out, err, before = self.run_main()
        report = json.loads(out)
        self.assertEqual(rc, 2)
        self.assertEqual(report["result"], "IDENTITY_OBSERVED_NOT_AUTHORIZED")
        self.assertEqual(report["cleanup_failures"], [])
        self.assertEqual(open_fds(), before)
        self.assertEqual(os.listdir(self.iso), [])

    def test_invalid_usage_is_64(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(T.main([]), 64)
            self.assertEqual(T.main(["--json"]), 64)

    def test_cleanup_only_removes_fixtures_made_by_this_module(self):
        other = os.path.join(self.iso, "important-dir")
        os.mkdir(other)
        self.assertEqual(T._remove_fixture(other), ["fixture_remove"])      # nome errado
        self.assertTrue(os.path.isdir(other))
        elsewhere = os.path.join(self.iso, "sub")
        os.mkdir(elsewhere)
        lookalike = os.path.join(elsewhere, "gh-f1-18-fixture-fake")
        os.mkdir(lookalike)
        self.assertEqual(T._remove_fixture(lookalike), ["fixture_remove"])  # pai errado
        self.assertTrue(os.path.isdir(lookalike))
        victim = os.path.join(self.iso, "victim")
        os.mkdir(victim)
        link = os.path.join(self.iso, "gh-f1-18-fixture-link")
        os.symlink(victim, link)
        self.assertEqual(T._remove_fixture(link), ["fixture_remove"])       # symlink
        self.assertTrue(os.path.isdir(victim))
        for bad in (None, 7, b"x", ""):
            self.assertEqual(T._remove_fixture(bad), ["fixture_remove"])


class PureMockTests(unittest.TestCase):
    """Sem syscalls: apenas lógica."""

    def refused(self, code, fn, *args):
        with self.assertRaises(T.RootRefused) as caught:
            fn(*args)
        self.assertEqual(caught.exception.code, code)

    def test_compare_rules(self):
        base = T.RootIdentity(1, 2, 3, "unique", "mnt:[1]", 0x1100)
        T.compare(base, base)
        for change, code in (({"mnt_id_variant": "legacy"}, "variant_not_comparable"),
                             ({"mnt_ns": "mnt:[2]"}, "mount_namespace_changed"),
                             ({"mnt_ns": None}, "mount_namespace_unknown"),
                             ({"dev": 9}, "identity_diverged"),
                             ({"ino": 9}, "identity_diverged"),
                             ({"mnt_id": 9}, "identity_diverged")):
            self.refused(code, T.compare, base, dc.replace(base, **change))
        self.refused("mount_namespace_unknown", T.compare, dc.replace(base, mnt_ns=None), base)
        self.refused("invalid_identity", T.compare, base, {"dev": 1})
        self.refused("invalid_identity", T.compare, None, base)

    def test_check_root_report_rejects_contradictions(self):
        ok = T._refused_report("x", ["fixture_remove"])
        T.check_root_report(ok)
        observed = {**T.INVARIANTS, "schema": "trusted-root-diagnostic/1",
                    "result": "IDENTITY_OBSERVED_NOT_AUTHORIZED", "synthetic_only": True,
                    "cleanup_failures": []}
        T.check_root_report(observed)
        T.check_root_report({**observed, "result": "OBSERVED_WITH_CLEANUP_FAILURE",
                             "cleanup_failures": ["anchor_close"]})
        bad_cases = [
            {"cleanup_failures": ["fixture_remove"]},               # sucesso integral com falha
            {"result": "OBSERVED_WITH_CLEANUP_FAILURE"},             # falha sem código
            {"result": "TRUSTED"}, {"result": None},
            {"cleanup_failures": ["/home/x"]},                      # código não sanitizado
            {"cleanup_failures": ["fixture_remove", "anchor_close"]},  # fora de ordem
            {"cleanup_failures": "none"}, {"cleanup_failures": None},
            {"reason": "x"},                                         # reason sem REFUSED
            {"synthetic_only": False},
            {"inventory_effectively_complete": True},
            {"unobserved_capabilities_excluded": 1},
            {"bootstrap_complete": "false"},
        ]
        for change in bad_cases:
            with self.assertRaises(ValueError, msg=change):
                T.check_root_report({**observed, **change})
        with self.assertRaises(ValueError):
            T.check_root_report({**ok, "reason": 7})
        missing = dict(observed)
        del missing["cleanup_failures"]
        for junk in (missing, None, [], "x"):
            with self.assertRaises(ValueError):
                T.check_root_report(junk)

    def test_check_report_validates_new_completeness_fields_only_when_present(self):
        base = {**T.INVARIANTS}
        T.check_report(base)                                   # ausentes: não exigidos
        T.check_report({**base, "inventory_effectively_complete": False,
                        "unobserved_capabilities_excluded": False})
        for key in ("inventory_effectively_complete", "unobserved_capabilities_excluded"):
            for value in (True, 1, 0, "false", None, [], 0.0):
                with self.assertRaises(ValueError, msg=(key, value)):
                    T.check_report({**base, key: value})

    def test_invariants_are_read_only_constants(self):
        self.assertEqual(dict(T.INVARIANTS), {
            "strong": "UNAVAILABLE", "readiness": "BLOCKED",
            "agent_execution_authorized": False, "file_operations_authorized": False,
            "cloud_call_authorized": False, "data_transfer_authorized": False})
        with self.assertRaises(TypeError):
            T.INVARIANTS["strong"] = "STRONG"
        with self.assertRaises(TypeError):
            T.INVARIANTS["agent_execution_authorized"] = True
        self.assertEqual(platform.system(), "Linux")

    def test_check_report_rejects_tampered_or_mistyped_reports(self):
        good = {**T.INVARIANTS, "result": "x"}
        T.check_report(good)
        for key, value in (("agent_execution_authorized", True),
                           ("agent_execution_authorized", 0),
                           ("file_operations_authorized", "false"),
                           ("cloud_call_authorized", None),
                           ("data_transfer_authorized", 1),
                           ("strong", "STRONG"), ("readiness", "READY"),
                           ("owner_authenticated", True), ("bootstrap_trusted", True)):
            with self.assertRaises(ValueError, msg=(key, value)):
                T.check_report({**good, key: value})
        for junk in (None, [], "x", {"strong": "UNAVAILABLE"}):
            with self.assertRaises(ValueError):
                T.check_report(junk)

    def test_describe_and_refused_reports_keep_the_invariants(self):
        refused = T._refused_report("whatever", ["fixture_remove", "anchor_close"])
        self.assertEqual(refused["cleanup_failures"], ["anchor_close", "fixture_remove"])
        self.assertEqual(refused["strong"], "UNAVAILABLE")
        ident = T.RootIdentity(1, 2, 3, "unique", "mnt:[1]", 0x1100)
        report = T.OpenedRoot(None, ident).describe()
        self.assertIs(report["owner_authenticated"], False)
        self.assertEqual(report["identity_scope"], "comparison_only")


if __name__ == "__main__":
    unittest.main()
