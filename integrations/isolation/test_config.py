#!/usr/bin/env python3
"""Testes do carregador de configuração. Só diretórios temporários fictícios.

Executar: python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
"""
import os, pwd, shutil, tempfile, threading, unittest
from unittest import mock

import isolation_config as C
import pathguard as P


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="cfg-test-"))
        self.d = os.path.join(self.tmp, "pasta")
        os.mkdir(self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def toml(self, adir=None, auth="none", net='mode = "deny"', extra=""):
        adir = self.d if adir is None else adir
        return f'version = 1\n{extra}\n[authorized]\ndir = "{adir}"\n[auth]\nmode = "{auth}"\n[network]\n{net}\n'

    def write(self, text, name="c.toml"):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p


class Valid(Base):
    def test_minimal(self):
        c = C.parse(self.toml())
        self.assertEqual((c.authorized_dir, c.auth_mode, c.network_mode, c.network_allow),
                         (self.d, "none", "deny", ()))

    def test_allowlist_and_auth(self):
        c = C.parse(self.toml(auth="claude-ai-outside-boundary",
                              net='mode = "allowlist"\nallow = ["github.com", "api.example.org"]'))
        self.assertEqual(c.network_allow, ("github.com", "api.example.org"))

    def test_load_file(self):
        self.assertEqual(C.load(self.write(self.toml())).authorized_dir, self.d)


class Invalid(Base):
    def bad(self, text):
        with self.assertRaises(C.ConfigError):
            C.parse(text)

    def test_missing_or_unreadable_file(self):
        for p in [os.path.join(self.tmp, "nao.toml"), "", None, "a\x00b", self.tmp]:
            with self.assertRaises(C.ConfigError, msg=repr(p)):
                C.load(p)

    def test_symlink_config_rejected(self):
        real = self.write(self.toml())
        link = os.path.join(self.tmp, "l.toml")
        os.symlink(real, link)
        with self.assertRaises(C.ConfigError):
            C.load(link)

    def test_bad_toml_encoding_size(self):
        self.bad("isto = não é toml [[")
        with self.assertRaises(C.ConfigError):
            C.load(self._raw(b"\xff\xfe"))
        self.bad("# " + "x" * 70000)

    def _raw(self, b):
        p = os.path.join(self.tmp, "raw.toml")
        with open(p, "wb") as f:
            f.write(b)
        return p

    def test_version_and_unknown_keys(self):
        self.bad(self.toml().replace("version = 1", "version = 2"))
        self.bad(self.toml().replace("version = 1", "version = true"))
        self.bad(self.toml().replace("version = 1\n", ""))
        self.bad(self.toml(extra='segredo = "x"'))
        self.bad(self.toml() + '[extra]\na = 1\n')
        self.bad(self.toml().replace('dir =', 'extra = 1\ndir ='))

    def test_missing_sections(self):
        for sec in ("[authorized]", "[auth]", "[network]"):
            self.bad(self.toml().replace(sec, "[zz]"))

    def test_authorized_dir(self):
        link = os.path.join(self.tmp, "ln")
        os.symlink(self.d, link)
        f = os.path.join(self.tmp, "arq")
        with open(f, "w"):
            pass
        home = os.path.realpath(P.account_home())
        for adir in ["relativo/x", "/", self.d + "/../pasta", self.d + "/", link, f,
                     os.path.join(self.tmp, "inexistente"), home, os.path.dirname(home), "", "/a\\x00b"]:
            self.bad(self.toml(adir=adir))
        self.bad(self.toml().replace(f'"{self.d}"', "42"))

    def test_auth_and_network(self):
        self.bad(self.toml(auth="full"))
        self.bad(self.toml(net='mode = "open"'))
        self.bad(self.toml(net='mode = "deny"\nallow = ["github.com"]'))
        self.bad(self.toml(net='mode = "allowlist"'))
        self.bad(self.toml(net='mode = "allowlist"\nallow = []'))
        for h in ["*.example.com", "https://x.com", "x.com:443", "10.0.0.1", "", "a b", "-x.com",
                  "x" * 300, "x.com/path"]:
            self.bad(self.toml(net=f'mode = "allowlist"\nallow = ["{h}"]'))
        self.bad(self.toml(net='mode = "allowlist"\nallow = ["a.com", "a.com"]'))
        self.bad(self.toml(net='mode = "allowlist"\nallow = "a.com"'))

    def test_deny_rejects_any_allow_value(self):
        for v in ['""', '{}', '[]', '5', 'true', 'false', '["a.com"]', '"a.com"', '1.5', '[[]]']:
            self.bad(self.toml(net=f'mode = "deny"\nallow = {v}'))

    def test_allowlist_requires_valid_allow(self):
        self.bad(self.toml(net='mode = "allowlist"'))
        for v in ['""', '{}', '5', 'true', 'false', '1.5', '[1]', '[true]', '[[]]', '[{}]', '[""]']:
            self.bad(self.toml(net=f'mode = "allowlist"\nallow = {v}'))

    def test_no_unexpected_exception_escapes(self):
        for net in ['mode = 5', 'mode = ["deny"]', 'mode = {}', 'allow = ["a.com"]']:
            self.bad(self.toml(net=net))
        self.bad(self.toml(auth="none").replace('mode = "none"', 'mode = 7'))
        self.bad("[" * 5000)


class FakeHome(Base):
    """HOME alterada e conta sintética: a home real da conta continua protegida."""

    def with_account_home(self, home):
        fake = pwd.struct_passwd(("u", "x", os.getuid(), 0, "", home, "/bin/sh"))
        return mock.patch.object(P.pwd, "getpwuid", return_value=fake)

    def test_home_env_does_not_authorize_account_home(self):
        acct = os.path.join(self.tmp, "conta-home")
        os.mkdir(acct)
        other = os.path.join(self.tmp, "outra")
        os.mkdir(other)
        sub = os.path.join(acct, "projetos")
        os.mkdir(sub)
        with self.with_account_home(acct), mock.patch.dict(os.environ, {"HOME": other}):
            self.bad_dir(acct)
            self.bad_dir(self.tmp)  # ancestral da home da conta
            self.assertEqual(C.parse(self.toml(adir=sub)).authorized_dir, sub)  # subpasta é permitida
            self.assertEqual(C.parse(self.toml(adir=other)).authorized_dir, other)

    def test_home_env_set_to_authorized_dir_changes_nothing(self):
        acct = os.path.join(self.tmp, "conta-home")
        os.mkdir(acct)
        with self.with_account_home(acct), mock.patch.dict(os.environ, {"HOME": self.d}):
            self.bad_dir(acct)
        with self.with_account_home(acct), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HOME", None)
            self.bad_dir(acct)

    def test_unknown_account_refuses(self):
        with mock.patch.object(P.pwd, "getpwuid", side_effect=KeyError("x")):
            self.bad_dir(self.d)
        with mock.patch.object(P, "pwd", None):
            self.bad_dir(self.d)
        fake = pwd.struct_passwd(("u", "x", 0, 0, "", "", "/bin/sh"))
        with mock.patch.object(P.pwd, "getpwuid", return_value=fake):
            self.bad_dir(self.d)

    def bad_dir(self, adir):
        with self.assertRaises(C.ConfigError, msg=adir):
            C.parse(self.toml(adir=adir))


class SpecialConfigFile(Base):
    def run_load(self, path):
        out = []

        def target():
            try:
                C.load(path)
                out.append("ok")
            except C.ConfigError:
                out.append("ConfigError")
            except BaseException as e:  # nada além de ConfigError pode escapar
                out.append(type(e).__name__)

        th = threading.Thread(target=target, daemon=True)
        th.start()
        th.join(5)
        self.assertFalse(th.is_alive(), "load() bloqueou")
        return out

    def test_fifo_does_not_block(self):
        f = os.path.join(self.tmp, "fifo.toml")
        os.mkfifo(f)
        self.assertEqual(self.run_load(f), ["ConfigError"])

    def test_directory_and_dev_null_refused(self):
        self.assertEqual(self.run_load(self.tmp), ["ConfigError"])
        self.assertEqual(self.run_load("/dev/null"), ["ConfigError"])

    def test_oversized_regular_file_refused(self):
        p = self._raw(b"#" * 70000)
        self.assertEqual(self.run_load(p), ["ConfigError"])

    def _raw(self, b):
        p = os.path.join(self.tmp, "raw2.toml")
        with open(p, "wb") as f:
            f.write(b)
        return p


if __name__ == "__main__":
    unittest.main()
