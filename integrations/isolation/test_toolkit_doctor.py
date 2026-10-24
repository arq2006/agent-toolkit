#!/usr/bin/env python3
"""Testes do doctor. srt FALSO e resultados sintéticos validam só a lógica de classificação e o
fail-closed; não provam isolamento. Um srt falso SEM sandbox deve ser detectado como FALHA.

Executar: python3 -I -m unittest discover -s integrations/isolation -p 'test_*.py'
"""
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import fakes
import srt_launcher as L
import toolkit_doctor as D


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="doctor-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.adir = os.path.join(self.tmp, "pasta")
        os.mkdir(self.adir)

    def config(self, net='mode = "deny"', auth="none", adir=None):
        p = os.path.join(self.tmp, "c.toml")
        with open(p, "w") as f:
            f.write(f'version = 1\n[authorized]\ndir = "{adir or self.adir}"\n[auth]\nmode = "{auth}"\n[network]\n{net}\n')
        return p

    def status(self, rep, cid):
        return next(c["status"] for c in rep["checks"] if c["id"] == cid)

    def assertNeverAuthorizes(self, rep):
        s = rep["summary"]
        self.assertEqual(s["file_operations"], "BLOCKED")
        self.assertEqual(s["strong"], "UNAVAILABLE")
        self.assertIs(s["agent_execution_authorized"], False)


class Failures(Base):
    def test_missing_config(self):
        rep = D.run_doctor(os.path.join(self.tmp, "nope.toml"))
        self.assertEqual(self.status(rep, "config"), D.FAIL)
        self.assertEqual(rep["exit_code"], 3)
        self.assertNeverAuthorizes(rep)
        self.assertNotEqual(rep["summary"]["sandbox_canaries"], "PASSED")

    def test_invalid_config(self):
        p = os.path.join(self.tmp, "bad.toml")
        with open(p, "w") as f:
            f.write("version = 2\n")
        rep = D.run_doctor(p)
        self.assertEqual(self.status(rep, "config"), D.FAIL)
        self.assertEqual(rep["exit_code"], 3)

    def test_unsafe_authorized_dir(self):
        rep = D.run_doctor(self.config(adir="/"))
        self.assertEqual(self.status(rep, "config"), D.FAIL)

    def test_unsupported_platform(self):
        with mock.patch("sys.platform", "darwin"):
            rep = D.run_doctor(self.config(), deps=fakes.make_fake_deps(self.tmp, "validate"))
        self.assertEqual(self.status(rep, "platform"), D.FAIL)
        self.assertEqual(rep["exit_code"], 3)
        self.assertNeverAuthorizes(rep)

    def test_allowlist_refused(self):
        rep = D.run_doctor(self.config(net='mode = "allowlist"\nallow = ["example.org"]'),
                           deps=fakes.make_fake_deps(self.tmp, "validate"))
        self.assertEqual(self.status(rep, "network_policy"), D.FAIL)
        self.assertEqual(self.status(rep, "canary_run"), D.NOT_TESTED)
        self.assertEqual(rep["exit_code"], 2)

    def test_dependencies_missing(self):
        deps = L.Dependencies({n: L.DepInfo(n, "", "", False, "não encontrado no PATH")
                               for n in ("srt", "node", "bwrap", "socat", "rg")})
        rep = D.run_doctor(self.config(), deps=deps)
        self.assertEqual(self.status(rep, "dep_srt"), D.FAIL)
        self.assertEqual(self.status(rep, "canary_run"), D.NOT_TESTED)
        self.assertEqual(rep["summary"]["sandbox_canaries"], "FAILED")
        self.assertEqual(rep["exit_code"], 2)
        self.assertNeverAuthorizes(rep)
        self.assertEqual(self.status(rep, "pathguard_indirect"), D.PASS)  # lógica do executor, sem sandbox

    def test_srt_incompatible_version_blocks(self):
        d = fakes.make_fake_deps(self.tmp, "validate")
        items = dict(d.items)
        items["srt"] = L.DepInfo("srt", items["srt"].path, "0.0.99", False, "versão incompatível")
        rep = D.run_doctor(self.config(), deps=L.Dependencies(items))
        self.assertEqual(self.status(rep, "dep_srt"), D.FAIL)
        self.assertEqual(self.status(rep, "canary_run"), D.NOT_TESTED)

    def test_sandbox_start_failure(self):
        rep = D.run_doctor(self.config(), deps=fakes.make_fake_deps(self.tmp, "crash"), timeout=20)
        self.assertEqual(self.status(rep, "canary_run"), D.FAIL)
        self.assertEqual(self.status(rep, "outside_read_blocked"), D.NOT_TESTED)
        # falha genérica de runtime (rc=7) NÃO prova rejeição de política
        self.assertEqual(self.status(rep, "fail_closed_missing_settings"), D.NOT_TESTED)
        self.assertEqual(self.status(rep, "runtime_reads"), D.NOT_TESTED)
        self.assertNeverAuthorizes(rep)
        self.assertEqual(rep["exit_code"], 2)

    def test_timeout(self):
        rep = D.run_doctor(self.config(), deps=fakes.make_fake_deps(self.tmp, "hang"), timeout=1)
        self.assertEqual(self.status(rep, "canary_run"), D.FAIL)
        self.assertEqual(self.status(rep, "fail_closed_missing_settings"), D.NOT_TESTED)
        self.assertEqual(rep["summary"]["sandbox_canaries"], "FAILED")


