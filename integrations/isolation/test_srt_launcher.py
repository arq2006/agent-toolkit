#!/usr/bin/env python3
"""Testes do launcher. Mocks e srt FALSO (fakes.py) validam só a lógica e o fail-closed; não provam
isolamento. Canários reais ficam no doctor, quando bwrap/srt existem.

Executar: python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
"""
import dataclasses
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import fakes
import isolation_config as C
import srt_launcher as L

SENSITIVE = {"ANTHROPIC_API_KEY": "fake-key", "GITHUB_TOKEN": "fake-token", "SSH_AUTH_SOCK": "/tmp/fake-agent",
             "HTTPS_PROXY": "http://fake:3128", "http_proxy": "http://fake:3128", "LD_PRELOAD": "/tmp/x.so",
             "NODE_OPTIONS": "--require /tmp/x.js", "PYTHONPATH": "/tmp/evil", "AWS_SECRET_ACCESS_KEY": "fake"}


def cfg(adir, net="deny"):
    return C.Config(adir, "none", net, () if net == "deny" else ("example.org",))


class Settings(unittest.TestCase):
    def test_restrictive_exact(self):
        with L.create_fixture() as fx:
            s = L.build_settings(cfg(fx.authorized), ["/usr"])
        self.assertEqual(s["filesystem"]["denyRead"], ["/"])
        self.assertEqual(s["filesystem"]["allowRead"], [fx.authorized, "/usr"])
        self.assertEqual(s["filesystem"]["allowWrite"], [fx.authorized])
        self.assertEqual(s["network"]["allowedDomains"], [])
        self.assertIs(s["network"]["allowLocalBinding"], False)

    def test_allowlist_refused(self):
        with L.create_fixture() as fx:
            with self.assertRaises(L.LauncherRefused):
                L.build_settings(cfg(fx.authorized, "allowlist"), ["/usr"])

    def test_unsafe_authorized_dir_refused(self):
        for bad in ("/", "relativo", os.path.expanduser("~")):
            with self.assertRaises(Exception):
                L.build_settings(cfg(bad), ["/usr"])

    def test_validate_rejects_weakening(self):
        with L.create_fixture() as fx:
            good = L.build_settings(cfg(fx.authorized), ["/usr"])
            import copy
            muts = [
                lambda s: s["filesystem"].update(denyRead=[]),
                lambda s: s["filesystem"].update(allowWrite=[fx.authorized, "/tmp"]),
                lambda s: s["filesystem"]["allowRead"].append("/home"),
                lambda s: s["network"].update(allowedDomains=["example.org"]),
                lambda s: s["network"].update(allowLocalBinding=True),
                lambda s: s["network"].update(allowAllUnixSockets=True),
                lambda s: s.update(enableWeakerNestedSandbox=True),
                lambda s: s.update(allowNestedUserNamespaces=True),
                lambda s: s.update(extra=1),
            ]
            for m in muts:
                s = copy.deepcopy(good)
                m(s)
                with self.assertRaises(L.LauncherError):
                    L.validate_settings(s, fx.authorized, ["/usr"])

    def test_runtime_reads_justified_and_minimal(self):
        for path, why in L.RUNTIME_READ + L.RUNTIME_READ_NON_USRMERGE:
            self.assertTrue(why.strip())
            self.assertNotIn(path, ("/", "/home", "/root", "/tmp", "/etc", "/var", "/proc", "/sys"))

    def test_runtime_reads_fail_closed(self):
        with mock.patch("os.path.isfile", return_value=False):
            with self.assertRaises(L.LauncherError):
                L.runtime_read_paths()
        with mock.patch("os.path.realpath", return_value="/opt/venv/bin/python3"):
            with self.assertRaises(L.LauncherError):
                L.runtime_read_paths()


