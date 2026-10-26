#!/usr/bin/env python3
"""Testes de supervisor_boot: diagnóstico de FDs herdados (GH-F1.18/PR-B).

Categorias (uma classe por categoria; nenhum teste é contado duas vezes):
- PureLogicTests: dados sintéticos e stubs; provam só a lógica do programa. Não
  tocam descritores nem /proc.
- ChildProcessTests: código REAL contra /proc/self/fd, fcntl e kcmp em
  subprocessos descartáveis (python -I), sem mocks.
- ChildMixedTests: idem, mas o finding principal depende de uma falha injetada
  (listagem adulterada, os.open trocado etc.) DENTRO do subprocesso.
Toda manipulação de FD ocorre só nos filhos; o processo do operador e o
terminal nunca são alterados. Timeout/saída malformada do filho = falha
(evidência insuficiente). Sem kcmp o teste é pulado: skip NÃO é evidência.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import supervisor_boot as B
import trusted_root as T

HERE = os.path.dirname(os.path.abspath(__file__))

CHILD = r"""
import json, os, resource, sys, threading
sys.path.insert(0, sys.argv[1])
import supervisor_boot as B
probe, steps = sys.argv[2], sys.argv[3:]
reg = B.CapabilityRegistry()
notes, stages, pipes = {}, [], []
real_open, real_list, real_describe = os.open, B._list_fd_names, B._describe_fd


def attempt(name, fn):
    try:
        fn()
        notes[name] = "NO_ERROR"
    except Exception as e:
        notes[name] = type(e).__name__


def listing(transform):
    B._list_fd_names = lambda: transform(real_list())


def drop(names, *fds):
    return [n for n in names if int(n) not in fds]


def real_transient(names):
    import fcntl
    gone = []
    for n in names:
        try:
            fcntl.fcntl(int(n), fcntl.F_GETFD)
        except OSError:
            gone.append(int(n))
    return gone


for step in steps:
    if step.startswith("devnull"):
        n = int(step[7:])
        try:
            reg.place_devnull(n)
            notes["place%d" % n] = "ok"
        except B.BootRefused as e:
            notes["place%d" % n] = e.code
    elif step.startswith("close"):
        os.close(int(step[5:]))
    elif step == "pipe":
        pipes.append(reg.make_pipe())
    elif step == "rawfile":
        real_open(probe, os.O_RDONLY | os.O_CLOEXEC)
    elif step == "rawfile_inherit":
        os.set_inheritable(real_open(probe, os.O_RDONLY), True)
    elif step.startswith("swap"):
        src = real_open(probe, os.O_RDONLY | os.O_CLOEXEC)
        os.dup2(src, int(step[4:]))
        os.close(src)
    elif step == "pipeswap_rw":
        os.dup2(pipes[0][1], pipes[0][0], inheritable=False)
    elif step == "pipeswap_wr":
        os.dup2(pipes[0][0], pipes[0][1], inheritable=False)
    elif step == "pipeswap_rw_inh":
        os.dup2(pipes[0][1], pipes[0][0])
    elif step == "reopen1":
        src = real_open("/dev/null", os.O_RDWR | os.O_CLOEXEC)
        os.dup2(src, 1, inheritable=True)
        os.close(src)
    elif step == "fake_devnull":
        os.open = lambda p, f, *a, **k: (real_open(probe, os.O_RDONLY | os.O_CLOEXEC)
                                         if p == "/dev/null" else real_open(p, f, *a, **k))
    elif step == "restore_open":
        os.open = real_open
    elif step == "forge":
        def setitem():
            reg.grants[9] = object()
        attempt("grants_setitem", setitem)
        attempt("grants_assign", lambda: setattr(reg, "grants", {}))
        attempt("new_attribute", lambda: setattr(reg, "extra", 1))
        attempt("grant_ctor", lambda: B.Grant(5, "regular", 1, 2, 0, False, "x", 9))
        attempt("grants_pop", lambda: reg.grants.pop(1))
    elif step == "list_omit_real":
        listing(lambda names: drop(names, pipes[0][0]))
    elif step == "list_omit_real_fake_transient":
        listing(lambda names: drop(names, pipes[0][0], *real_transient(names)) + ["999"])
    elif step == "list_fake_transient":
        listing(lambda names: names + ["999"])
    elif step == "list_swap_transient":      # inofensivo: só troca o número transitório
        listing(lambda names: drop(names, *real_transient(names)) + ["999"])
    elif step == "list_dupes":
        listing(lambda names: names + names[:1])
    elif step == "list_garbage":
        listing(lambda names: ["x"])
    elif step == "list_oserror":
        def boom():
            raise OSError(5, "io")
        B._list_fd_names = boom
    elif step == "unstable":
        calls = {}

        def flaky(fd):
            entry = real_describe(fd)
            calls[fd] = calls.get(fd, 0) + 1
            if fd == pipes[0][0] and calls[fd] > 1:
                entry = dict(entry, ino=entry["ino"] + 1)
            return entry
        B._describe_fd = flaky
    elif step == "describe_eacces":
        def denied(fd):
            raise PermissionError(13, "denied")
        B._describe_fd = denied
    elif step == "proc_mismatch":
        real_readlink = os.readlink
        os.readlink = lambda p, *a, **k: "1" if p == "/proc/self" else real_readlink(p, *a, **k)
    elif step == "threads":
        B.threading.active_count = lambda: 2
    elif step == "rlimit_inf":
        B.resource.getrlimit = lambda r: (resource.RLIM_INFINITY, resource.RLIM_INFINITY)
    elif step == "platform_darwin":
        B.sys.platform = "darwin"
    elif step == "eval":
        stages.append(B.diagnose(reg))
    else:
        raise SystemExit("passo desconhecido")
