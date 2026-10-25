#!/usr/bin/env python3
"""Fixtures temporárias e regressões do guard experimental openat2."""
import ctypes
import errno
import os
import shutil
import stat
import tempfile
import unittest
from unittest import mock

import pathguard
import linux_openat2_guard as G


class Openat2GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="openat2-test-"))
        self.root = os.path.join(self.tmp, "authorized")
        self.other = os.path.join(self.tmp, "outside")
        os.mkdir(self.root, 0o700)
        os.mkdir(self.other, 0o700)
        with open(os.path.join(self.root, "inside.txt"), "w") as f:
            f.write("FICTIONAL-OK")
        with open(os.path.join(self.other, "secret.txt"), "w") as f:
            f.write("FICTIONAL-SECRET")
        os.mkdir(os.path.join(self.root, "sub"))
        with open(os.path.join(self.root, "sub", "nested.txt"), "w") as f:
            f.write("NESTED")
        self.fd = pathguard.open_root(self.root)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(os.close, self.fd)

    def require_kernel(self):
        try:
            G.read_bytes(self.fd, "inside.txt")
        except G.Openat2Denied as e:
            if str(e) in ("syscall_unavailable", "unsupported_platform"):
                self.skipTest("openat2 não permitido/suportado neste ambiente")
            raise

    def denied(self, path, code=None):
        with self.assertRaises(G.Openat2Denied) as caught:
            G.read_bytes(self.fd, path)
        if code:
            self.assertEqual(str(caught.exception), code)

    def test_kernel_positive_read_and_nested_file(self):
        self.require_kernel()
        self.assertEqual(G.read_text(self.fd, "inside.txt"), "FICTIONAL-OK")
        self.assertEqual(G.read_text(self.fd, "sub/nested.txt"), "NESTED")

    def test_kernel_positive_list_root_and_nested(self):
        self.require_kernel()
        self.assertEqual(G.list_dir(self.fd), ["inside.txt", "sub"])
        self.assertEqual(G.list_dir(self.fd, "sub"), ["nested.txt"])

    def test_symlink_to_external_rejected_by_kernel(self):
        self.require_kernel()
        os.symlink(os.path.join(self.other, "secret.txt"), os.path.join(self.root, "shortcut"))
        self.denied("shortcut", "path_denied")

    def test_symlink_parent_rejected_by_kernel(self):
        self.require_kernel()
        os.symlink(self.other, os.path.join(self.root, "external_dir"))
        self.denied("external_dir/secret.txt", "path_denied")

    def test_hardlink_to_external_rejected_by_inode_guard(self):
        self.require_kernel()
        try:
            os.link(os.path.join(self.other, "secret.txt"), os.path.join(self.root, "hardlink.txt"))
        except OSError:
            self.skipTest("filesystem não permite hardlink sintético")
        self.denied("hardlink.txt", "unsafe_file")
        # Um hardlink na árvore não bloqueia outras leituras nesse guard per-path.
        self.assertEqual(G.read_text(self.fd, "inside.txt"), "FICTIONAL-OK")

    def test_invalid_paths_denied_without_kernel_access(self):
        for rel in ("../outside/secret.txt", "/etc/passwd", "sub/../inside.txt",
                    "./inside.txt", "sub//nested.txt", "", "a\x00b", "x\\y",
                    "\ud800"):
            with mock.patch.object(G, "_sys_openat2",
                                   side_effect=AssertionError("kernel não deve ser invocado")):
                self.denied(rel, "invalid_path")

    def test_root_fd_must_be_integer_directory(self):
        for bad in (None, False, True, "3", -1):
            with self.assertRaises(G.Openat2Denied):
                G.read_bytes(bad, "inside.txt")
        file_fd = os.open(os.path.join(self.root, "inside.txt"), os.O_RDONLY)
        try:
            with self.assertRaises(G.Openat2Denied):
                G.read_bytes(file_fd, "inside.txt")
        finally:
            os.close(file_fd)

    def test_missing_syscall_has_no_fallback(self):
        with mock.patch.object(G, "_sys_openat2",
                               side_effect=G.Openat2Denied("syscall_unavailable")):
            self.denied("inside.txt", "syscall_unavailable")

    def test_other_platform_and_arch_rejected_without_syscall(self):
        with mock.patch.object(G.sys, "platform", "darwin"):
            with mock.patch.object(G, "_sys_openat2",
                                   side_effect=AssertionError("kernel chamado")):
                self.denied("inside.txt", "unsupported_platform")
        with mock.patch.object(G.platform, "machine", return_value="i386"):
            with mock.patch.object(G, "_sys_openat2",
                                   side_effect=AssertionError("kernel chamado")):
                self.denied("inside.txt", "unsupported_platform")

    def test_restrictive_kernel_flags_are_passed_unconditionally(self):
        record = {}
        class FakeSyscall:
            restype = None
            def __call__(self, nr, fd, path, howptr, size):
                how = ctypes.cast(howptr, ctypes.POINTER(G._OpenHow)).contents
                record["number"] = nr.value
                record["resolve"] = how.resolve
                record["flags"] = how.flags
                record["size"] = size.value
                ctypes.set_errno(errno.EXDEV)
                return -1
        with mock.patch.object(G.ctypes, "CDLL", return_value=type("Lib", (), {
            "syscall": FakeSyscall()
        })()):
            self.denied("inside.txt", "path_denied")
        self.assertEqual(record["number"], 437)
        self.assertEqual(record["resolve"], 0x0F)
        self.assertTrue(record["flags"] & os.O_NOFOLLOW)
        self.assertTrue(record["flags"] & os.O_CLOEXEC)
        self.assertEqual(record["size"], ctypes.sizeof(G._OpenHow))

    def test_no_fallback_on_errno_enosys_eperm_einval(self):
        for number in (errno.ENOSYS, errno.EPERM, errno.EINVAL):
            class FakeSyscall:
                restype = None
                def __call__(self, *unused):
                    ctypes.set_errno(number)
                    return -1
            with mock.patch.object(G.ctypes, "CDLL",
                                   return_value=type("Lib", (), {"syscall": FakeSyscall()})()):
                self.denied("inside.txt", "syscall_unavailable")

    def test_nonregular_and_oversized_file_denied(self):
        self.require_kernel()
        with open(os.path.join(self.root, "large.txt"), "wb") as out:
            out.write(b"x" * 100)
        with self.assertRaises(G.Openat2Denied) as e:
            G.read_bytes(self.fd, "large.txt", max_bytes=64)
        self.assertEqual(str(e.exception), "too_large")
        os.mkfifo(os.path.join(self.root, "fifo"))
        self.denied("fifo", "unsafe_file")

    def test_invalid_size_limits_fail_closed(self):
        for limit in (0, 65537, -1, True, "10"):
            with self.assertRaises(G.Openat2Denied):
                G.read_bytes(self.fd, "inside.txt", max_bytes=limit)
        for limit in (0, 1025, -1, True, "10"):
            with self.assertRaises(G.Openat2Denied):
                G.list_dir(self.fd, max_entries=limit)

    def test_directory_listing_limit_is_enforced_during_iteration(self):
        self.require_kernel()
        with self.assertRaises(G.Openat2Denied) as e:
            G.list_dir(self.fd, max_entries=1)
        self.assertEqual(str(e.exception), "too_many_entries")

    def test_no_file_descriptor_leak_on_success_or_failure(self):
        self.require_kernel()
        before = len(os.listdir("/proc/self/fd"))
        for _ in range(15):
            self.assertEqual(G.read_bytes(self.fd, "inside.txt"), b"FICTIONAL-OK")
            self.denied("nope.txt", "path_denied")
            G.list_dir(self.fd)
        self.assertLessEqual(len(os.listdir("/proc/self/fd")), before + 1)


if __name__ == "__main__":
    unittest.main()
