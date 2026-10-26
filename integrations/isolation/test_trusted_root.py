#!/usr/bin/env python3
"""Testes de trusted_root: identidade de raiz sintética (GH-F1.18/PR-B).

Duas classes distintas:
- KernelTests: chamam openat2/statx REAIS do kernel sobre fixtures em /tmp.
  Um skipTest por syscall indisponível NÃO é evidência positiva.
- MockTests: provam a lógica do programa com falhas injetadas; não provam o
  comportamento do kernel.
Nenhum mount, namespace, sudo ou caminho real é usado.
"""
import ctypes
import errno
import json
import os
import platform
import shutil
import subprocess
import sys
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

    def test_cli_is_closed_and_never_exits_zero(self):
        proc = subprocess.run([sys.executable, os.path.join(HERE, "trusted_root.py"),
                               "--synthetic-only", "--json"],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2)
        report = json.loads(proc.stdout)
        self.assertEqual(report["strong"], "UNAVAILABLE")
        self.assertIs(report["agent_execution_authorized"], False)
        self.assertIn(report["result"], ("IDENTITY_OBSERVED_NOT_AUTHORIZED", "REFUSED"))
        bad = subprocess.run([sys.executable, os.path.join(HERE, "trusted_root.py"),
                              "/etc"], capture_output=True, text=True, timeout=30)
        self.assertEqual(bad.returncode, 64)


class MockTests(FixtureCase):
    """Falhas injetadas: a lógica do programa, não o kernel."""

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
                          (errno.EPERM, "syscall_unavailable"),
                          (errno.ENOSYS, "syscall_unavailable"),
                          (errno.EIO, "open_failed")):
            with mock.patch.object(T, "_sys_openat2", side_effect=OSError(err, "x")):
                self.refused(code, self.open_root)
        with self.open_root():
            pass  # controle positivo

    def test_unsupported_platform(self):
        with mock.patch.object(T.sys, "platform", "darwin"):
            self.refused("unsupported_platform", self.open_root)
        with mock.patch.object(T.platform, "machine", return_value="riscv64"):
            self.refused("unsupported_platform", self.open_root)
        fd = T._open_dir(self.anchor, self.name)
        self.addCleanup(os.close, fd)
        with mock.patch.object(T.sys, "platform", "win32"):
            self.refused("unsupported_platform", T.observe, fd)

    def test_compare_rules(self):
        base = T.RootIdentity(1, 2, 3, "unique", "mnt:[1]", 0x1100)
        T.compare(base, base)
        import dataclasses as dc
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

    def test_invariants_are_constants(self):
        self.assertEqual(T.INVARIANTS, {
            "strong": "UNAVAILABLE", "readiness": "BLOCKED",
            "agent_execution_authorized": False, "file_operations_authorized": False,
            "cloud_call_authorized": False, "data_transfer_authorized": False})
        self.assertEqual(platform.system(), "Linux")


if __name__ == "__main__":
    unittest.main()
