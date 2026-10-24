#!/usr/bin/env python3
"""Testes do pathguard. Só diretórios temporários fictícios; sem rede, shell nem credenciais.

Executar: python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
"""
import os, pwd, shutil, tempfile, unittest
from unittest import mock

import pathguard as P


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="pg-test-"))
        self.root = os.path.join(self.tmp, "auth")
        self.outside = os.path.join(self.tmp, "outside")
        os.mkdir(self.root); os.mkdir(self.outside)
        with open(os.path.join(self.outside, "secret.txt"), "w") as f:
            f.write("FICTICIO-FORA")
        with open(os.path.join(self.root, "a.txt"), "w") as f:
            f.write("ola")
        os.mkdir(os.path.join(self.root, "sub"))
        self.fd = P.open_root(self.root)

    @staticmethod
    def text(path):
        with open(path) as f:
            return f.read()

    def tearDown(self):
        os.close(self.fd)
        shutil.rmtree(self.tmp, ignore_errors=True)


class RelPath(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(P.split_relpath("a/b/c.txt"), ("a", "b", "c.txt"))

    def test_rejects(self):
        for bad in ["", "/etc/passwd", "../x", "a/../b", "a/./b", "a//b", "a/", "a\x00b",
                    "a\\b", "C:x", ".", "..", "x" * 300, "a/" + "y" * 256, "z" * 5000, None, 3]:
            with self.assertRaises(P.PathGuardError, msg=repr(bad)[:40]):
                P.split_relpath(bad)


class ReadWrite(Base):
    def test_read_ok(self):
        self.assertEqual(P.read_bytes(self.fd, "a.txt"), b"ola")

    def test_create_and_overwrite(self):
        P.write_bytes(self.fd, "sub/n.txt", b"1")
        self.assertEqual(P.read_bytes(self.fd, "sub/n.txt"), b"1")
        with self.assertRaises(P.PathGuardError):
            P.write_bytes(self.fd, "sub/n.txt", b"2")  # sem overwrite
        P.write_bytes(self.fd, "sub/n.txt", b"22", overwrite=True)
        self.assertEqual(P.read_bytes(self.fd, "sub/n.txt"), b"22")
        self.assertEqual(oct(os.stat(os.path.join(self.root, "sub/n.txt")).st_mode & 0o777), "0o600")

    def test_overwrite_must_be_exact_bool(self):
        for bad in ("false", "true", "", 1, 0, None, 1.0, [], [True], {}, b"x", object()):
            with self.assertRaises(P.PathGuardError, msg=repr(bad)):
                P.write_bytes(self.fd, "a.txt", b"SOBRESCRITO", overwrite=bad)
            self.assertEqual(P.read_bytes(self.fd, "a.txt"), b"ola")
        with self.assertRaises(P.PathGuardError):  # nada é criado com overwrite inválido
            P.write_bytes(self.fd, "novo.txt", b"x", overwrite="false")
        self.assertFalse(os.path.exists(os.path.join(self.root, "novo.txt")))
        with self.assertRaises(P.PathGuardError):  # overwrite=False continua recusando existente
            P.write_bytes(self.fd, "a.txt", b"x", overwrite=False)
        P.write_bytes(self.fd, "a.txt", b"novo", overwrite=True)
        self.assertEqual(P.read_bytes(self.fd, "a.txt"), b"novo")

    def test_missing_parent_not_created(self):
        with self.assertRaises(P.PathGuardError):
            P.write_bytes(self.fd, "nope/x.txt", b"1")
        self.assertFalse(os.path.exists(os.path.join(self.root, "nope")))

    def test_symlink_final_rejected(self):
        os.symlink(os.path.join(self.outside, "secret.txt"), os.path.join(self.root, "ln"))
        with self.assertRaises(P.PathGuardError):
            P.read_bytes(self.fd, "ln")
        with self.assertRaises(P.PathGuardError):
            P.write_bytes(self.fd, "ln", b"x", overwrite=True)
        self.assertEqual(self.text(os.path.join(self.outside, "secret.txt")), "FICTICIO-FORA")

    def test_symlink_middle_rejected(self):
        os.symlink(self.outside, os.path.join(self.root, "dl"))
        with self.assertRaises(P.PathGuardError):
            P.read_bytes(self.fd, "dl/secret.txt")
        with self.assertRaises(P.PathGuardError):
            P.write_bytes(self.fd, "dl/new.txt", b"x")
        self.assertFalse(os.path.exists(os.path.join(self.outside, "new.txt")))

    def test_dangling_symlink_create_rejected(self):
        os.symlink(os.path.join(self.outside, "novo"), os.path.join(self.root, "dang"))
        with self.assertRaises(P.PathGuardError):
            P.write_bytes(self.fd, "dang", b"x")
        self.assertFalse(os.path.exists(os.path.join(self.outside, "novo")))

    def test_hardlink_rejected_before_truncate(self):
        target = os.path.join(self.outside, "secret.txt")
        os.link(target, os.path.join(self.root, "hl"))
        with self.assertRaises(P.PathGuardError):
            P.read_bytes(self.fd, "hl")
        with self.assertRaises(P.PathGuardError):
            P.write_bytes(self.fd, "hl", b"x", overwrite=True)
        self.assertEqual(self.text(target), "FICTICIO-FORA")  # não truncado

    def test_special_and_dir_rejected(self):
        os.mkfifo(os.path.join(self.root, "fifo"))
        for rel in ("fifo", "sub"):
            with self.assertRaises(P.PathGuardError):
                P.read_bytes(self.fd, rel)
        with self.assertRaises(P.PathGuardError):
            P.write_bytes(self.fd, "fifo", b"x", overwrite=True)

    def test_limits(self):
        with open(os.path.join(self.root, "big"), "wb") as f:
            f.write(b"x" * 100)
        with self.assertRaises(P.PathGuardError):
            P.read_bytes(self.fd, "big", max_bytes=10)
        with self.assertRaises(P.PathGuardError):
            P.write_bytes(self.fd, "w", b"x" * 100, max_bytes=10)
        with self.assertRaises(P.PathGuardError):
            P.write_bytes(self.fd, "w", "texto")

    def test_missing_file(self):
        with self.assertRaises(P.PathGuardError):
            P.read_bytes(self.fd, "nao-existe")

    def test_list_dir(self):
        self.assertEqual(P.list_dir(self.fd), ["a.txt", "sub"])
        self.assertEqual(P.list_dir(self.fd, "sub"), [])
        os.symlink(self.outside, os.path.join(self.root, "dl"))
        with self.assertRaises(P.PathGuardError):
            P.list_dir(self.fd, "dl")


class Root(Base):
    def test_root_requirements(self):
        link = os.path.join(self.tmp, "rootlink")
        os.symlink(self.root, link)
        for bad in ["relativo", link, os.path.join(self.root, "a.txt"), self.root + "/../auth",
                    os.path.join(self.tmp, "inexistente"), "x\x00y", None]:
            with self.assertRaises(P.PathGuardError, msg=repr(bad)):
                P.open_root(bad)

    def test_nul_refused_for_nul(self):
        # caminhos absolutos e existentes até o NUL: a recusa só pode ser pelo NUL
        with self.assertRaises(P.PathGuardError) as cm:
            P.open_root(self.root + "\x00/x")
        self.assertIn("caminho textual válido", str(cm.exception))
        with self.assertRaises(P.PathGuardError) as cm:
            P.check_authorized_path(self.root + "\x00")
        self.assertIn("caminho textual válido", str(cm.exception))
        with self.assertRaises(P.PathGuardError) as cm:
            P.read_bytes(self.fd, "a.txt\x00")
        self.assertIn("NUL", str(cm.exception))
        with self.assertRaises(P.PathGuardError) as cm:
            P.write_bytes(self.fd, "sub/n\x00.txt", b"x")
        self.assertIn("NUL", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.root, "sub", "n")))

    def test_root_slash_and_unnormalized_refused(self):
        for bad in ["/", "//", "//x", self.root + "/", self.root + "//", self.root + "/.",
                    self.root + "/./", "/" + "a" * 300, ""]:
            with self.assertRaises(P.PathGuardError, msg=repr(bad)):
                P.open_root(bad)

    def test_symlink_in_middle_of_root_path_refused(self):
        os.mkdir(os.path.join(self.root, "sub", "deep"))
        os.symlink(os.path.join(self.root, "sub"), os.path.join(self.tmp, "lnk"))
        with self.assertRaises(P.PathGuardError):
            P.open_root(os.path.join(self.tmp, "lnk", "deep"))  # componente intermediário
        with self.assertRaises(P.PathGuardError):
            P.open_root(os.path.join(self.tmp, "lnk"))  # componente final

    def test_valid_root_opens_directory(self):
        fd = P.open_root(os.path.join(self.root, "sub"))
        try:
            self.assertEqual(P.list_dir(fd), [])
        finally:
            os.close(fd)

    def test_home_and_ancestors_refused_even_if_HOME_changed(self):
        acct = os.path.join(self.tmp, "conta-home")
        os.mkdir(acct)
        fake = pwd.struct_passwd(("u", "x", os.getuid(), 0, "", acct, "/bin/sh"))
        with mock.patch.object(P.pwd, "getpwuid", return_value=fake), \
                mock.patch.dict(os.environ, {"HOME": self.outside}):
            for bad in [acct, self.tmp, os.path.dirname(self.tmp)]:
                with self.assertRaises(P.PathGuardError, msg=bad):
                    P.open_root(bad)
            fd = P.open_root(self.outside)  # HOME apontando para outro lugar não protege nada
            os.close(fd)

    def test_account_home_unavailable_refuses(self):
        with mock.patch.object(P, "pwd", None):
            with self.assertRaises(P.PathGuardError):
                P.open_root(self.root)
        with mock.patch.object(P.pwd, "getpwuid", side_effect=KeyError("x")):
            with self.assertRaises(P.PathGuardError):
                P.open_root(self.root)

    def test_fds_not_leaked(self):
        before = len(os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else None
        for _ in range(20):
            for rel in ("ln/x", "a.txt", "nao"):
                try: P.read_bytes(self.fd, rel)
                except P.PathGuardError: pass
        if before is not None:
            self.assertLessEqual(len(os.listdir("/proc/self/fd")), before + 1)


class Scan(Base):
    def test_clean_tree(self):
        self.assertEqual(P.scan_tree(self.fd), [])

    def test_findings(self):
        os.symlink(self.outside, os.path.join(self.root, "dl"))
        os.link(os.path.join(self.outside, "secret.txt"), os.path.join(self.root, "sub", "hl"))
        os.mkfifo(os.path.join(self.root, "fifo"))
        got = dict(P.scan_tree(self.fd))
        self.assertEqual(got, {"dl": "symlink", "sub/hl": "hardlink", "fifo": "tipo especial"})

    def test_limit(self):
        with self.assertRaises(P.PathGuardError):
            P.scan_tree(self.fd, max_entries=1)


if __name__ == "__main__":
    unittest.main()
