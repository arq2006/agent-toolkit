#!/usr/bin/env python3
"""Regression tests for the read-only executor: synthetic temporary fixtures only."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import pathguard
import readonly_executor as E


class ReadonlyExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="readonly-exec-test-"))
        self.root = os.path.join(self.tmp, "authorized")
        self.outside = os.path.join(self.tmp, "external")
        os.mkdir(self.root, 0o700)
        os.mkdir(self.outside, 0o700)
        with open(os.path.join(self.root, "inside.txt"), "w", encoding="utf-8") as f:
            f.write("FICTIONAL-ALLOWED")
        with open(os.path.join(self.outside, "outside.txt"), "w", encoding="utf-8") as f:
            f.write("FICTIONAL-EXTERNAL")
        os.mkdir(os.path.join(self.root, "sub"))
        self.fd = pathguard.open_root(self.root)

    def tearDown(self):
        os.close(self.fd)
        shutil.rmtree(self.tmp)

    def request(self, **payload):
        return E.dispatch_json(self.fd, json.dumps(payload).encode("utf-8"))

    def assert_denied(self, raw, code=None):
        with self.assertRaises(E.RequestDenied) as cm:
            E.dispatch_json(self.fd, raw)
        if code:
            self.assertEqual(str(cm.exception), code)

    def test_read_text_in_authorized_root(self):
        self.assertEqual(
            self.request(op="read", path="inside.txt"),
            {"ok": True, "op": "read", "text": "FICTIONAL-ALLOWED"},
        )

    def test_list_root_and_nested(self):
        self.assertEqual(
            self.request(op="list"),
            {"ok": True, "op": "list", "entries": ["inside.txt", "sub"]},
        )
        self.assertEqual(
            self.request(op="list", path="sub"),
            {"ok": True, "op": "list", "entries": []},
        )

    def test_reject_path_traversal_and_absolute(self):
        for path in ("../external/outside.txt", "/etc/passwd", "./inside.txt",
                     "sub/../inside.txt", "sub//inside.txt", "", "sub\\inside.txt"):
            self.assert_denied(
                json.dumps({"op": "read", "path": path}).encode(),
                "invalid_path",
            )

    def test_reject_write_exec_network_and_extra_fields(self):
        for op in ("write", "edit", "bash", "exec", "network", "delete", "glob"):
            self.assert_denied(
                json.dumps({"op": op, "path": "inside.txt"}).encode(),
                "operation_denied",
            )
        self.assert_denied(b'{"op":"read","path":"inside.txt","shell":true}', "invalid_fields")
        self.assert_denied(b'{"op":"list","allowOutside":true}', "invalid_fields")
        self.assertEqual(os.listdir(self.outside), ["outside.txt"])

    def test_invalid_json_duplicate_keys_and_nonfinite(self):
        self.assert_denied(b'{"op":"read","op":"read","path":"inside.txt"}', "duplicate_key")
        self.assert_denied(b'{"op":"read","path":"inside.txt","unused":{"x":1,"x":2}}',
                           "duplicate_key")
        self.assert_denied(b'{"op":"read","path":"inside.txt","x":NaN}', "invalid_json")
        self.assert_denied(b'{"op":"read","path":"inside.txt",}', "invalid_json")
        self.assert_denied(b'\xff\xfe', "invalid_json")

    def test_json_surrogates_rejected_before_filesystem(self):
        # JSON permite escapes Unicode sem par valido; no Arch/Linux,
        # os.open normalmente lançaria UnicodeEncodeError.
        for raw in (
            b'{"op":"read","path":"\\ud800"}',
            b'{"op":"list","path":"\\udfff"}',
            b'{"op":"read","path":"sub/\\ud800/file.txt"}',
        ):
            self.assert_denied(raw, "invalid_path")
        for path in ("\ud800", "\udfff", "sub/\ud800"):
            with self.assertRaises(E.RequestDenied) as cm:
                E.dispatch(self.fd, {"op": "read", "path": path})
            self.assertEqual(str(cm.exception), "invalid_path")

    def test_scan_streams_wide_tree_and_fails_closed(self):
        for i in range(64):
            os.mkdir(os.path.join(self.root, f"dir-{i:03d}"))
        with mock.patch.object(pathguard.os, "listdir",
                               side_effect=AssertionError("listdir materializou diretório")):
            with mock.patch.object(E, "MAX_SCAN_ENTRIES", 10):
                self.assert_denied(b'{"op":"read","path":"inside.txt"}', "path_denied")

    def test_deep_tree_rejected_without_leaking_fd(self):
        parent = self.root
        for _ in range(65):
            parent = os.path.join(parent, "d")
            os.mkdir(parent)
        before = len(os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else None
        self.assert_denied(b'{"op":"read","path":"inside.txt"}', "path_denied")
        if before is not None:
            self.assertLessEqual(len(os.listdir("/proc/self/fd")), before + 2)

    def test_types_and_sizes_fail_closed(self):
        for raw in (b"", b"[]", b"null", b"true", b"1", b'{"op":12}',
                    b'{"op":"read","path":1}', b'{"op":"list","path":null}'):
            self.assert_denied(raw)
        with self.assertRaises(E.RequestDenied):
            E.parse_request('{"op":"list"}')
        with self.assertRaises(E.RequestDenied):
            E.parse_request(b"x" * (E.MAX_REQUEST_BYTES + 1))

    def test_symlink_to_external_blocks_entire_tree(self):
        os.symlink(os.path.join(self.outside, "outside.txt"),
                   os.path.join(self.root, "alias"))
        self.assert_denied(b'{"op":"read","path":"inside.txt"}', "unsafe_tree")

    def test_hardlink_to_external_blocks_entire_tree(self):
        os.link(os.path.join(self.outside, "outside.txt"),
                os.path.join(self.root, "alias"))
        self.assert_denied(b'{"op":"read","path":"inside.txt"}', "unsafe_tree")
        with open(os.path.join(self.outside, "outside.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "FICTIONAL-EXTERNAL")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unsupported")
    def test_special_file_blocks_entire_tree(self):
        os.mkfifo(os.path.join(self.root, "pipe"))
        self.assert_denied(b'{"op":"list"}', "unsafe_tree")

    def test_reading_binary_or_too_large_is_denied(self):
        with open(os.path.join(self.root, "binary.bin"), "wb") as f:
            f.write(b"\xff\xff")
        self.assert_denied(b'{"op":"read","path":"binary.bin"}', "invalid_encoding")
        with open(os.path.join(self.root, "large.txt"), "wb") as f:
            f.write(b"x" * (E.MAX_READ_BYTES + 1))
        self.assert_denied(b'{"op":"read","path":"large.txt"}', "path_denied")

    def test_tree_size_limit_fail_closed(self):
        with mock.patch.object(E, "MAX_SCAN_ENTRIES", 1):
            self.assert_denied(b'{"op":"read","path":"inside.txt"}', "path_denied")

    def test_list_size_limit(self):
        with mock.patch.object(E, "MAX_LIST_ENTRIES", 1):
            self.assert_denied(b'{"op":"list"}', "too_many_entries")

    def test_fd_must_be_real_directory_int(self):
        for invalid in (None, True, False, "42", -1):
            with self.assertRaises(E.RequestDenied):
                E.dispatch(invalid, {"op": "read", "path": "inside.txt"})
        file_fd = os.open(os.path.join(self.root, "inside.txt"), os.O_RDONLY)
        try:
            with self.assertRaises(E.RequestDenied) as cm:
                E.dispatch(file_fd, {"op": "list"})
            self.assertEqual(str(cm.exception), "invalid_root")
        finally:
            os.close(file_fd)

    def test_dispatch_revalidates_request_without_json(self):
        for bad in ({"op": "read"}, {"op": "read", "path": "/etc/passwd"},
                    {"op": "list", "path": "."}, {"op": "list", "path": 1},
                    {"op": "read", "path": "inside.txt", "overwrite": True}):
            with self.assertRaises(E.RequestDenied):
                E.dispatch(self.fd, bad)

    def test_each_call_rechecks_tree(self):
        self.request(op="read", path="inside.txt")
        alias = os.path.join(self.root, "external-hardlink.txt")
        os.link(os.path.join(self.outside, "outside.txt"), alias)
        self.assert_denied(b'{"op":"read","path":"inside.txt"}', "unsafe_tree")
        os.unlink(alias)
        self.assertEqual(self.request(op="read", path="inside.txt")["ok"], True)


if __name__ == "__main__":
    unittest.main()
