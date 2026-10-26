#!/usr/bin/env python3
"""Testes de supervisor_boot: diagnóstico de FDs herdados (GH-F1.18/PR-B).

- InventoryLogicTests: puros, sobre inventários sintéticos e mocks; provam a
  lógica do programa, não o kernel. Não tocam descritores.
- ChildProcessTests: executam o código REAL contra /proc/self/fd, SEMPRE em
  subprocesso descartável (python -I). Toda manipulação de FD (dup2, pipes,
  herança) acontece só ali; o processo do operador e o terminal real nunca
  são alterados. Timeout ou saída malformada do filho = falha (evidência
  insuficiente).
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import supervisor_boot as B

HERE = os.path.dirname(os.path.abspath(__file__))

CHILD = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
import supervisor_boot as B
reg = B.CapabilityRegistry()
for step in sys.argv[3:]:
    if step.startswith("devnull"):
        reg.place_devnull(int(step[7:]))
    elif step == "pipe":
        reg.make_pipe()
    elif step == "rawfile":                    # aberto sem registro, CLOEXEC
        os.open(sys.argv[2], os.O_RDONLY | os.O_CLOEXEC)
    elif step == "rawfile_inherit":            # aberto sem registro, herdável
        os.set_inheritable(os.open(sys.argv[2], os.O_RDONLY), True)
    elif step.startswith("swap"):              # grant válido, objeto trocado depois
        fd = int(step[4:])
        src = os.open(sys.argv[2], os.O_RDONLY | os.O_CLOEXEC)
        os.dup2(src, fd)
        os.close(src)
    elif step == "closestd2":
        os.close(2)
    else:
        raise SystemExit("passo desconhecido")
report = B.diagnose(reg)
with open(sys.argv[2] + ".result", "w") as out:
    json.dump(report, out)
"""