with open(probe + ".result", "w") as out:
    json.dump({"stages": stages, "notes": notes, "pipes": pipes}, out)
"""


def run_child(steps=(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, pass_fds=()):
    """Roda os passos num subprocesso descartável; devolve o JSON do filho."""
    with tempfile.TemporaryDirectory(prefix="gh-f1-18-boot-") as tmp:
        probe = os.path.join(tmp, "probe")
        with open(probe, "w") as f:
            f.write("FICTIONAL")
        proc = subprocess.run(
            [sys.executable, "-I", "-c", CHILD, HERE, probe, *steps],
            stdin=stdin, stdout=stdout, stderr=stderr, pass_fds=pass_fds,
            timeout=60, close_fds=True, env={})
        result = probe + ".result"
        if proc.returncode != 0 or not os.path.exists(result):
            raise AssertionError("filho falhou (evidência insuficiente): rc=%s" % proc.returncode)
        with open(result) as f:
            return json.load(f)


def final(steps=(), **kw):
    return run_child([*steps, "eval"], **kw)["stages"][-1]


CLEAN_STD = ["devnull0", "devnull1", "devnull2"]


def mismatch_of(report, fd):
    return set(next(e for e in report["entries"] if e["fd"] == fd)["mismatch"])


def entry(fd, kind="chr_devnull", dev=5, ino=6, cloexec=False, flags=2,
          target="/dev/null", opath=False, access="rdwr"):
    return {"fd": fd, "kind": kind, "dev": dev, "ino": ino, "cloexec": cloexec,
            "flags": flags, "access": access, "opath": opath, "target": target}


def inventory(*entries, **over):
    inv = {"structurally_consistent": True, "entries": list(entries), "transient": 1,
           "sentinel_verified": True, "probe_agrees": True, "probe_range": 1024}
    inv.update(over)
    return inv


def grant(fd, kind="chr_devnull", dev=5, ino=6, flags=2, inheritable=True, anchor=None):
    return B._mint_grant(fd, kind, dev, ino, flags, inheritable, "stdio_devnull",
                         100 + fd if anchor is None else anchor)


def std_inventory():
    return inventory(entry(0), entry(1), entry(2))


def std_registry():
    return B._registry_with(grant(0), grant(1), grant(2))


def ev(inv, reg, same=lambda a, b: True):
    return B._evaluate(inv, reg, same)


class PureLogicTests(unittest.TestCase):
    def refused(self, code, inv, reg=None, same=lambda a, b: True):
        with self.assertRaises(B.BootRefused) as caught:
            B._evaluate(inv, reg or std_registry(), same)
        self.assertEqual(caught.exception.code, code)

    def test_positive_control_all_granted(self):
        report = ev(std_inventory(), std_registry())
        self.assertEqual(report["verdict"], "CLEAN_FOR_GRANTS")
        self.assertEqual(report["unknown_fds"], [])

    def test_clean_is_not_a_completeness_or_trust_claim(self):
        report = ev(std_inventory(), std_registry())
        self.assertEqual(report["strong"], "UNAVAILABLE")
        self.assertEqual(report["readiness"], "BLOCKED")
        for flag in ("agent_execution_authorized", "file_operations_authorized",
                     "cloud_call_authorized", "data_transfer_authorized",
                     "bootstrap_trusted", "bootstrap_complete", "close_range_used",
                     "inventory_effectively_complete", "unobserved_capabilities_excluded"):
            self.assertIs(report[flag], False)
        self.assertIs(report["inventory_structurally_consistent"], True)
        self.assertTrue(report["limitations"] and report["not_verified"])

    def test_extra_fd_and_sensitive_slots_are_unknown(self):
        report = ev(inventory(entry(0), entry(1), entry(2),
                              entry(7, "regular", 1, 2, True, 0, "<redacted-path>")),
                    std_registry())
        self.assertEqual(report["unknown_fds"], [7])
        for kind in ("socket", "regular", "directory", "tty", "fifo"):
            report = ev(inventory(entry(0, kind, 9, 9), entry(1), entry(2)), std_registry())
            self.assertEqual(report["unknown_fds"], [0], kind)
            self.assertEqual(report["entries"][0]["reason"], "grant_mismatch")
            self.assertIn("identity", report["entries"][0]["mismatch"])

    def test_rights_are_compared_strictly(self):
        # Mesmo objeto (kind/dev/ino), direito diferente => unknown.
        cases = {
            "access": entry(0, flags=0, access="rdonly"),
            "opath": entry(0, flags=2 | os.O_PATH, opath=True),
            "flags": entry(0, flags=2 | os.O_APPEND),
            "cloexec": entry(0, cloexec=True),
        }
        for name, bad in cases.items():
            report = ev(inventory(bad, entry(1), entry(2)), std_registry())
            self.assertEqual(report["unknown_fds"], [0], name)
            self.assertIn(name, report["entries"][0]["mismatch"])
            self.assertNotIn("identity", report["entries"][0]["mismatch"])
        ev(std_inventory(), std_registry())  # controle positivo

    def test_read_grant_does_not_authorize_write_end(self):
        reg = B._registry_with(grant(5, "fifo", 7, 8, flags=0, inheritable=False),
                               grant(6, "fifo", 7, 8, flags=1, inheritable=False))
        good = [entry(5, "fifo", 7, 8, True, 0, "pipe:[1]", access="rdonly"),
                entry(6, "fifo", 7, 8, True, 1, "pipe:[1]", access="wronly")]
        base = [entry(0), entry(1), entry(2)]
        self.assertEqual(ev(inventory(*base, *good), B._registry_with(
            grant(0), grant(1), grant(2), *reg.grants.values()))["unknown_fds"], [])
        swapped = [dict(good[1], fd=5), dict(good[0], fd=6)]  # extremos trocados
        report = ev(inventory(*base, *swapped), B._registry_with(
            grant(0), grant(1), grant(2), *reg.grants.values()))
        self.assertEqual(report["unknown_fds"], [5, 6])
        self.assertEqual(set(report["entries"][3]["mismatch"]), {"access"})

    def test_ofd_replacement_or_unverifiable_is_unknown(self):
        report = ev(std_inventory(), std_registry(), lambda a, b: False)
        self.assertEqual(report["unknown_fds"], [0, 1, 2])
        self.assertEqual(report["entries"][0]["mismatch"], ["ofd"])
        report = ev(std_inventory(), std_registry(), lambda a, b: None)
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")
        self.assertEqual(report["entries"][0]["mismatch"], ["ofd_unverifiable"])

    def test_registry_anchors_are_accounted_for_but_not_trusted_blindly(self):
        reg = B._registry_with(grant(0, anchor=10), grant(1, anchor=11), grant(2, anchor=12))
        anchors = [entry(10, cloexec=True), entry(11, cloexec=True), entry(12, cloexec=True)]
        report = ev(inventory(entry(0), entry(1), entry(2), *anchors), reg)
        self.assertEqual(report["verdict"], "CLEAN_FOR_GRANTS")
        self.assertEqual(report["entries"][3]["reason"], "registry_anchor")
        bad = [entry(10, cloexec=False), *anchors[1:]]       # âncora herdável
        report = ev(inventory(entry(0), entry(1), entry(2), *bad), reg)
        self.assertEqual(report["unknown_fds"], [10])
        bad = [entry(10, "regular", 1, 1, True), *anchors[1:]]  # âncora trocada
        self.assertEqual(ev(inventory(entry(0), entry(1), entry(2), *bad), reg)["unknown_fds"], [10])

    def test_closed_stdio_and_vanished_grant_are_not_clean(self):
        report = ev(inventory(entry(0), entry(1)), std_registry())
        self.assertEqual(report["std_closed"], [2])
        self.assertEqual(report["grants_missing"], [2])
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")

    def test_cloexec_unknown_is_still_reported(self):
        report = ev(inventory(entry(0), entry(1), entry(2),
                              entry(5, "regular", 1, 2, True, 0, "<redacted-path>")),
                    std_registry())
        self.assertTrue(report["entries"][3]["cloexec"])
        self.assertEqual(report["entries"][3]["status"], "unknown")

    def test_inconsistent_and_malformed_inventories_are_refused(self):
        ev(std_inventory(), std_registry())  # controle positivo
        cases = {
            "inventory_inconsistent": [{"structurally_consistent": False},
                                       {"sentinel_verified": False},
                                       {"probe_agrees": False}],
            "inventory_malformed": [
                {"entries": None}, {"transient": "1"}, {"probe_range": None},
                {"probe_agrees": 1}, {"entries": [entry(0), entry(0)]},
                {"entries": [entry(0), {**entry(1), "fd": True}]},
                {"entries": [entry(0), {**entry(1), "fd": -1}]},
                {"entries": [entry(0), {**entry(1), "kind": "wormhole"}]},
                {"entries": [entry(0), {**entry(1), "cloexec": 1}]},
                {"entries": [entry(0), {k: v for k, v in entry(1).items() if k != "ino"}]},
                {"entries": [entry(0), {**entry(1), "extra": 1}]},
                {"entries": ["fd=1"]}, {"surprise": 1}],
        }
        for code, mutations in cases.items():
            for mutation in mutations:
                self.refused(code, {**std_inventory(), **mutation})
        legacy = std_inventory()
        legacy["complete"] = True
        del legacy["probe_agrees"]
        self.refused("inventory_malformed", legacy)
        for junk in (None, [], "x", {}):
            self.refused("inventory_malformed", junk)

    def test_registry_cannot_be_forged_through_public_surface(self):
        reg = B.CapabilityRegistry()
        with self.assertRaises(TypeError):
            reg.grants[9] = object()
        with self.assertRaises(AttributeError):
            reg.grants = {}
        with self.assertRaises(AttributeError):
            reg.other = 1
        with self.assertRaises(TypeError):
            B.Grant(5, "regular", 1, 2, 0, False, "x", 9)
        with self.assertRaises(TypeError):
            B.Grant(5, "regular", 1, 2, 0, False, "x", 9, _mint=object())

        class Sub(B.CapabilityRegistry):
            pass
        self.refused("invalid_registry", std_inventory(), Sub())
        self.refused("invalid_registry", std_inventory(), {"grants": {}})
        # Mesmo adulterando o dict PRIVADO (fora da garantia), o conteúdo é validado:
        tampered = std_registry()
        tampered._grants[0] = ("0", "chr_devnull")
        self.refused("invalid_grant", std_inventory(), tampered)
        wild = B._registry_with(B._mint_grant(9, "kernel_gift", 1, 1, 0, False, "x", 99))
        self.refused("unexpected_capability_kind", std_inventory(), wild)
        collide = B._registry_with(grant(0, anchor=1), grant(1, anchor=1))
        self.refused("invalid_grant", std_inventory(), collide)

    def test_place_devnull_rejects_targets_outside_stdio_before_touching_fds(self):
        for bad in (3, -1, 99, "1", None, True.__class__):
            with self.assertRaises(B.BootRefused) as caught:
                B.CapabilityRegistry().place_devnull(bad)
            self.assertEqual(caught.exception.code, "invalid_target")

    def test_reserved_report_fields_cannot_be_overridden(self):
        base = B._report("UNKNOWN_CAPABILITIES")
        self.assertEqual(base["verdict"], "UNKNOWN_CAPABILITIES")
        for field, value in (("strong", "STRONG"), ("readiness", "READY"),
                             ("agent_execution_authorized", True),
                             ("file_operations_authorized", True),
                             ("cloud_call_authorized", True),
                             ("data_transfer_authorized", True),
                             ("bootstrap_trusted", True), ("bootstrap_complete", True),
                             ("verdict", "CLEAN_FOR_GRANTS"), ("schema", "x"),
                             ("inventory_effectively_complete", True),
                             ("limitations", [])):
            with self.assertRaises(ValueError, msg=field) as caught:
                B._report("REFUSED", **{field: value})
            self.assertEqual(str(caught.exception), "reserved_field")
        with self.assertRaises(ValueError):
            B._report("TRUSTED")

    def test_invariants_are_read_only_and_reports_are_independent_copies(self):
        with self.assertRaises(TypeError):
            T.INVARIANTS["strong"] = "STRONG"
        self.assertIs(B.INVARIANTS, T.INVARIANTS)
        report = B._report("REFUSED", reason="x")
        report["strong"] = "STRONG"            # alterar a cópia não toca a constante
        self.assertEqual(T.INVARIANTS["strong"], "UNAVAILABLE")
        self.assertEqual(B._report("REFUSED")["strong"], "UNAVAILABLE")

    def test_check_report_rejects_tampered_or_mistyped_invariants(self):
        good = B._report("REFUSED")
        T.check_report(good)
        for key, value in (("agent_execution_authorized", True),
                           ("agent_execution_authorized", 0),
                           ("file_operations_authorized", "false"),
                           ("cloud_call_authorized", None),
                           ("data_transfer_authorized", 1),
                           ("strong", "STRONG"), ("readiness", "OK"),
                           ("bootstrap_trusted", True)):
            bad = dict(good)
            bad[key] = value
            with self.assertRaises(ValueError, msg=(key, value)):
                T.check_report(bad)
        missing = dict(good)
        del missing["readiness"]
        for junk in (missing, None, [], "x"):
            with self.assertRaises(ValueError):
                T.check_report(junk)

    def test_diagnose_turns_every_failure_into_refusal(self):
        reg = std_registry()

        def boom():
            raise OSError("syscall failure")
        for collect in (boom, lambda: None, lambda: "garbage", lambda: {}):
            report = B._diagnose(reg, collect)
            self.assertEqual(report["verdict"], "REFUSED")
            self.assertIs(report["bootstrap_trusted"], False)
        self.assertEqual(B._diagnose(reg, boom)["reason"], "evidence_insufficient")
        self.assertEqual(B._diagnose(reg, lambda: {"sentinel_verified": True})["reason"],
                         "inventory_malformed")

    def test_public_diagnose_has_no_injectable_collector(self):
        import inspect
        self.assertEqual(list(inspect.signature(B.diagnose).parameters), ["registry"])

    def test_source_does_not_use_close_range_for_inventory(self):
        with open(os.path.join(HERE, "supervisor_boot.py")) as f:
            code = [l for l in f.read().splitlines() if not l.lstrip().startswith(("#", '"""'))]
        self.assertFalse([l for l in code if "close_range(" in l])


