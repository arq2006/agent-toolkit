#!/usr/bin/env python3
"""Testes do launcher. Mocks e srt FALSO (fakes.py) validam só a lógica e o fail-closed; não provam
isolamento. Canários reais ficam no doctor, quando bwrap/srt existem.

Executar: python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
"""
import dataclasses
import json
import os
import shutil
import socket
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
        deps = fakes.make_fake_deps(tempfile.gettempdir(), "validate")
        with mock.patch("os.path.isfile", return_value=False):
            with self.assertRaises(L.LauncherError):
                L.runtime_read_paths(deps)
        with mock.patch("os.path.realpath", return_value="/opt/venv/bin/python3"):
            with self.assertRaises(L.LauncherError):
                L.runtime_read_paths(deps)

    def test_validate_settings_rejects_broad_or_extra_reads(self):
        helper = "/home/u/.local/lib/node_modules/@anthropic-ai/sandbox-runtime/vendor/seccomp/x64/apply-seccomp"
        with L.create_fixture() as fx:
            ok = L.build_settings(cfg(fx.authorized), ["/usr", helper])
            self.assertIn(helper, ok["filesystem"]["allowRead"])
            self.assertFalse(ok["network"]["allowAllUnixSockets"])  # seccomp/sockets Unix seguem bloqueados
            for bad in (["/usr", "/home/u/.local"], ["/usr", "/home/u"], ["/usr", "~"],
                        ["/usr", os.path.dirname(helper)], ["/usr", helper, helper.replace("x64", "arm64")],
                        ["/usr", "/home/u/*/vendor/seccomp/x64/apply-seccomp"],
                        ["/usr", "/home/u/.local/vendor/seccomp/x64/apply-seccomp.sh"]):
                with self.assertRaises(L.LauncherError, msg=bad):
                    L.build_settings(cfg(fx.authorized), bad)


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
        with mock.patch.dict(os.environ, {"PATH": self.tmp}), mock.patch("platform.machine", return_value="x86_64"):
            return L.detect_dependencies()

    def make_package(self, root=None, version=None, with_helper=True):
        root = root or os.path.join(self.tmp, "lib", "node_modules", "@anthropic-ai", "sandbox-runtime")
        os.makedirs(os.path.join(root, "dist"), exist_ok=True)
        with open(os.path.join(root, "package.json"), "w") as f:
            json.dump({"name": L.SRT_PACKAGE, "version": version or L.SUPPORTED_SRT_VERSION}, f)
        cli = os.path.join(root, "dist", "cli.js")
        with open(cli, "w") as f:
            f.write(f"#!/bin/sh\necho '{L.SUPPORTED_SRT_VERSION}'\n")
        os.chmod(cli, 0o755)
        helper = os.path.join(root, "vendor", "seccomp", "x64", "apply-seccomp")
        if with_helper:
            os.makedirs(os.path.dirname(helper), exist_ok=True)
            with open(helper, "wb") as f:
                f.write(b"\x7fELF-fake")
            os.chmod(helper, 0o755)
        return root, cli, helper

    def install_srt(self, **kw):
        root, cli, helper = self.make_package(**kw)
        link = os.path.join(self.tmp, "srt")
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(cli, link)
        return root, cli, helper

    def locate(self, cli):
        with mock.patch("platform.machine", return_value="x86_64"):
            return L.locate_seccomp_helper(cli)

    def all_ok(self):
        self.install_srt()
        self.exe("node", "v22")
        self.exe("bwrap", "bubblewrap 0.12.0")
        self.exe("socat", "x")
        self.exe("rg", "x")

    def test_all_present(self):
        self.all_ok()
        d = self.detect()
        self.assertTrue(d.all_ok, d)
        self.assertTrue(d.get("apply-seccomp").path.endswith("vendor/seccomp/x64/apply-seccomp"))

    def test_srt_outside_usr_helper_exact_path_only(self):
        root, cli, helper = self.install_srt()
        info = self.locate(cli)
        self.assertTrue(info.ok, info)
        self.assertEqual(info.path, os.path.realpath(helper))
        reads = L.runtime_read_paths(L.Dependencies({"apply-seccomp": info}))
        self.assertIn(info.path, reads)
        for forbidden in (root, os.path.dirname(info.path), self.tmp, os.path.expanduser("~"), "/home"):
            self.assertNotIn(forbidden, reads)
        self.assertEqual(reads[-1], info.path)

    def test_helper_physically_absent_is_distinguished(self):
        _, cli, _ = self.install_srt(with_helper=False)
        info = self.locate(cli)
        self.assertFalse(info.ok)
        self.assertIn("AUSENTE fisicamente", info.reason)
        with self.assertRaises(L.LauncherError):
            L.runtime_read_paths(L.Dependencies({"apply-seccomp": info}))

    def test_helper_unsafe_variants_refused(self):
        root, cli, helper = self.install_srt()
        os.chmod(helper, 0o775)
        self.assertFalse(self.locate(cli).ok)  # gravável por grupo
        os.chmod(helper, 0o755)
        real = helper + ".real"
        os.rename(helper, real)
        os.symlink(real, helper)
        self.assertFalse(self.locate(cli).ok)  # symlink
        os.remove(helper)
        os.rename(real, helper)
        os.link(helper, helper + ".hl")
        self.assertFalse(self.locate(cli).ok)  # hardlink
        os.remove(helper + ".hl")
        self.assertTrue(self.locate(cli).ok)
        os.chmod(os.path.dirname(helper), 0o777)
        self.assertFalse(self.locate(cli).ok)  # ancestral gravável por outros (sem sticky)
        os.chmod(os.path.dirname(helper), 0o755)
        open(helper, "w").close()
        self.assertFalse(self.locate(cli).ok)  # vazio

    def test_helper_wrong_package_or_version_or_arch(self):
        _, cli, _ = self.install_srt(version="0.0.82")
        self.assertFalse(self.locate(cli).ok)
        lone = os.path.join(self.tmp, "lonely")
        os.mkdir(lone)
        self.assertIn("não localizado", self.locate(os.path.join(lone, "cli.js")).reason)
        _, cli, _ = self.install_srt()
        with mock.patch("platform.machine", return_value="riscv64"):
            self.assertFalse(L.locate_seccomp_helper(cli).ok)

    def test_helper_glob_characters_in_path_refused(self):
        base = os.path.join(self.tmp, "we*ird")
        root, cli, _ = self.make_package(os.path.join(base, "pkg"))
        info = self.locate(cli)
        self.assertFalse(info.ok)
        self.assertIn("caracteres", info.reason)

    def test_srt_version_mismatch_means_no_helper(self):
        self.all_ok()
        self.exe("srt", "0.0.82")  # substitui o symlink por script com outra versão
        d = self.detect()
        self.assertFalse(d.get("srt").ok)
        self.assertFalse(d.get("apply-seccomp").ok)

    def test_missing_everything(self):
        d = self.detect()
        self.assertFalse(d.all_ok)
        for n in ("srt", "bwrap", "socat", "rg", "node"):
            self.assertFalse(d.get(n).ok)

    def test_srt_wrong_version(self):
        self.all_ok()
        os.remove(os.path.join(self.tmp, "srt"))
        self.exe("srt", "0.0.82")
        d = self.detect()
        self.assertFalse(d.get("srt").ok)
        self.assertIn("incompatível", d.get("srt").reason)

    def test_srt_version_failure(self):
        self.all_ok()
        os.remove(os.path.join(self.tmp, "srt"))
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