class Regression127(Base):
    """Regressão do relatório real do Arch: srt 0.0.81 instalado fora de /usr, apply-seccomp oculto (127)."""

    def test_exit127_is_not_fail_closed_evidence(self):
        rep = D.run_doctor(self.config(), deps=fakes.make_fake_deps(self.tmp, "exit127"), timeout=20)
        c = next(c for c in rep["checks"] if c["id"] == "canary_run")
        self.assertEqual(c["status"], D.FAIL)
        self.assertIn("AUSENTE fisicamente", c["reason"])  # caminho do fake não existe no host
        for cid in ("fail_closed_missing_settings", "fail_closed_invalid_settings", "runtime_reads"):
            self.assertEqual(self.status(rep, cid), D.NOT_TESTED, cid)
        self.assertEqual(rep["summary"]["sandbox_canaries"], "FAILED")

    def test_hidden_vs_absent_diagnosis(self):
        helper = os.path.join(self.tmp, "vendor", "seccomp", "x64", "apply-seccomp")
        os.makedirs(os.path.dirname(helper))
        open(helper, "w").close()
        err = f"bash: {helper}: No such file or directory"
        deps = fakes.make_fake_deps(self.tmp, "validate")
        items = dict(deps.items)
        items["apply-seccomp"] = L.DepInfo("apply-seccomp", helper, "x64", True)
        self.assertIn("OCULTO", D._diagnose_start_failure(L.Dependencies(items), err))
        os.remove(helper)
        self.assertIn("AUSENTE", D._diagnose_start_failure(L.Dependencies(items), err))
        self.assertEqual(D._diagnose_start_failure(deps, "other error"), "")

    def test_classify_fail_closed(self):
        with L.create_fixture() as fx:
            path = os.path.join(fx.root, "no-such-settings.json")
            msg = f"Error: {path} does not exist.\nRefusing to run with the built-in defaults, x\n"
            mk = lambda rc, err, ran=False, to=False: L.SuiteResult(ran, "", rc, to, {}, err)
            cl = lambda r, ctl=True: D._classify_fail_closed(r, fx, "missing", path, ctl)[0]
            self.assertEqual(cl(mk(1, msg)), D.PASS)
            self.assertEqual(cl(mk(1, msg), ctl=False), D.NOT_TESTED)  # sem controle positivo
            self.assertEqual(cl(mk(127, "No such file or directory")), D.NOT_TESTED)  # genérica
            self.assertEqual(cl(mk(1, "Refusing to run with the built-in defaults")), D.NOT_TESTED)  # sem o arquivo
            self.assertEqual(cl(mk(1, "x", to=True)), D.NOT_TESTED)
            self.assertEqual(cl(mk(0, "")), D.FAIL)
            self.assertEqual(cl(mk(0, msg, ran=True)), D.FAIL)

    def test_runtime_reads_pass_requires_working_sandbox(self):
        rep = D.run_doctor(self.config(), deps=fakes.make_fake_deps(self.tmp, "validate_noop"), timeout=30)
        self.assertEqual(self.status(rep, "runtime_reads"), D.PASS)  # controle positivo funcionou
        rep = D.run_doctor(self.config(), deps=fakes.make_fake_deps(self.tmp, "exit127"), timeout=20)
        self.assertEqual(self.status(rep, "runtime_reads"), D.NOT_TESTED)