class ChildProcessTests(unittest.TestCase):
    """Código real contra /proc/self/fd, fcntl e kcmp; sem mocks."""

    @classmethod
    def setUpClass(cls):
        control = final(CLEAN_STD)
        if any("ofd_unverifiable" in e["mismatch"] for e in control.get("entries", [])):
            raise unittest.SkipTest("kcmp indisponível: SKIP NÃO é evidência")

    def test_positive_control_clean_child(self):
        report = final(CLEAN_STD)
        self.assertEqual(report["verdict"], "CLEAN_FOR_GRANTS", report)
        # 3 FDs padrão + 3 âncoras privadas do registro (>= 3, CLOEXEC)
        stdio = [e for e in report["entries"] if e["fd"] <= 2]
        anchors = [e for e in report["entries"] if e["fd"] > 2]
        self.assertEqual([e["fd"] for e in stdio], [0, 1, 2])
        self.assertTrue(all(e["kind"] == "chr_devnull" and not e["cloexec"]
                            and e["access"] == "rdwr" for e in stdio))
        self.assertEqual(len(anchors), 3)
        self.assertTrue(all(e["cloexec"] and e["reason"] == "registry_anchor" for e in anchors))
        self.assertIs(report["bootstrap_trusted"], False)
        self.assertIs(report["inventory_effectively_complete"], False)

    def test_inherited_extra_fd_is_unknown_with_control(self):
        self.assertEqual(final(CLEAN_STD)["unknown_fds"], [])
        with tempfile.TemporaryFile() as secret:
            secret.write(b"FICTIONAL-SECRET")
            report = final(CLEAN_STD, pass_fds=(secret.fileno(),))
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")
        extra = [e for e in report["entries"] if e["status"] == "unknown"]
        self.assertEqual(len(extra), 1)
        self.assertFalse(extra[0]["cloexec"])  # herdável, atravessaria execve
        self.assertEqual(extra[0]["target"], "<redacted-path>")

    def test_sensitive_fds_in_slots_0_1_2_are_unknown_with_control(self):
        import socket
        self.assertEqual(final(CLEAN_STD)["verdict"], "CLEAN_FOR_GRANTS")
        left, right = socket.socketpair()
        r, w = os.pipe()
        try:
            with left, right, tempfile.TemporaryFile() as regular:
                report = final(CLEAN_STD[1:], stdin=regular)
                self.assertEqual(report["unknown_fds"], [0])
                self.assertEqual(report["entries"][0]["kind"], "regular")
                report = final(CLEAN_STD[:1] + CLEAN_STD[2:], stdout=right.fileno())
                self.assertEqual(report["unknown_fds"], [1])
                self.assertEqual(report["entries"][1]["kind"], "socket")
                report = final(CLEAN_STD[:2], stderr=w)
                self.assertEqual(report["unknown_fds"], [2])
                self.assertEqual(report["entries"][2]["kind"], "fifo")
        finally:
            os.close(r)
            os.close(w)

    def test_place_devnull_replaces_inherited_object_in_each_std_slot(self):
        with tempfile.TemporaryFile() as regular:
            for slot in (0, 1, 2):
                kw = {("stdin", "stdout", "stderr")[slot]: regular}
                before = final([s for s in CLEAN_STD if s != "devnull%d" % slot], **kw)
                self.assertEqual(before["unknown_fds"], [slot])      # controle negativo
                after = final(CLEAN_STD, **kw)                        # fábrica substitui
                self.assertEqual(after["verdict"], "CLEAN_FOR_GRANTS", slot)
                self.assertEqual(after["entries"][slot]["kind"], "chr_devnull")

    def test_place_devnull_when_slot_was_closed_and_number_is_reused(self):
        for slot in (0, 1, 2):
            others = [s for s in CLEAN_STD if s != "devnull%d" % slot]
            result = run_child(["close%d" % slot, "devnull%d" % slot, *others, "eval"])
            report = result["stages"][-1]
            self.assertEqual(result["notes"]["place%d" % slot], "ok")
            self.assertEqual(report["verdict"], "CLEAN_FOR_GRANTS", slot)
            state = report["entries"][slot]
            # dup2(fd, fd) sozinho deixaria CLOEXEC ligado: o estado efetivo é herdável
            self.assertEqual((state["kind"], state["cloexec"], state["access"]),
                             ("chr_devnull", False, "rdwr"))
            self.assertEqual(state["status"], "authorized")

    def test_authorized_fd_swapped_for_another_object_is_unknown(self):
        report = final(CLEAN_STD + ["swap1"])
        self.assertEqual(report["unknown_fds"], [1])
        self.assertIn("identity", report["entries"][1]["mismatch"])

    def test_pipe_ends_swapped_are_not_authorized_and_attributes_are_recorded(self):
        control = run_child([*CLEAN_STD, "pipe", "eval"])
        self.assertEqual(control["stages"][-1]["verdict"], "CLEAN_FOR_GRANTS")
        r, w = control["pipes"][0]
        # (a) leitura <- escrita, preservando CLOEXEC (dup2 não herdável)
        a = run_child([*CLEAN_STD, "pipe", "eval", "pipeswap_rw", "eval"])
        self.assertEqual(a["stages"][0]["verdict"], "CLEAN_FOR_GRANTS")
        report = a["stages"][1]
        self.assertEqual(report["unknown_fds"], [r])
        self.assertEqual(mismatch_of(report, r), {"access", "ofd"})
        # mesmo objeto: kind/dev/ino NÃO distinguem os extremos (por isso não bastam)
        self.assertNotIn("identity", mismatch_of(report, r))
        self.assertNotIn("cloexec", mismatch_of(report, r))
        # (b) o inverso: escrita <- leitura
        b = run_child([*CLEAN_STD, "pipe", "eval", "pipeswap_wr", "eval"])
        self.assertEqual(b["stages"][0]["verdict"], "CLEAN_FOR_GRANTS")
        self.assertEqual(b["stages"][1]["unknown_fds"], [w])
        self.assertEqual(mismatch_of(b["stages"][1], w), {"access", "ofd"})
        # (c) dup2 comum também limpa CLOEXEC: atributo adicional diferencia
        c = run_child([*CLEAN_STD, "pipe", "pipeswap_rw_inh", "eval"])
        self.assertEqual(mismatch_of(c["stages"][-1], r), {"access", "ofd", "cloexec"})

    def test_reopening_same_inode_is_detected_only_by_open_file_description(self):
        report = final([*CLEAN_STD, "reopen1"])
        self.assertEqual(report["unknown_fds"], [1])
        # kind, dev, ino, flags e CLOEXEC idênticos: só a OFD (kcmp) diferencia
        self.assertEqual(mismatch_of(report, 1), {"ofd"})

    def test_closed_stdio_and_vanished_grant_in_real_child(self):
        report = final(CLEAN_STD + ["close2"])
        self.assertEqual(report["std_closed"], [2])
        self.assertEqual(report["grants_missing"], [2])
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")

    def test_registry_surface_cannot_be_forged_in_child(self):
        result = run_child([*CLEAN_STD, "forge", "eval"])
        self.assertEqual(result["notes"], {
            **{k: v for k, v in result["notes"].items() if k.startswith("place")},
            "grants_setitem": "TypeError", "grants_assign": "AttributeError",
            "new_attribute": "AttributeError", "grant_ctor": "TypeError",
            "grants_pop": "AttributeError"})
        self.assertEqual(result["stages"][-1]["verdict"], "CLEAN_FOR_GRANTS")

    def test_real_inventory_is_cross_checked_and_never_claims_completeness(self):
        report = final(CLEAN_STD)
        self.assertNotIn("reason", report)
        self.assertIs(report["inventory_structurally_consistent"], True)
        self.assertIs(report["inventory_effectively_complete"], False)
        self.assertIs(report["unobserved_capabilities_excluded"], False)

    def test_cli_is_closed_and_never_exits_zero(self):
        proc = subprocess.run([sys.executable, os.path.join(HERE, "supervisor_boot.py"),
                               "--synthetic-only", "--json"], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2)
        report = json.loads(proc.stdout)
        self.assertIs(report["bootstrap_trusted"], False)
        self.assertEqual(report["readiness"], "BLOCKED")
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")  # sem grants
        self.assertTrue(all("/" not in e["target"] or e["target"] == "/dev/null"
                            for e in report["entries"]))
        bad = subprocess.run([sys.executable, os.path.join(HERE, "supervisor_boot.py"), "--x"],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(bad.returncode, 64)


class ChildMixedTests(unittest.TestCase):
    """Syscalls reais no filho + uma falha injetada que é o finding principal."""

    def test_place_devnull_fails_closed_when_object_is_not_devnull(self):
        for slot in (0, 1, 2):
            others = [s for s in CLEAN_STD if s != "devnull%d" % slot]
            control = run_child(["close%d" % slot, "devnull%d" % slot, *others, "eval"])
            self.assertEqual(control["notes"]["place%d" % slot], "ok")  # controle positivo
            result = run_child(["close%d" % slot, "fake_devnull", "devnull%d" % slot,
                                "restore_open", *others, "eval"])
            self.assertEqual(result["notes"]["place%d" % slot], "devnull_identity")
            report = result["stages"][-1]
            # o slot que a chamada abriu foi devolvido fechado; nada foi concedido
            self.assertEqual(report["std_closed"], [slot])
            self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")

    def test_truncated_listing_omitting_a_real_fd_is_not_accepted(self):
        base = [*CLEAN_STD, "pipe"]
        self.assertEqual(run_child([*base, "eval"])["stages"][-1]["verdict"],
                         "CLEAN_FOR_GRANTS")                                  # controle
        # Omite um FD real; sentinela e o FD transitório REAL continuam na lista.
        omit = final([*base, "list_omit_real"])
        self.assertEqual((omit["verdict"], omit["reason"]), ("REFUSED", "inventory_inconsistent"))
        # Omite o FD real, remove o transitório real e põe um transitório plausível falso.
        forged = final([*base, "list_omit_real_fake_transient"])
        self.assertEqual((forged["verdict"], forged["reason"]),
                         ("REFUSED", "inventory_inconsistent"))
        # Transitório extra falso: dois números listados inexistentes.
        extra = final([*base, "list_fake_transient"])
        self.assertEqual(extra["reason"], "inventory_inconsistent")
        # Trocar apenas o número transitório não omite nada: segue consistente,
        # e ainda assim NÃO vira garantia de completude.
        swapped = final([*base, "list_swap_transient"])
        self.assertEqual(swapped["verdict"], "CLEAN_FOR_GRANTS")
        self.assertIs(swapped["inventory_effectively_complete"], False)

    def test_listing_and_metadata_failures_are_refused(self):
        base = [*CLEAN_STD, "pipe"]
        for step, reason in (("list_dupes", "inventory_malformed"),
                             ("list_garbage", "inventory_malformed"),
                             ("list_oserror", "inventory_unavailable"),
                             ("describe_eacces", "inventory_unavailable"),
                             ("unstable", "inventory_inconsistent"),
                             ("proc_mismatch", "proc_mismatch"),
                             ("threads", "multithreaded"),
                             ("rlimit_inf", "probe_range_exceeded"),
                             ("platform_darwin", "unsupported_platform")):
            report = final([*base, step])
            self.assertEqual((step, report["verdict"], report["reason"]),
                             (step, "REFUSED", reason))
            self.assertIs(report["bootstrap_trusted"], False)


if __name__ == "__main__":
    unittest.main()