class Env(unittest.TestCase):
    def test_env_is_closed_list(self):
        with mock.patch.dict(os.environ, SENSITIVE), L.create_fixture() as fx:
            env = L.build_env(fx, ["/usr/bin"])
        self.assertLessEqual(set(env), set(L.ENV_ALLOWED))
        for k, v in SENSITIVE.items():
            self.assertNotIn(k, env)
            self.assertNotIn(v, env.values())
        self.assertTrue(env["HOME"].startswith(fx.root))


class Deps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="deps-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def exe(self, name, out, rc=0):
        p = os.path.join(self.tmp, name)
        with open(p, "w") as f:
            f.write(f"#!/bin/sh\necho '{out}'\nexit {rc}\n")
        os.chmod(p, 0o755)

    def detect(self):
        with mock.patch.dict(os.environ, {"PATH": self.tmp}):
            return L.detect_dependencies()

    def all_ok(self):
        self.exe("srt", L.SUPPORTED_SRT_VERSION)
        self.exe("node", "v22")
        self.exe("bwrap", "bubblewrap 0.12.0")
        self.exe("socat", "x")
        self.exe("rg", "x")

    def test_all_present(self):
        self.all_ok()
        d = self.detect()
        self.assertTrue(d.all_ok, d)

    def test_missing_everything(self):
        d = self.detect()
        self.assertFalse(d.all_ok)
        for n in ("srt", "bwrap", "socat", "rg", "node"):
            self.assertFalse(d.get(n).ok)

    def test_srt_wrong_version(self):
        self.all_ok()
        self.exe("srt", "0.0.82")
        d = self.detect()
        self.assertFalse(d.get("srt").ok)
        self.assertIn("incompatível", d.get("srt").reason)

    def test_srt_version_failure(self):
        self.all_ok()
        self.exe("srt", "", rc=1)
        self.assertFalse(self.detect().get("srt").ok)

    def test_bwrap_old_and_garbage(self):
        self.all_ok()
        self.exe("bwrap", "bubblewrap 0.4.1")
        self.assertFalse(self.detect().get("bwrap").ok)
        self.exe("bwrap", "something else")
        self.assertFalse(self.detect().get("bwrap").ok)

    def test_missing_node_blocks_srt(self):
        self.all_ok()
        os.remove(os.path.join(self.tmp, "node"))
        d = self.detect()
        self.assertFalse(d.get("node").ok)
        self.assertFalse(d.get("srt").ok)