class Listeners(unittest.TestCase):
    """Separação controle positivo x conexões do sandbox; accept() atrasado não vira falso positivo."""

    def connect(self, lst, label, hello):
        ip, port = lst.socks[label][1], lst.socks[label][2]
        with socket.create_connection((ip, port), timeout=2) as c:
            if hello is not None:
                c.sendall(hello.encode())

    def test_control_waits_for_registration_and_is_not_sandbox(self):
        with L.TcpListeners() as lst:
            lst._accept_delay = 0.6  # accept() registrado bem depois de o controle conectar
            t0 = time.time()
            self.assertTrue(lst.host_control("loopback"))
            self.assertGreaterEqual(time.time() - t0, 0.5)  # esperou o registro: sem corrida
            lst.settle()
            self.assertEqual(lst.summary("loopback"), {"control": 1, "sandbox": 0, "unattributed": 0})
            self.assertEqual(lst.hits["loopback"], 0)

    def test_late_control_accept_after_control_returned_is_still_control(self):
        # reproduz a corrida original: o controle é contabilizado depois de qualquer "reset"; por
        # identidade explícita ele continua sendo controle, nunca sandbox
        with L.TcpListeners() as lst:
            lst._accept_delay = 0.4
            ip, port = lst.socks["loopback"][1], lst.socks["loopback"][2]
            with socket.create_connection((ip, port), timeout=2) as c:  # sem esperar o registro
                c.sendall(lst.control_hello.encode())
            time.sleep(0.05)
            self.assertEqual(lst.summary("loopback")["sandbox"], 0)
            lst.settle()
            self.assertEqual(lst.summary("loopback"), {"control": 1, "sandbox": 0, "unattributed": 0})

    def test_real_sandbox_connection_is_counted_as_sandbox(self):
        with L.TcpListeners() as lst:
            self.assertTrue(lst.host_control("loopback"))
            self.connect(lst, "loopback", lst.sandbox_hello)
            lst.settle()
            self.assertEqual(lst.summary("loopback"), {"control": 1, "sandbox": 1, "unattributed": 0})

    def test_delayed_sandbox_accept_is_collected_by_settle(self):
        with L.TcpListeners() as lst:
            lst._accept_delay = 0.4
            self.connect(lst, "loopback", lst.sandbox_hello)
            lst.settle()
            self.assertEqual(lst.summary("loopback")["sandbox"], 1)

    def test_anonymous_or_forged_connection_is_unattributed(self):
        with L.TcpListeners() as lst:
            self.connect(lst, "loopback", None)
            self.connect(lst, "loopback", "CONTROL-wrongtoken")
            lst.settle()
            self.assertEqual(lst.summary("loopback"), {"control": 0, "sandbox": 0, "unattributed": 2})

    def test_target_carries_sandbox_hello_not_control(self):
        with L.TcpListeners() as lst:
            ip, port, hello = lst.target("loopback")
            self.assertEqual(hello, lst.sandbox_hello)
            self.assertNotEqual(lst.sandbox_hello, lst.control_hello)

    def test_probe_sends_sandbox_hello_when_it_connects(self):
        # executa o PROBE_SRC (sem sandbox, só lógica) contra um ouvinte real
        with L.TcpListeners() as lst:
            ip, port, hello = lst.target("loopback")
            payload = json.dumps({"nonce": "n", "ops": [["t", "tcp", [ip, port, hello]]]})
            r = subprocess.run(["/usr/bin/python3", "-I", "-c", L.PROBE_SRC, payload], capture_output=True, timeout=30)
            res = json.loads(r.stdout.decode().strip().splitlines()[-1])["results"]["t"]
            lst.settle()
            self.assertEqual((res["ok"], res["attempted"]), (True, True))
            self.assertEqual(lst.summary("loopback")["sandbox"], 1)

    def test_probe_reports_attempt_when_connection_fails(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # porta fechada: conexão recusada
        payload = json.dumps({"nonce": "n", "ops": [["t", "tcp", ["127.0.0.1", port, "SANDBOX-x"]]]})
        r = subprocess.run(["/usr/bin/python3", "-I", "-c", L.PROBE_SRC, payload], capture_output=True, timeout=30)
        res = json.loads(r.stdout.decode().strip().splitlines()[-1])["results"]["t"]
        self.assertEqual((res["ok"], res["attempted"]), (False, True))


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