class FakeNoopSandbox(Base):
    """srt falso que NÃO isola: o doctor precisa reprovar (não confundir lógica com isolamento)."""

    def test_noop_sandbox_is_detected(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
            rep = D.run_doctor(self.config(), deps=fakes.make_fake_deps(self.tmp, "validate_noop"), timeout=30)
        self.assertEqual(self.status(rep, "canary_run"), D.PASS)
        self.assertEqual(self.status(rep, "auth_read_write"), D.PASS)  # controle positivo
        for cid in ("outside_read_blocked", "outside_write_blocked", "home_decoy_blocked", "policy_file_hidden",
                    "subprocess_restricted", "dotdot_blocked", "proc_blocked"):
            self.assertEqual(self.status(rep, cid), D.FAIL, cid)
        for cid in ("tcp_loopback_blocked", "tcp_external_blocked"):
            c = next(c for c in rep["checks"] if c["id"] == cid)
            if c["status"] != D.NOT_TESTED:  # NOT_TESTED só se o host não tiver a interface
                self.assertEqual(c["status"], D.FAIL, cid)
                self.assertGreaterEqual(c["evidence"]["received_from_sandbox"], 1)
                self.assertEqual(c["evidence"]["control_connections"], 1)
        self.assertEqual(self.status(rep, "env_not_inherited"), D.PASS)  # ambiente é do launcher, não do srt
        self.assertEqual(rep["summary"]["sandbox_canaries"], "FAILED")
        self.assertEqual(rep["exit_code"], 2)
        self.assertNeverAuthorizes(rep)

    def test_noop_srt_that_ignores_bad_settings_is_detected(self):
        rep = D.run_doctor(self.config(), deps=fakes.make_fake_deps(self.tmp, "ignore_settings_ok"), timeout=30)
        self.assertEqual(self.status(rep, "fail_closed_missing_settings"), D.FAIL)
        self.assertEqual(self.status(rep, "fail_closed_invalid_settings"), D.FAIL)

    def test_external_files_untouched_after_run(self):
        # o fake não isola, então o doctor modifica o decoy; o fixture é descartado ao final
        before = set(os.listdir(tempfile.gettempdir()))
        D.run_doctor(self.config(), deps=fakes.make_fake_deps(self.tmp, "validate_noop"), timeout=30)
        leftovers = [n for n in set(os.listdir(tempfile.gettempdir())) - before if n.startswith("toolkit-doctor-")]
        self.assertEqual(leftovers, [])
        self.assertEqual(os.listdir(self.adir), [])  # a pasta "autorizada" do config nunca é tocada

    def test_environment_restored(self):
        D.run_doctor(self.config(), deps=fakes.make_fake_deps(self.tmp, "validate"), timeout=20)
        self.assertNotIn("TOOLKIT_DOCTOR_FAKE_SECRET", os.environ)


class Classification(Base):
    """_check_canaries com resultados SINTÉTICOS (lógica pura; não é evidência de isolamento)."""

    def setUp(self):
        super().setUp()
        self.fx = L.create_fixture()
        self.addCleanup(self.fx.cleanup)
        with open(self.fx.auth_write, "wb") as f:
            f.write(b"probe-write")
        fx = self.fx
        blocked = {"ok": False, "err": "PermissionError"}
        netblocked = {"ok": False, "attempted": True, "err": "OSError"}
        self.good = {
            "auth_read": {"ok": True, "data": fx.auth_marker}, "auth_write": {"ok": True},
            "auth_child_read": {"ok": True, "data": fx.auth_marker},
            "ext_read": blocked, "ext_write_existing": blocked, "ext_create": blocked, "home_decoy_read": blocked,
            "settings_read": blocked, "child_ext_read": blocked, "child_ext_write": blocked, "dotdot_read": blocked,
            "symlink_read": blocked, "hardlink_read": blocked, "proc_host": blocked,
            "env": {"ok": True, "keys": ["PATH", "HOME"], "sentinel_visible": False},
            "tcp_loopback": netblocked, "tcp_external": netblocked,
        }
        self.counts = {k: {"control": 1, "sandbox": 0, "unattributed": 0} for k in ("loopback", "external")}
        self.lst = mock.Mock(socks={"loopback": 1, "external": 1}, control_ok={"loopback": True, "external": True},
                             summary=lambda label: dict(self.counts[label]))

    def run_checks(self, results):
        rep = D.Report()
        D._check_canaries(rep, self.fx, L.SuiteResult(True, results=results), self.lst, True)
        return {c["id"]: c for c in rep.checks}

    def test_all_good_passes_but_never_authorizes(self):
        c = self.run_checks(self.good)
        for cid, _ in D.CANARY_CHECKS:
            if cid != "canary_run":
                self.assertEqual(c[cid]["status"], D.PASS, cid)
        self.assertEqual(c["hardlink_native_read"]["status"], D.INFO)
        self.assertFalse(c["hardlink_native_read"]["mandatory"])

    def test_leaks_fail(self):
        fx = self.fx
        for op, cid, val in (
            ("ext_read", "outside_read_blocked", {"ok": True, "data": fx.secret_marker}),
            ("ext_create", "outside_write_blocked", {"ok": True}),
            ("child_ext_read", "subprocess_restricted", {"ok": True, "data": fx.secret_marker}),
            ("proc_host", "proc_blocked", {"ok": True}),
            ("tcp_loopback", "tcp_loopback_blocked", {"ok": True, "attempted": True}),
            ("tcp_external", "tcp_external_blocked", {"ok": True, "attempted": True}),
            ("settings_read", "policy_file_hidden", {"ok": True, "data": "{}"}),
            ("env", "env_not_inherited", {"ok": True, "keys": [], "sentinel_visible": True}),
        ):
            r = dict(self.good)
            r[op] = val
            self.assertEqual(self.run_checks(r)[cid]["status"], D.FAIL, cid)

    def test_sandbox_connection_received_fails_and_is_reported(self):
        self.counts["loopback"]["sandbox"] = 1
        c = self.run_checks(self.good)["tcp_loopback_blocked"]
        self.assertEqual(c["status"], D.FAIL)
        self.assertEqual(c["evidence"]["received_from_sandbox"], 1)
        self.assertEqual(c["evidence"]["control_connections"], 1)

    def test_unattributed_connection_fails(self):
        self.counts["external"]["unattributed"] = 1
        self.assertEqual(self.run_checks(self.good)["tcp_external_blocked"]["status"], D.FAIL)

    def test_control_connections_alone_never_fail(self):
        self.counts["external"]["control"] = 3  # controle positivo (inclusive repetido/atrasado)
        c = self.run_checks(self.good)["tcp_external_blocked"]
        self.assertEqual(c["status"], D.PASS)
        self.assertEqual(c["evidence"]["probe_reported_connected"], False)
        self.assertTrue(c["evidence"]["sandbox_attempted"])

    def test_probe_reported_connection_without_listener_record_fails(self):
        r = dict(self.good)
        r["tcp_external"] = {"ok": True, "attempted": True}
        c = self.run_checks(r)["tcp_external_blocked"]
        self.assertEqual(c["status"], D.FAIL)
        self.assertEqual(c["evidence"]["received_from_sandbox"], 0)

    def test_no_attempt_reported_is_not_tested(self):
        r = dict(self.good)
        r["tcp_external"] = {"ok": False, "err": "x"}
        self.assertEqual(self.run_checks(r)["tcp_external_blocked"]["status"], D.NOT_TESTED)

    def test_missing_network_control_is_not_tested(self):
        self.lst.control_ok["external"] = False
        self.assertEqual(self.run_checks(self.good)["tcp_external_blocked"]["status"], D.NOT_TESTED)
        self.lst.socks.pop("external")
        self.assertEqual(self.run_checks(self.good)["tcp_external_blocked"]["status"], D.NOT_TESTED)

    def test_failed_positive_control_invalidates_blocks(self):
        r = dict(self.good)
        r["auth_read"] = {"ok": False, "err": "FileNotFoundError"}  # ex.: runtime mínimo insuficiente
        c = self.run_checks(r)
        self.assertEqual(c["auth_read_write"]["status"], D.FAIL)
        self.assertEqual(c["outside_read_blocked"]["status"], D.NOT_TESTED)  # bloqueio sem controle não vale

    def test_hardlink_leak_is_reported_as_limitation(self):
        r = dict(self.good)
        r["hardlink_read"] = {"ok": True, "data": self.fx.secret_marker}
        c = self.run_checks(r)
        self.assertIn("LIMITAÇÃO", c["hardlink_native_read"]["reason"])
        self.assertEqual(c["hardlink_native_read"]["status"], D.INFO)


class Output(Base):
    def test_json_and_text(self):
        deps = L.Dependencies({n: L.DepInfo(n, "", "", False, "ausente") for n in ("srt", "node", "bwrap", "socat", "rg")})
        rep = D.run_doctor(self.config(), deps=deps)
        json.dumps(rep)
        txt = D.render_text(rep)
        self.assertIn("NÃO autorizada", txt)
        self.assertIn("BLOCKED", txt)
        self.assertTrue(rep["limitations"])
        self.assertNotIn(self.adir, json.dumps(rep))  # caminho da pasta do usuário não vai para a saída

    def test_main_exit_codes(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = D.main(["--config", os.path.join(self.tmp, "nope.toml"), "--json"])
        self.assertEqual(rc, 3)
        self.assertEqual(json.loads(buf.getvalue())["summary"]["file_operations"], "BLOCKED")

    def test_main_requires_config_and_sane_timeout(self):
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()):
                D.main([])
        with self.assertRaises(SystemExit):
            D.main(["--config", "x", "--timeout", "0"])

    def test_limitations_mention_hardlink_and_strong(self):
        text = " ".join(D.LIMITATIONS)
        for w in ("STRONG", "Hardlinks", "TOCTOU", "WSL2", "0.0.81"):
            self.assertIn(w, text)


if __name__ == "__main__":
    unittest.main()