class Execution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="exec-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fx = L.create_fixture()
        self.addCleanup(self.fx.cleanup)
        self.config = cfg(self.fx.authorized)

    def suite(self, mode, **kw):
        deps = fakes.make_fake_deps(self.tmp, mode)
        return deps, L.run_suite(deps, self.config, self.fx, timeout=kw.pop("timeout", 20), **kw)

    def test_fixture_layout_and_cleanup(self):
        fx = L.create_fixture()
        self.assertEqual(stat.S_IMODE(os.stat(fx.root).st_mode), 0o700)
        for p in (fx.auth_canary, fx.secret, fx.home_decoy):
            self.assertTrue(os.path.isfile(p))
        self.assertTrue(os.path.islink(fx.symlink))
        fx.cleanup()
        self.assertFalse(os.path.exists(fx.root))

    def test_argv_structured_with_settings_no_shell(self):
        deps = fakes.make_fake_deps(self.tmp, "validate")
        real = subprocess.Popen
        seen = []

        def spy(argv, **kw):
            seen.append((argv, kw))
            return real(argv, **kw)

        with mock.patch("subprocess.Popen", spy):
            L.run_suite(deps, self.config, self.fx, timeout=20)
        argv, kw = seen[0]
        self.assertIsInstance(argv, list)
        self.assertEqual(argv[0], deps.get("srt").path)
        self.assertEqual(argv[1], "--settings")
        self.assertEqual(argv[2], self.fx.settings_path)
        self.assertFalse(kw["shell"])
        self.assertTrue(kw["start_new_session"])
        self.assertEqual(len(seen), 1)

    def test_launcher_source_has_no_shell_true_or_other_exec(self):
        with open(L.__file__) as f:
            src = f.read()
        self.assertNotIn("shell=True", src)
        self.assertNotIn("os.system", src)

    def test_policy_file_written_restrictive(self):
        self.suite("validate")
        import json
        with open(self.fx.settings_path) as f:
            s = json.load(f)
        self.assertEqual(s["filesystem"]["denyRead"], ["/"])
        self.assertEqual(stat.S_IMODE(os.stat(self.fx.settings_path).st_mode), 0o600)

    def test_refuses_non_fixture_dir(self):
        deps = fakes.make_fake_deps(self.tmp, "validate")
        with self.assertRaises(L.LauncherRefused):
            L.run_suite(deps, cfg(self.tmp), self.fx)

    def test_refuses_allowlist(self):
        deps = fakes.make_fake_deps(self.tmp, "validate")
        with self.assertRaises(L.LauncherRefused):
            L.run_suite(deps, cfg(self.fx.authorized, "allowlist"), self.fx)

    def test_refuses_missing_dependency(self):
        deps = fakes.make_fake_deps(self.tmp, "validate")
        items = dict(deps.items)
        items["bwrap"] = L.DepInfo("bwrap", "", "", False, "ausente")
        with self.assertRaises(L.LauncherError):
            L.run_suite(L.Dependencies(items), self.config, self.fx)

    def test_sandbox_start_failure_is_not_ran_and_no_fallback(self):
        deps, res = self.suite("crash")
        self.assertFalse(res.ran)
        self.assertEqual(res.returncode, 7)
        self.assertFalse(os.path.exists(self.fx.auth_write))  # nada rodou sem o srt

    def test_timeout_kills_process(self):
        t0 = time.time()
        deps, res = self.suite("hang", timeout=1)
        self.assertFalse(res.ran)
        self.assertTrue(res.timed_out)
        self.assertLess(time.time() - t0, 15)

    def test_output_without_valid_nonce_is_not_accepted(self):
        deps = fakes.make_fake_deps(self.tmp, "validate")
        real = subprocess.Popen

        def fake_popen(argv, **kw):
            return real(["/usr/bin/env", "python3", "-c", "print('{\"nonce\":\"forged\",\"results\":{}}')"], **kw)

        with mock.patch("subprocess.Popen", fake_popen):
            res = L.run_suite(deps, self.config, self.fx, timeout=20)
        self.assertFalse(res.ran)

    def test_spawn_failure_raises(self):
        with self.assertRaises(L.LauncherError):
            L._spawn(["/nonexistent/binary"], {}, self.tmp, 5)

    def test_env_not_inherited_in_child(self):
        with mock.patch.dict(os.environ, SENSITIVE):
            deps, res = self.suite("validate", sentinel="fake-token")
        self.assertTrue(res.ran, res)
        keys = res.results["env"]["keys"]
        self.assertLessEqual(set(keys), set(L.ENV_ALLOWED))
        self.assertFalse(res.results["env"]["sentinel_visible"])

    def test_fail_closed_probe_detects_srt_that_ignores_bad_settings(self):
        deps = fakes.make_fake_deps(self.tmp, "validate")
        for kind in ("missing", "invalid"):
            r = L.run_fail_closed_probe(deps, self.fx, kind, 20)
            self.assertFalse(r.ran, kind)
        deps = fakes.make_fake_deps(self.tmp, "ignore_settings_ok")  # srt falso que executa mesmo assim
        for kind in ("missing", "invalid"):
            self.assertTrue(L.run_fail_closed_probe(deps, self.fx, kind, 20).ran, kind)

    def test_fail_closed_probe_unknown_kind(self):
        deps = fakes.make_fake_deps(self.tmp, "validate")
        with self.assertRaises(L.LauncherError):
            L.run_fail_closed_probe(deps, self.fx, "other")


if __name__ == "__main__":
    unittest.main()