def child_report(steps=(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, pass_fds=()):
    """Roda o diagnóstico REAL num subprocesso e devolve o relatório."""
    with tempfile.TemporaryDirectory(prefix="gh-f1-18-boot-") as tmp:
        probe = os.path.join(tmp, "probe")
        with open(probe, "w") as f:
            f.write("FICTIONAL")
        proc = subprocess.run(
            [sys.executable, "-I", "-c", CHILD, HERE, probe, *steps],
            stdin=stdin, stdout=stdout, stderr=stderr, pass_fds=pass_fds,
            timeout=30, close_fds=True, env={})
        result = probe + ".result"
        if proc.returncode != 0 or not os.path.exists(result):
            raise AssertionError("filho falhou (evidência insuficiente): rc=%s" % proc.returncode)
        with open(result) as f:
            return json.load(f)


CLEAN_STD = ["devnull0", "devnull1", "devnull2"]


def entry(fd, kind="chr_devnull", dev=5, ino=6, cloexec=False, target="/dev/null"):
    return {"fd": fd, "kind": kind, "dev": dev, "ino": ino, "cloexec": cloexec,
            "flags": 2, "access": "rdwr", "opath": False, "target": target}


def inventory(*entries, **over):
    inv = {"complete": True, "entries": list(entries), "transient": 1,
           "sentinel_verified": True}
    inv.update(over)
    return inv


def registry_with(*grants):
    reg = B.CapabilityRegistry()
    for g in grants:
        reg.grants[g.fd] = g
    return reg


def std_inventory():
    return inventory(entry(0), entry(1), entry(2))


def std_registry():
    return registry_with(*[B.Grant(fd, "chr_devnull", 5, 6, True, "stdio_devnull")
                           for fd in (0, 1, 2)])


class InventoryLogicTests(unittest.TestCase):
    def test_positive_control_all_granted(self):
        report = B.evaluate(std_inventory(), std_registry())
        self.assertEqual(report["verdict"], "CLEAN_FOR_GRANTS")
        self.assertEqual(report["unknown_fds"], [])

    def test_invariants_and_no_trust_claim_even_when_clean(self):
        report = B.evaluate(std_inventory(), std_registry())
        self.assertEqual(report["strong"], "UNAVAILABLE")
        self.assertEqual(report["readiness"], "BLOCKED")
        for flag in ("agent_execution_authorized", "file_operations_authorized",
                     "cloud_call_authorized", "data_transfer_authorized",
                     "bootstrap_trusted", "bootstrap_complete", "close_range_used"):
            self.assertIs(report[flag], False)
        self.assertTrue(report["limitations"] and report["not_verified"])

    def test_extra_fd_is_unknown(self):
        inv = inventory(entry(0), entry(1), entry(2),
                        entry(7, "regular", 1, 2, True, "<redacted-path>"))
        report = B.evaluate(inv, std_registry())
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")
        self.assertEqual(report["unknown_fds"], [7])

    def test_sensitive_object_in_std_slot_is_unknown(self):
        for kind in ("socket", "regular", "directory", "tty", "fifo"):
            inv = inventory(entry(0, kind, 9, 9), entry(1), entry(2))
            report = B.evaluate(inv, std_registry())
            self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES", kind)
            self.assertEqual(report["unknown_fds"], [0])
            self.assertEqual(report["entries"][0]["reason"], "grant_identity_mismatch")

    def test_grant_flag_mismatch_is_unknown(self):
        inv = inventory(entry(0, cloexec=True), entry(1), entry(2))
        report = B.evaluate(inv, std_registry())
        self.assertEqual(report["entries"][0]["reason"], "grant_cloexec_mismatch")
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")

    def test_closed_stdio_and_vanished_grant_are_not_clean(self):
        report = B.evaluate(inventory(entry(0), entry(1)), std_registry())
        self.assertEqual(report["std_closed"], [2])
        self.assertEqual(report["grants_missing"], [2])
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")

    def test_cloexec_unknown_is_still_reported(self):
        inv = inventory(entry(0), entry(1), entry(2),
                        entry(5, "regular", 1, 2, True, "<redacted-path>"))
        report = B.evaluate(inv, std_registry())
        self.assertTrue(report["entries"][3]["cloexec"])
        self.assertEqual(report["entries"][3]["status"], "unknown")

    def test_incomplete_and_malformed_inventories_are_refused(self):
        good = std_inventory()
        B.evaluate(good, std_registry())  # controle positivo
        cases = {
            "inventory_incomplete": [{"complete": False}, {"sentinel_verified": False}],
            "inventory_malformed": [
                {"entries": None}, {"transient": "1"}, {"entries": [entry(0), entry(0)]},
                {"entries": [entry(0), {**entry(1), "fd": True}]},
                {"entries": [entry(0), {**entry(1), "fd": -1}]},
                {"entries": [entry(0), {**entry(1), "kind": "wormhole"}]},
                {"entries": [entry(0), {**entry(1), "cloexec": 1}]},
                {"entries": [entry(0), {k: v for k, v in entry(1).items() if k != "ino"}]},
                {"entries": [entry(0), {**entry(1), "extra": 1}]},
                {"entries": ["fd=1"]},
            ],
        }
        for code, mutations in cases.items():
            for mutation in mutations:
                bad = copy.deepcopy(good)
                bad.update(mutation)
                with self.assertRaises(B.BootRefused, msg=str(mutation)) as caught:
                    B.evaluate(bad, std_registry())
                self.assertEqual(caught.exception.code, code, str(mutation))
        for junk in (None, [], "x", {}, {**good, "surprise": 1}):
            with self.assertRaises(B.BootRefused):
                B.evaluate(junk, std_registry())

    def test_unexpected_capability_kind_cannot_be_registered(self):
        reg = registry_with(B.Grant(9, "kernel_gift", 1, 1, False, "x"))
        with self.assertRaises(B.BootRefused) as caught:
            B.evaluate(std_inventory(), reg)
        self.assertEqual(caught.exception.code, "unexpected_capability_kind")
        with self.assertRaises(B.BootRefused):
            B.evaluate(std_inventory(), {"grants": {}})  # registro forjado
        with self.assertRaises(B.BootRefused):
            B.CapabilityRegistry().place_devnull(3)  # só 0, 1, 2

    def test_diagnose_turns_every_failure_into_refusal(self):
        reg = std_registry()
        self.assertEqual(B.diagnose(reg, lambda: std_inventory())["verdict"], "CLEAN_FOR_GRANTS")

        def boom():
            raise OSError("syscall failure")
        for collect in (boom, lambda: None, lambda: "garbage", lambda: {}):
            report = B.diagnose(reg, collect)
            self.assertEqual(report["verdict"], "REFUSED")
            self.assertIs(report["bootstrap_trusted"], False)
        self.assertEqual(B.diagnose(reg, boom)["reason"], "evidence_insufficient")

    def test_collect_failures_are_refusals_not_silence(self):
        with mock.patch.object(B.sys, "platform", "darwin"):
            self.assertEqual(B.diagnose(B.CapabilityRegistry())["reason"],
                             "unsupported_platform")
        with mock.patch.object(B.os, "listdir", side_effect=OSError(5, "io")):
            self.assertEqual(B.diagnose(B.CapabilityRegistry())["reason"],
                             "inventory_unavailable")
        with mock.patch.object(B.threading, "active_count", return_value=2):
            self.assertEqual(B.diagnose(B.CapabilityRegistry())["reason"], "multithreaded")

    def test_incomplete_collect_is_refused_when_listing_is_truncated(self):
        # Lista sem o FD sentinela: a coleta real marca complete=False e recusa.
        real = os.listdir

        def truncated(path, *a):
            names = real(path, *a)
            return names[:1] if path == "/proc/self/fd" else names
        with mock.patch.object(B.os, "listdir", side_effect=truncated):
            report = B.diagnose(B.CapabilityRegistry())
        self.assertEqual(report["verdict"], "REFUSED")
        self.assertIn(report["reason"], ("inventory_incomplete", "evidence_insufficient"))

    def test_source_does_not_use_close_range_for_inventory(self):
        with open(os.path.join(HERE, "supervisor_boot.py")) as f:
            code = [l for l in f.read().splitlines() if not l.lstrip().startswith(("#", '"""'))]
        self.assertFalse([l for l in code if "close_range(" in l])


class ChildProcessTests(unittest.TestCase):
    """Código real contra /proc/self/fd, só em subprocessos descartáveis."""

    def test_positive_control_clean_child(self):
        report = child_report(CLEAN_STD)
        self.assertEqual(report["verdict"], "CLEAN_FOR_GRANTS", report)
        self.assertEqual([e["fd"] for e in report["entries"]], [0, 1, 2])
        self.assertTrue(all(e["kind"] == "chr_devnull" for e in report["entries"]))
        self.assertIs(report["bootstrap_trusted"], False)

    def test_inherited_extra_fd_is_unknown_with_control(self):
        control = child_report(CLEAN_STD)
        self.assertEqual(control["unknown_fds"], [])
        with tempfile.TemporaryFile() as secret:
            secret.write(b"FICTIONAL-SECRET")
            report = child_report(CLEAN_STD, pass_fds=(secret.fileno(),))
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")
        self.assertEqual(len(report["unknown_fds"]), 1)
        extra = [e for e in report["entries"] if e["status"] == "unknown"][0]
        self.assertGreater(extra["fd"], 2)
        self.assertFalse(extra["cloexec"])  # herdável, atravessaria execve
        self.assertNotIn("tmp", extra["target"])  # caminho redigido

    def test_sensitive_fds_in_slots_0_1_2_are_unknown_with_control(self):
        control = child_report(CLEAN_STD)
        self.assertEqual(control["verdict"], "CLEAN_FOR_GRANTS")
        import socket
        left, right = socket.socketpair()
        with left, right, tempfile.TemporaryFile() as regular:
            report = child_report(CLEAN_STD[1:], stdin=regular, )  # fd 0: arquivo
            self.assertEqual(report["unknown_fds"], [0])
            self.assertEqual(report["entries"][0]["kind"], "regular")
            report = child_report(CLEAN_STD[:1] + CLEAN_STD[2:], stdout=right.fileno())
            self.assertEqual(report["unknown_fds"], [1])
            self.assertEqual(report["entries"][1]["kind"], "socket")
        r, w = os.pipe()
        try:
            report = child_report(CLEAN_STD[:2], stderr=w)
            self.assertEqual(report["unknown_fds"], [2])
            self.assertEqual(report["entries"][2]["kind"], "fifo")
        finally:
            os.close(r)
            os.close(w)

    def test_raw_opened_fd_is_unknown_but_registered_pipe_is_authorized(self):
        registered = child_report(CLEAN_STD + ["pipe"])
        self.assertEqual(registered["verdict"], "CLEAN_FOR_GRANTS")
        self.assertEqual(len(registered["entries"]), 5)
        raw = child_report(CLEAN_STD + ["pipe", "rawfile"])
        self.assertEqual(raw["verdict"], "UNKNOWN_CAPABILITIES")
        unknown = [e for e in raw["entries"] if e["status"] == "unknown"]
        self.assertEqual(len(unknown), 1)
        self.assertTrue(unknown[0]["cloexec"])  # CLOEXEC não o torna autorizado
        inherit = child_report(CLEAN_STD + ["rawfile_inherit"])
        self.assertFalse([e for e in inherit["entries"] if e["status"] == "unknown"][0]["cloexec"])

    def test_authorized_fd_swapped_for_another_object_is_unknown(self):
        report = child_report(CLEAN_STD + ["swap1"])
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")
        self.assertEqual(report["unknown_fds"], [1])
        self.assertEqual(report["entries"][1]["reason"], "grant_identity_mismatch")

    def test_closed_stdio_and_vanished_grant_in_real_child(self):
        report = child_report(CLEAN_STD + ["closestd2"])
        self.assertEqual(report["std_closed"], [2])
        self.assertEqual(report["grants_missing"], [2])
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")

    def test_child_inventory_is_complete_and_excludes_listing_fd(self):
        report = child_report(CLEAN_STD)
        self.assertNotIn("reason", report)
        fds = [e["fd"] for e in report["entries"]]
        self.assertEqual(fds, sorted(set(fds)))
        self.assertEqual(max(fds), 2)  # nem sentinela nem FD da listagem vazam

    def test_cli_is_closed_and_never_exits_zero(self):
        proc = subprocess.run([sys.executable, os.path.join(HERE, "supervisor_boot.py"),
                               "--synthetic-only", "--json"], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2)
        report = json.loads(proc.stdout)
        self.assertIs(report["bootstrap_trusted"], False)
        self.assertEqual(report["readiness"], "BLOCKED")
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")  # sem grants
        self.assertTrue(all("/" not in e["target"] or e["target"] == "/dev/null"
                            for e in report["entries"]))
        bad = subprocess.run([sys.executable, os.path.join(HERE, "supervisor_boot.py"), "--x"],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(bad.returncode, 64)


if __name__ == "__main__":
    unittest.main()
