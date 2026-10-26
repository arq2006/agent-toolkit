#!/usr/bin/env python3
"""Testes de supervisor_boot: diagnóstico de FDs herdados (GH-F1.18/PR-B).

Categorias (uma classe por categoria; nenhum teste é contado duas vezes):
- PureLogicTests: dados sintéticos e stubs; provam só a lógica do programa. Não
  tocam descritores nem /proc.
- ChildProcessTests: código REAL contra /proc/self/fd, fcntl e kcmp em
  subprocessos descartáveis (python -I), sem mocks.
- ChildMixedTests: idem, mas o finding principal depende de uma falha injetada
  (listagem adulterada, os.open trocado etc.) DENTRO do subprocesso.
Os testes puros montam registros sintéticos com o helper LOCAL
`synthetic_registry`, que escreve no estado privado do registro (o que código
no mesmo processo sempre poderia fazer: fora da garantia); o módulo de produção
não oferece nenhuma API para isso.
Toda manipulação de FD ocorre só nos filhos; o processo do operador e o
terminal nunca são alterados. Timeout/saída malformada do filho = falha
(evidência insuficiente). Sem kcmp o teste é pulado: skip NÃO é evidência.
"""
import contextlib
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


real_fcntl = B.fcntl.fcntl
base = set()


def openset():
    found = set()
    for fd in range(256):
        try:
            real_fcntl(fd, B.fcntl.F_GETFD)
            found.add(fd)
        except OSError:
            pass
    return found


def failing(nth):
    calls = [0]

    def fn(fd, cmd, *a):
        if cmd == B.fcntl.F_DUPFD_CLOEXEC:
            calls[0] += 1
            if calls[0] == nth:
                raise OSError(24, "EMFILE")
        return real_fcntl(fd, cmd, *a)
    B.fcntl.fcntl = fn


def attempt(name, fn):
    try:
        fn()
        notes[name] = "NO_ERROR"
    except B.BootRefused as e:
        notes[name] = "BootRefused:" + e.code
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
        try:
            pipes.append(reg.make_pipe())
        except B.BootRefused as e:
            notes["pipe"] = e.code
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
        attempt("grant_by_declaration",
                lambda: reg._issue(B.Grant(5, "regular", 1, 2, 0, False, "x", 9)))
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
    elif step == "mark_base":
        base = openset()
    elif step.startswith("diff:"):
        now = openset()
        notes[step[5:]] = {"added": sorted(now - base), "removed": sorted(base - now)}
    elif step == "fail_anchor":
        failing(1)
    elif step == "fail_anchor_second":
        failing(2)
    elif step == "restore_fcntl":
        B.fcntl.fcntl = real_fcntl
    elif step == "declare_int":
        for fd in (0, 1, 2):
            attempt("declare%d" % fd, lambda fd=fd: reg._issue(fd))
    elif step == "declare_forged":
        forged = B._Created(0, 3, B._describe_fd(0), "forged", True)
        attempt("declare_forged", lambda: reg._issue(forged))
    elif step == "shutdown_registry":
        reg.close()
        reg.close()                                  # idempotente
        attempt("place_after_close", lambda: reg.place_devnull(0))
        attempt("pipe_after_close", lambda: reg.make_pipe())
        notes["grants_after_close"] = len(reg.grants)
    elif step == "reuse_closed_pipe_read":
        os.close(pipes[0][0])
        real_open(probe, os.O_RDONLY | os.O_CLOEXEC)
    elif step == "kernel_objects":
        import select, socket
        keep = [select.epoll(), socket.socketpair(), os.eventfd(0), os.pipe()]
        notes["kernel_objects"] = len(keep)
    elif step == "kcmp_unavailable":
        B.platform.machine = lambda: "riscv64"
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

# Filho dedicado às injeções de falha do registro: uma falha por execução, em um
# ponto nomeado, com verificação do conjunto REAL de FDs abertos e do estado.
CHILD_FAULT = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
import supervisor_boot as B
factory, where, nth, slot, interpose = (sys.argv[2], sys.argv[3], int(sys.argv[4]),
                                        sys.argv[5], sys.argv[6] == "1")
real_fcntl, real_close, real_open = B.fcntl.fcntl, os.close, os.open


def openset():
    found = set()
    for fd in range(256):
        try:
            real_fcntl(fd, B.fcntl.F_GETFD)
            found.add(fd)
        except OSError:
            pass
    return found


class Boom(RuntimeError):
    pass


count = [0]


def tick():
    count[0] += 1
    if count[0] == nth:
        raise Boom("/home/fictional-user/segredo")


class FailList(list):
    def append(self, item):
        tick()
        super().append(item)


class FailDict(dict):
    def __setitem__(self, key, value):
        tick()
        super().__setitem__(key, value)


class FailSet(set):
    def add(self, item):
        tick()
        super().add(item)


reg = B.CapabilityRegistry()
target = 1
if factory == "place" and slot == "closed":
    real_close(target)
before = openset()
closed_log, interposed = [], []


def close_wrap(fd):
    closed_log.append(fd)
    src = real_open("/dev/null", os.O_RDONLY | os.O_CLOEXEC) if interpose else None
    real_close(fd)
    if interpose:      # um FD novo assume IMEDIATAMENTE o número que acabou de ser liberado
        os.dup2(src, fd, inheritable=False)
        real_close(src)
        interposed.append(fd)


if where == "anchor":
    def fn(fd, cmd, *a):
        if cmd == B.fcntl.F_DUPFD_CLOEXEC:
            tick()
        return real_fcntl(fd, cmd, *a)
    B.fcntl.fcntl = fn
elif where == "created":
    RealCreated = B._Created

    def ctor(*a):
        tick()
        return RealCreated(*a)
    B._Created = ctor
elif where == "pending":
    reg._pending = FailList()
elif where == "grant":
    RealGrant = B.Grant

    def gctor(*a):
        tick()
        return RealGrant(*a)
    B.Grant = gctor
elif where == "grants":
    reg._grants = FailDict()
elif where == "issued":
    reg._issued = FailSet()
elif where == "owned":
    reg._owned = FailSet()
elif where != "none":
    raise SystemExit("ponto desconhecido")
os.close = close_wrap


def call():
    return reg.make_pipe() if factory == "pipe" else reg.place_devnull(target)


out = {}
try:
    call()
    out["exc"] = "NO_ERROR"
except B.BootRefused as e:
    out["exc"] = "BootRefused:" + e.code
except Exception as e:
    out["exc"] = type(e).__name__
out["state"] = {"grants": len(reg._grants), "issued": len(reg._issued),
                "pending": len(reg._pending), "owned": len(reg._owned)}
os.close = real_close
B.fcntl.fcntl = real_fcntl
after = openset()
out.update(before=sorted(before), after=sorted(after), closed_log=list(closed_log),
           interposed=list(interposed), interposed_open=sorted(set(interposed) & after))
# o registro continua utilizável: sem a falha, a mesma fábrica funciona
if where in ("grant", "created"):
    B.Grant, B._Created = RealGrant if where == "grant" else B.Grant, \
        RealCreated if where == "created" else B._Created
else:
    reg._pending = list(reg._pending)
    reg._grants = dict(reg._grants)
    reg._issued = set(reg._issued)
    reg._owned = set(reg._owned)
out["retry_state_before"] = {"grants": len(reg._grants), "owned": len(reg._owned)}
try:
    call()
    out["retry"] = "ok"
except Exception as e:
    out["retry"] = type(e).__name__
out["retry_state"] = {"grants": len(reg._grants), "issued": len(reg._issued),
                      "pending": len(reg._pending), "owned": len(reg._owned)}
report = B.diagnose(reg)
out["authorized"] = [(e["fd"], e["reason"]) for e in report.get("entries", [])
                     if e["status"] == "authorized"]
closed_log.clear()
interposed.clear()
os.close = close_wrap
reg.close()
reg.close()
os.close = real_close
out["close_log"] = list(closed_log)
out["close_interposed_open"] = sorted(set(interposed) & openset())
out["close_interposed"] = sorted(set(interposed))
out["after_close"] = {"grants": len(reg._grants), "owned": len(reg._owned),
                      "pending": len(reg._pending), "closed": reg.closed}
with open(sys.argv[7], "w") as f:
    json.dump(out, f)
"""


def run_fault(factory, where, nth=1, slot="open", interpose=False):
    """Roda uma injeção de falha num filho descartável; devolve o JSON do filho."""
    with tempfile.TemporaryDirectory(prefix="gh-f1-18-fault-") as tmp:
        result = os.path.join(tmp, "result.json")
        proc = subprocess.run(
            [sys.executable, "-I", "-c", CHILD_FAULT, HERE, factory, where, str(nth), slot,
             "1" if interpose else "0", result],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=60, close_fds=True, env={})
        if proc.returncode != 0 or not os.path.exists(result):
            raise AssertionError("filho falhou (evidência insuficiente): rc=%s" % proc.returncode)
        with open(result) as f:
            return json.load(f)


def inherited_file():
    return tempfile.TemporaryFile()


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
    purpose = {"chr_devnull": "stdio_devnull"}.get(kind, "x")
    if kind == "fifo":
        purpose = "supervisor_pipe_read" if flags & os.O_ACCMODE == 0 \
            else "supervisor_pipe_write"
    return B.Grant(fd, kind, dev, ino, flags, inheritable, purpose,
                   100 + fd if anchor is None else anchor)


def synthetic_registry(*grants):
    """SOMENTE TESTES: escreve no estado privado, como código no mesmo processo
    sempre poderia. Não existe API de produção equivalente."""
    registry = B.CapabilityRegistry()
    for g in grants:
        registry._grants[g.fd] = g
        registry._issued.add(id(g))
    return registry


def std_inventory():
    return inventory(entry(0), entry(1), entry(2))


def std_registry():
    return synthetic_registry(grant(0), grant(1), grant(2))


def ev(inv, reg, same=lambda a, b: True, provenance="caller_supplied_unverified"):
    return B._evaluate(inv, reg, same, provenance)


class PureLogicTests(unittest.TestCase):
    def refused(self, code, inv, reg=None, same=lambda a, b: True):
        with self.assertRaises(B.BootRefused) as caught:
            B._evaluate(inv, reg or std_registry(), same, 'caller_supplied_unverified')
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
                              entry(7, "regular", 1, 2, True, 0, "<redacted-path>", access="rdonly")),
                    std_registry())
        self.assertEqual(report["unknown_fds"], [7])
        for kind in ("socket", "regular", "directory", "tty", "fifo"):
            report = ev(inventory(entry(0, kind, 9, 9, target="<redacted-path>"),
                                  entry(1), entry(2)), std_registry())
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
        reg = synthetic_registry(grant(5, "fifo", 7, 8, flags=0, inheritable=False),
                                 grant(6, "fifo", 7, 8, flags=1, inheritable=False))
        good = [entry(5, "fifo", 7, 8, True, 0, "pipe:[1]", access="rdonly"),
                entry(6, "fifo", 7, 8, True, 1, "pipe:[1]", access="wronly")]
        base = [entry(0), entry(1), entry(2)]
        self.assertEqual(ev(inventory(*base, *good), synthetic_registry(
            grant(0), grant(1), grant(2), *reg.grants.values()))["unknown_fds"], [])
        swapped = [dict(good[1], fd=5), dict(good[0], fd=6)]  # extremos trocados
        report = ev(inventory(*base, *swapped), synthetic_registry(
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
        reg = synthetic_registry(grant(0, anchor=10), grant(1, anchor=11), grant(2, anchor=12))
        anchors = [entry(10, cloexec=True), entry(11, cloexec=True), entry(12, cloexec=True)]
        report = ev(inventory(entry(0), entry(1), entry(2), *anchors), reg)
        self.assertEqual(report["verdict"], "CLEAN_FOR_GRANTS")
        self.assertEqual(report["entries"][3]["reason"], "registry_anchor")
        bad = [entry(10, cloexec=False), *anchors[1:]]       # âncora herdável
        report = ev(inventory(entry(0), entry(1), entry(2), *bad), reg)
        self.assertEqual(report["unknown_fds"], [10])
        bad = [entry(10, "regular", 1, 1, True, target="<redacted-path>"), *anchors[1:]]  # âncora trocada
        self.assertEqual(ev(inventory(entry(0), entry(1), entry(2), *bad), reg)["unknown_fds"], [10])

    def test_closed_stdio_and_vanished_grant_are_not_clean(self):
        report = ev(inventory(entry(0), entry(1)), std_registry())
        self.assertEqual(report["std_closed"], [2])
        self.assertEqual(report["grants_missing"], [2])
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")

    def test_cloexec_unknown_is_still_reported(self):
        report = ev(inventory(entry(0), entry(1), entry(2),
                              entry(5, "regular", 1, 2, True, 0, "<redacted-path>", access="rdonly")),
                    std_registry())
        self.assertTrue(report["entries"][3]["cloexec"])
        self.assertEqual(report["entries"][3]["status"], "unknown")

    def test_inconsistent_and_malformed_inventories_are_refused(self):
        ev(std_inventory(), std_registry())  # controle positivo
        cases = {
            "inventory_inconsistent": [{"structurally_consistent": False},
                                       {"probe_agrees": False},
                                       {"probe_agrees": False, "transient": 2}],
            "inventory_malformed": [
                {"entries": None}, {"transient": "1"}, {"transient": -1},
                {"probe_range": None}, {"probe_range": True}, {"probe_range": 2},
                {"probe_range": 0}, {"probe_range": (1 << 20) + 1},
                {"probe_agrees": 1}, {"entries": [entry(0), entry(0)]},
                {"entries": [entry(1), entry(0)]},                      # fora de ordem
                {"entries": [entry(0), {**entry(1), "fd": True}]},
                {"entries": [entry(0), {**entry(1), "fd": -1}]},
                {"entries": [entry(0), {**entry(1), "ino": -1}]},
                {"entries": [entry(0), {**entry(1), "kind": "wormhole"}]},
                {"entries": [entry(0), {**entry(1), "cloexec": 1}]},
                {"entries": [entry(0), {k: v for k, v in entry(1).items() if k != "ino"}]},
                {"entries": [entry(0), {**entry(1), "extra": 1}]},
                {"entries": ["fd=1"]}, {"surprise": 1}],
            "inventory_contradictory": [
                # sucesso estrutural declarado sem a sentinela que o sustenta
                {"sentinel_verified": False},
                # probe_agrees implica exatamente um transitório
                {"transient": 0}, {"transient": 2},
                # campos derivados contradizem os flags brutos
                {"entries": [entry(0), {**entry(1), "access": "rdonly"}, entry(2)]},
                {"entries": [entry(0), {**entry(1), "flags": 0}, entry(2)]},
                {"entries": [entry(0), {**entry(1), "opath": True}, entry(2)]},
                {"entries": [entry(0), {**entry(1), "flags": 2 | os.O_PATH}, entry(2)]},
                # FD fora do intervalo efetivamente sondado
                {"probe_range": 4, "entries": [entry(0), entry(1), entry(2), entry(4)]},
                {"probe_range": 1024, "entries": [entry(0), entry(1), entry(2), entry(1024)]}],
        }
        for code, mutations in cases.items():
            for mutation in mutations:
                self.refused(code, {**std_inventory(), **mutation})
        # fronteira válida: último FD logo abaixo do limite sondado
        ev(inventory(entry(0), entry(1), entry(2), entry(1023)), std_registry())
        legacy = std_inventory()
        legacy["complete"] = True
        del legacy["probe_agrees"]
        self.refused("inventory_malformed", legacy)
        for junk in (None, [], "x", {}):
            self.refused("inventory_malformed", junk)

    def test_caller_supplied_targets_are_refused_unless_in_the_closed_format(self):
        def with_target(target, kind="fifo"):
            return inventory(entry(0), entry(1), entry(2),
                             entry(7, kind, 1, 2, True, 0, target, access="rdonly"))
        reg = std_registry()
        # controles positivos: alvos legítimos, cada um com o kind coerente
        for kind, good in (("fifo", "pipe:[12345]"), ("socket", "socket:[9]"),
                           ("anon_inode", "anon_inode:[eventpoll]"),
                           ("anon_inode", "anon_inode:inotify"),
                           ("chr_devnull", "/dev/null"), ("tty", "<tty>"),
                           ("fifo", "<redacted-path>"), ("regular", "<redacted-path>")):
            report = ev(with_target(good, kind), reg)
            self.assertEqual(report["entries"][3]["target"], good)
            self.assertEqual(report["inventory_provenance"], "caller_supplied_unverified")
        # negativos: nada fornecido pelo chamador é reproduzido no relatório
        personal = "/home/fictional-user/Documents/segredo.txt"
        for bad in ("/private/path", "pipe:/private/path", "socket:/private/path",
                    "anon_inode:/private/path", personal, "pipe:" + personal,
                    "pipe:[1]/x", "pipe:[abc]", "pipe:[]", "pipe:[" + "9" * 30 + "]",
                    "pipe:[1]\n", "pipe:[1]\x00", "anon_inode:[a/b]",
                    "anon_inode:" + "x" * 40, "<tty>/x", " /dev/null", "/dev/nullx", "",
                    "anon_inode:[eventpoll", "anon_inode:eventpoll]", "anon_inode:[]"):
            with self.assertRaises(B.BootRefused, msg=bad) as caught:
                ev(with_target(bad), reg)
            self.assertEqual(caught.exception.code, "inventory_target_invalid")
            self.assertEqual(B._diagnose(reg, lambda bad=bad: with_target(bad))["reason"],
                             "inventory_target_invalid")
        for wrong_type in (None, 7, b"/dev/null", ["/dev/null"]):
            self.refused("inventory_malformed", with_target(wrong_type))
        # o texto recusado nunca aparece no relatório de recusa
        refused = B._diagnose(reg, lambda: with_target("pipe:" + personal))
        self.assertNotIn("fictional-user", json.dumps(refused))

    def test_real_target_sanitizer_only_returns_the_closed_format(self):
        for raw, kind, expected in (
                ("/dev/null", "chr_devnull", "/dev/null"), ("pipe:[7]", "fifo", "pipe:[7]"),
                ("anon_inode:[eventpoll]", "anon_inode", "anon_inode:[eventpoll]"),
                ("/dev/pts/3", "tty", "<tty>"), ("/home/x/file", "regular", "<redacted-path>"),
                ("pipe:/home/x", "fifo", "<redacted-path>"),
                ("anon_inode:" + "y" * 50, "anon_inode", "<redacted-path>"),
                # formato válido de OUTRO kind nunca é reproduzido
                ("pipe:[7]", "regular", "<redacted-path>"),
                ("/dev/null", "regular", "<redacted-path>"),
                ("/dev/pts/3", "chr_other", "<redacted-path>"),
                ("anon_inode:[eventpoll", "anon_inode", "<redacted-path>")):
            safe = B._safe_target(raw, kind)
            self.assertEqual(safe, expected)
            self.assertEqual(B._target_state(kind, safe), "ok")

    def test_validated_inventory_still_has_no_provenance(self):
        report = B.evaluate(std_inventory(), std_registry())
        self.assertEqual(report["inventory_provenance"], "caller_supplied_unverified")
        self.assertIs(report["inventory_effectively_complete"], False)
        self.assertIs(report["unobserved_capabilities_excluded"], False)
        self.assertTrue(any("proveniência" in text for text in report["limitations"]))
        self.assertEqual(B._diagnose(std_registry(), lambda: std_inventory())[
            "inventory_provenance"], "caller_supplied_unverified")
        self.assertEqual(B._report("REFUSED", reason="inventory_malformed")["inventory_provenance"], "none")

    def test_no_declaration_api_exists_in_production(self):
        for name in ("_MINT", "_mint_grant", "_registry_with", "_record"):
            self.assertFalse(hasattr(B, name), name)
            self.assertFalse(hasattr(B.CapabilityRegistry, name), name)
        reg = B.CapabilityRegistry()
        hand_built = B.Grant(0, "chr_devnull", 5, 6, 2, True, "x", 9)
        for bad in (0, 1, 2, 7, None, "0", (1, "x"), hand_built):
            with self.assertRaises(B.BootRefused, msg=repr(bad)) as caught:
                reg._issue(bad)
            self.assertEqual(caught.exception.code, "declaration_refused")
        # um recibo montado à mão não está entre os criados pelas fábricas
        forged = B._Created(0, 3, entry(0), "forged", True)
        with self.assertRaises(B.BootRefused) as caught:
            reg._issue(forged)
        self.assertEqual(caught.exception.code, "declaration_refused")
        self.assertEqual(dict(reg.grants), {})

    def test_hand_built_grants_are_only_trusted_if_this_registry_issued_them(self):
        ev(std_inventory(), std_registry())  # controle positivo
        injected = B.CapabilityRegistry()
        injected._grants[0] = grant(0)     # sem passar por _issue (fora da garantia)
        self.refused("invalid_grant", std_inventory(), injected)

    def test_closed_registry_invalidates_its_grants_and_close_is_idempotent(self):
        reg = std_registry()
        ev(std_inventory(), reg)
        reg.close()
        reg.close()
        self.assertTrue(reg.closed)
        self.assertEqual(dict(reg.grants), {})
        self.refused("registry_closed", std_inventory(), reg)
        for call in (lambda: reg.place_devnull(0), reg.make_pipe):
            with self.assertRaises(B.BootRefused) as caught:
                call()
            self.assertEqual(caught.exception.code, "registry_closed")

    def test_registry_context_manager_closes(self):
        with B.CapabilityRegistry() as reg:
            self.assertFalse(reg.closed)
        self.assertTrue(reg.closed)

    def test_registry_cannot_be_forged_through_public_surface(self):
        reg = B.CapabilityRegistry()
        with self.assertRaises(TypeError):
            reg.grants[9] = object()
        with self.assertRaises(AttributeError):
            reg.grants = {}
        with self.assertRaises(AttributeError):
            reg.other = 1

        class Sub(B.CapabilityRegistry):
            pass
        self.refused("invalid_registry", std_inventory(), Sub())
        self.refused("invalid_registry", std_inventory(), {"grants": {}})
        # Mesmo adulterando o dict PRIVADO (fora da garantia), o conteúdo é validado:
        tampered = std_registry()
        tampered._grants[0] = ("0", "chr_devnull")
        self.refused("invalid_grant", std_inventory(), tampered)
        wild = synthetic_registry(B.Grant(9, "kernel_gift", 1, 1, 0, False, "x", 99))
        self.refused("unexpected_capability_kind", std_inventory(), wild)
        collide = synthetic_registry(grant(0, anchor=1), grant(1, anchor=1))
        self.refused("invalid_grant", std_inventory(), collide)

    def test_place_devnull_rejects_targets_outside_stdio_before_touching_fds(self):
        for bad in (3, -1, 99, "1", None, True.__class__):
            with self.assertRaises(B.BootRefused) as caught:
                B.CapabilityRegistry().place_devnull(bad)
            self.assertEqual(caught.exception.code, "invalid_target")

    def test_reserved_report_fields_cannot_be_overridden(self):
        base = B._report("REFUSED", reason="inventory_malformed")
        self.assertEqual(base["verdict"], "REFUSED")
        for field, value in (("strong", "STRONG"), ("readiness", "READY"),
                             ("agent_execution_authorized", True),
                             ("file_operations_authorized", True),
                             ("cloud_call_authorized", True),
                             ("data_transfer_authorized", True),
                             ("bootstrap_trusted", True), ("bootstrap_complete", True),
                             ("verdict", "CLEAN_FOR_GRANTS"), ("schema", "x"),
                             ("inventory_effectively_complete", True),
                             ("unobserved_capabilities_excluded", True),
                             ("inventory_provenance", "collected_in_process"),
                             ("limitations", [])):
            with self.assertRaises(ValueError, msg=field) as caught:
                B._report("REFUSED", **{field: value})
            self.assertEqual(str(caught.exception), "reserved_field")
        with self.assertRaises(ValueError):
            B._report("TRUSTED")
        with self.assertRaises(ValueError):          # proveniência inventada
            B._report("REFUSED", provenance="trusted_by_owner", reason="inventory_malformed")

    def test_invariants_are_read_only_and_reports_are_independent_copies(self):
        with self.assertRaises(TypeError):
            T.INVARIANTS["strong"] = "STRONG"
        self.assertIs(B.INVARIANTS, T.INVARIANTS)
        report = B._report("REFUSED", reason="inventory_malformed")
        report["strong"] = "STRONG"            # alterar a cópia não toca a constante
        self.assertEqual(T.INVARIANTS["strong"], "UNAVAILABLE")
        self.assertEqual(B._report("REFUSED", reason="inventory_malformed")["strong"], "UNAVAILABLE")

    def test_check_report_rejects_tampered_or_mistyped_invariants(self):
        good = B._report("REFUSED", reason="inventory_malformed")
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

    def test_check_boot_report_rejects_contradictory_or_tampered_reports(self):
        clean = ev(std_inventory(), std_registry())
        unknown = ev(inventory(entry(0), entry(1), entry(2), entry(7, "regular", 1, 2, True, 0,
                                                                     "<redacted-path>",
                                                                     access="rdonly")),
                     std_registry())
        refused = B._report("REFUSED", reason="inventory_malformed")
        for good in (clean, unknown, refused):
            B.check_boot_report(good)

        def tampered(report, **changes):
            bad = dict(report)
            bad.update(changes)
            with self.assertRaises(ValueError, msg=changes):
                B.check_boot_report(bad)
        # 1. campos reservados/novos de completude alterados
        for key in ("inventory_effectively_complete", "unobserved_capabilities_excluded",
                    "bootstrap_trusted", "bootstrap_complete", "agent_execution_authorized"):
            for value in (True, 1, 0, "false", None):
                tampered(clean, **{key: value})
        # 2. booleanos com tipo errado
        for value in (1, 0, "true", None):
            tampered(clean, inventory_structurally_consistent=value)
            tampered(clean, close_range_used=value)
        # 3. campo obrigatório ausente
        for key in ("strong", "readiness", "verdict", "schema", "bootstrap_trusted",
                    "inventory_effectively_complete", "unobserved_capabilities_excluded",
                    "inventory_provenance", "inventory_structurally_consistent"):
            missing = dict(clean)
            del missing[key]
            with self.assertRaises(ValueError, msg=key):
                B.check_boot_report(missing)
        # 4. veredito incompatível com a observação
        tampered(clean, verdict="UNKNOWN_CAPABILITIES")        # nada desconhecido
        tampered(unknown, verdict="CLEAN_FOR_GRANTS")           # há desconhecido
        tampered(clean, verdict="REFUSED")                      # tem entries/consistente
        tampered(refused, verdict="CLEAN_FOR_GRANTS")
        tampered(refused, inventory_structurally_consistent=True)
        tampered(clean, inventory_structurally_consistent=False)
        tampered(clean, unknown_fds=[0])                        # lista vs entries
        tampered(unknown, unknown_fds=[])
        tampered(clean, verdict="TRUSTED")
        tampered(clean, inventory_provenance="trusted_by_owner")
        tampered(refused, reason=None)
        tampered(refused, entries=[])
        # 5. estrutura malformada
        for junk in (None, [], "x", {}):
            with self.assertRaises(ValueError):
                B.check_boot_report(junk)
        tampered(clean, entries="all-good")

    def test_fabricated_boot_reports_are_refused_field_by_field(self):
        """P2-02: cada campo crítico é adulterado sozinho (ausente, tipo errado,
        texto sensível, contradição). O relatório de partida é aceito."""
        clean = ev(std_inventory(), std_registry())
        unknown = ev(inventory(entry(0), entry(1), entry(2),
                               entry(7, "regular", 1, 2, True, 0, "<redacted-path>",
                                     access="rdonly")), std_registry())
        closed = ev(inventory(entry(0), entry(1)), std_registry())   # std_closed/missing
        refused = B._report("REFUSED", reason="inventory_malformed")
        for good in (clean, unknown, closed, refused):
            B.check_boot_report(good)

        def tampered(report, msg, **changes):
            bad = {**report, **changes}
            with self.assertRaises(ValueError, msg=msg):
                B.check_boot_report(bad)

        def with_entry(report, index, **changes):
            entries = [dict(e) for e in report["entries"]]
            entries[index].update(changes)
            return entries
        # 1. o caso do relatório de auditoria
        tampered(clean, "fabricado", entries=[{"fd": "not-an-int", "status": "authorized",
                                               "target": "/private/path"}],
                 inventory_provenance="none")
        # 2. campos de entrada: tipo errado, ausente, texto sensível
        wrong = {"fd": ("0", None, True, -1, 1.5, [0]), "kind": ("wormhole", None, 3),
                 "dev": ("1", None, True, -1), "ino": ("1", None, True, -1),
                 "flags": ("2", None, True, -1), "cloexec": (1, 0, "false", None),
                 "opath": (1, 0, "false", None), "access": ("write", None, 2),
                 "target": ("/private/path", "pipe:/x", None, 7, "/dev/null\n"),
                 "status": ("trusted", None, 1, True), "reason": ("x", None, 5, "/private"),
                 "mismatch": ("identity", None, 1, ["bogus"], [7], ["opath", "identity"],
                              ["identity", "identity"])}
        for key, values in wrong.items():
            for value in values:
                tampered(clean, (key, value), entries=with_entry(clean, 0, **{key: value}))
        for key in clean["entries"][0]:
            entries = [dict(e) for e in clean["entries"]]
            del entries[0][key]
            tampered(clean, ("missing", key), entries=entries)
        tampered(clean, "extra", entries=with_entry(clean, 0, secret="/home/fictional-user/x"))
        tampered(clean, "entry nao dict", entries=["fd=0"])
        tampered(clean, "entries nao lista", entries="ok")
        # 3. coerência dentro da entrada
        tampered(clean, "kind/target", entries=with_entry(clean, 0, kind="regular"))
        tampered(clean, "access/flags", entries=with_entry(clean, 0, access="rdonly"))
        tampered(clean, "autorizada com mismatch", entries=with_entry(clean, 0, mismatch=["ofd"]))
        tampered(clean, "autorizada por razão desconhecida",
                 entries=with_entry(clean, 0, reason="made_up"))
        tampered(clean, "stdio_devnull fora de 0..2", entries=with_entry(clean, 0, fd=9))
        tampered(clean, "razão de pipe em devnull",
                 entries=with_entry(clean, 0, reason="supervisor_pipe_read"))
        tampered(clean, "autorizada sem direito", entries=with_entry(clean, 0, cloexec=True))
        tampered(unknown, "grant_mismatch sem diferença",
                 entries=with_entry(unknown, 3, reason="grant_mismatch"))
        tampered(unknown, "no_grant com diferença", entries=with_entry(unknown, 3, mismatch=["identity"]))
        tampered(unknown, "anchor_mismatch errado",
                 entries=with_entry(unknown, 3, reason="anchor_mismatch", mismatch=["ofd"]))
        tampered(unknown, "razão de autorizado em unknown",
                 entries=with_entry(unknown, 3, reason="stdio_devnull"))
        tampered(unknown, "unknown virou authorized",
                 entries=with_entry(unknown, 3, status="authorized"))
        tampered(clean, "entradas fora de ordem", entries=list(reversed(clean["entries"])))
        tampered(clean, "entradas duplicadas", entries=clean["entries"] + clean["entries"][:1])
        # 4. listas: tipo, ordem, unicidade e relação com as entradas
        for key in ("unknown_fds", "std_closed", "grants_missing"):
            for value in (None, "0", (0,), [True], [-1], ["0"], [1, 0], [0, 0], [1.5]):
                tampered(clean, (key, value), **{key: value})
        tampered(clean, "unknown_fds vs entries", unknown_fds=[0])
        tampered(unknown, "unknown_fds vazia", unknown_fds=[])
        tampered(unknown, "unknown_fds errada", unknown_fds=[3])
        tampered(clean, "std_closed aberto", std_closed=[0], verdict="UNKNOWN_CAPABILITIES")
        tampered(closed, "std_closed vazia", std_closed=[])
        tampered(closed, "std_closed extra", std_closed=[1, 2])
        tampered(closed, "missing em fd presente", grants_missing=[0, 2])
        # 5. veredito x observação
        tampered(clean, "veredito", verdict="UNKNOWN_CAPABILITIES")
        tampered(unknown, "veredito", verdict="CLEAN_FOR_GRANTS")
        tampered(closed, "veredito", verdict="CLEAN_FOR_GRANTS")
        tampered(clean, "REFUSED com listas", verdict="REFUSED", reason="inventory_malformed")
        # 6. proveniência
        for value in ("none", "trusted_by_owner", None, 1, ["none"], ""):
            tampered(clean, ("provenance", value), inventory_provenance=value)
        tampered(unknown, "provenance none", inventory_provenance="none")
        for value in ("collected_in_process", "caller_supplied_unverified", "trusted", None):
            tampered(refused, ("refused provenance", value), inventory_provenance=value)
        # 7. REFUSED: motivo de conjunto fixo, sem listas
        for value in ("x", "/private/path", "", None, 7, ["inventory_malformed"],
                      "inventory_malformed\n", "place_devnull_failed"):
            tampered(refused, ("reason", value), reason=value)
        for key in ("entries", "unknown_fds", "std_closed", "grants_missing"):
            tampered(refused, ("refused+" + key), **{key: []})
        del_reason = dict(refused)
        del del_reason["reason"]
        with self.assertRaises(ValueError):
            B.check_boot_report(del_reason)
        tampered(clean, "CLEAN com reason", reason="inventory_malformed")
        # 8. nível superior: schema, textos fixos, chaves exatas
        for value in ("wrong", None, 3, "supervisor-boot-diagnostic/2"):
            tampered(clean, ("schema", value), schema=value)
        tampered(clean, "inventory_source", inventory_source="/private/path")
        tampered(clean, "limitations", limitations=[])
        tampered(clean, "limitations", limitations=["/private/path"])
        tampered(clean, "not_verified", not_verified=None)
        tampered(clean, "extra no topo", surprise="/home/fictional-user")
        tampered(clean, "close_range", close_range_used=True)
        tampered(clean, "verdict tipo", verdict=["CLEAN_FOR_GRANTS"])
        # 9. a validação é de forma/coerência: um relatório forjado e coerente passa
        forged = {**clean, "inventory_provenance": "collected_in_process"}
        B.check_boot_report(forged)
        self.assertTrue(any("autenticidade" in text for text in clean["limitations"]))

    def test_kind_and_target_must_agree(self):
        """P3-01: o formato do alvo precisa ser o do kind (ou o genérico)."""
        def one(kind, target):
            return inventory(entry(0), entry(1), entry(2),
                             entry(7, kind, 1, 2, True, 0, target, access="rdonly"))
        reg = std_registry()
        coherent = [("fifo", "pipe:[1]"), ("socket", "socket:[1]"),
                    ("chr_devnull", "/dev/null"), ("tty", "<tty>"),
                    ("anon_inode", "anon_inode:[eventpoll]"), ("anon_inode", "anon_inode:inotify")]
        for kind, target in coherent:
            ev(one(kind, target), reg)
        for kind in B.KINDS:
            ev(one(kind, "<redacted-path>"), reg)             # genérico serve a todos
        # formato válido, kind errado
        for kind, target in (("regular", "pipe:[1]"), ("socket", "pipe:[1]"),
                             ("fifo", "socket:[1]"), ("directory", "/dev/null"),
                             ("regular", "<tty>"), ("tty", "/dev/null"),
                             ("chr_devnull", "anon_inode:[x]"), ("other", "socket:[2]")):
            with self.assertRaises(B.BootRefused, msg=(kind, target)) as caught:
                ev(one(kind, target), reg)
            self.assertEqual(caught.exception.code, "inventory_contradictory")
        # formato inválido (colchetes soltos, vazio, caminhos)
        for kind, target in (("anon_inode", "anon_inode:[eventpoll"),
                             ("anon_inode", "anon_inode:eventpoll]"),
                             ("anon_inode", "anon_inode:[]"), ("fifo", "pipe:[1"),
                             ("regular", "/etc/passwd")):
            with self.assertRaises(B.BootRefused, msg=(kind, target)) as caught:
                ev(one(kind, target), reg)
            self.assertEqual(caught.exception.code, "inventory_target_invalid")
        # o mesmo vale na validação do relatório já classificado
        report = ev(one("fifo", "pipe:[1]"), reg)
        B.check_boot_report(report)
        bad = [dict(e) for e in report["entries"]]
        bad[3]["kind"] = "regular"
        with self.assertRaises(ValueError):
            B.check_boot_report({**report, "entries": bad})
        bad[3].update(kind="anon_inode", target="anon_inode:[eventpoll")
        with self.assertRaises(ValueError):
            B.check_boot_report({**report, "entries": bad})
        # o coletor real nunca produz alvo incoerente com o kind que ele mesmo escolheu
        for target, kind in (("pipe:[3]", "fifo"), ("/home/u/x", "regular"),
                             ("/dev/null", "regular"), ("anon_inode:[eventfd]", "regular")):
            safe = B._safe_target(target, kind)
            self.assertEqual(B._target_state(kind, safe), "ok")


    def test_report_builder_refuses_incoherent_results(self):
        # "CLEAN" com listas inconsistentes não pode ser construído pelas rotas internas
        with self.assertRaises(ValueError):
            B._report("CLEAN_FOR_GRANTS", entries=[], unknown_fds=[0], std_closed=[],
                      grants_missing=[])
        with self.assertRaises(ValueError):
            B._report("UNKNOWN_CAPABILITIES", entries=[], unknown_fds=[], std_closed=[],
                      grants_missing=[])
        with self.assertRaises(ValueError):
            B._report("REFUSED")                      # sem reason
        base = ev(std_inventory(), std_registry())     # controle positivo coerente
        B._report("CLEAN_FOR_GRANTS", provenance="collected_in_process",
                  entries=base["entries"], unknown_fds=[], std_closed=[],
                  grants_missing=[])

    def test_unexpected_diagnosis_failure_is_a_conservative_refusal(self):
        reg = std_registry()
        # saída do coletor com estrutura que passa a validação mas quebra a avaliação
        original = B._classify

        def explode(*args):
            raise RuntimeError("/secret/path unexpected")
        B._classify = explode
        try:
            report = B._diagnose(reg, lambda: std_inventory())
        finally:
            B._classify = original
        self.assertEqual((report["verdict"], report["reason"]),
                         ("REFUSED", "evidence_insufficient"))
        self.assertNotIn("secret", json.dumps(report))
        control = B._diagnose(reg, lambda: std_inventory())   # controle, sem a falha
        self.assertNotIn("reason", control)
        self.assertEqual(control["inventory_provenance"], "caller_supplied_unverified")

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

    def test_inherited_fds_cannot_be_registered_by_declaration(self):
        with tempfile.TemporaryFile() as inherited:
            result = run_child(["declare_int", "declare_forged", "eval"],
                               stdin=inherited, stdout=inherited, stderr=inherited)
        for fd in (0, 1, 2):
            self.assertEqual(result["notes"]["declare%d" % fd],
                             "BootRefused:declaration_refused")
        self.assertEqual(result["notes"]["declare_forged"], "BootRefused:declaration_refused")
        report = result["stages"][-1]
        # nada foi concedido: os três slots herdados seguem desconhecidos
        self.assertEqual(report["unknown_fds"], [0, 1, 2])
        self.assertTrue(all(e["reason"] == "no_grant" for e in report["entries"]))
        # controle positivo: a fábrica, que CRIA o FD, é reconhecida
        with contextlib.ExitStack() as stack:    # fecha os três arquivos temporários
            control = run_child([*CLEAN_STD, "eval"],
                                stdin=stack.enter_context(inherited_file()),
                                stdout=stack.enter_context(inherited_file()),
                                stderr=stack.enter_context(inherited_file()))
        self.assertEqual(control["stages"][-1]["verdict"], "CLEAN_FOR_GRANTS")

    def test_registry_lifecycle_releases_anchors_and_invalidates_grants(self):
        result = run_child([*CLEAN_STD, "pipe", "eval", "mark_base", "shutdown_registry",
                            "diff:closed", "eval"])
        self.assertEqual(result["stages"][0]["verdict"], "CLEAN_FOR_GRANTS")   # controle
        # as 5 âncoras (3 slots + 2 pipes) foram liberadas; nenhum FD do chamador fechado
        self.assertEqual(len(result["notes"]["closed"]["removed"]), 5)
        self.assertEqual(result["notes"]["closed"]["added"], [])
        self.assertEqual(result["notes"]["grants_after_close"], 0)
        self.assertEqual(result["notes"]["place_after_close"], "BootRefused:registry_closed")
        self.assertEqual(result["notes"]["pipe_after_close"], "BootRefused:registry_closed")
        final_report = result["stages"][-1]
        self.assertEqual((final_report["verdict"], final_report["reason"]),
                         ("REFUSED", "registry_closed"))

    def test_fd_number_reused_after_close_is_not_the_granted_object(self):
        result = run_child([*CLEAN_STD, "pipe", "eval", "reuse_closed_pipe_read", "eval"])
        r = result["pipes"][0][0]
        self.assertEqual(result["stages"][0]["verdict"], "CLEAN_FOR_GRANTS")    # controle
        report = result["stages"][-1]
        self.assertEqual(report["unknown_fds"], [r])
        mismatch = mismatch_of(report, r)
        self.assertLessEqual({"identity", "ofd"}, mismatch)    # outro objeto, outra OFD

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
            "new_attribute": "AttributeError",
            "grant_by_declaration": "BootRefused:declaration_refused",
            "grants_pop": "AttributeError"})
        self.assertEqual(result["stages"][-1]["verdict"], "CLEAN_FOR_GRANTS")

    def test_real_collection_of_kernel_objects_keeps_kind_and_target_coherent(self):
        result = run_child([*CLEAN_STD, "kernel_objects", "eval"])
        report = result["stages"][-1]
        self.assertNotIn("reason", report)                    # não foi recusado
        B.check_boot_report(report)                           # coerente de ponta a ponta
        kinds = {e["kind"] for e in report["entries"]}
        self.assertLessEqual({"anon_inode", "socket", "fifo"}, kinds)
        for e in report["entries"]:
            self.assertEqual(B._target_state(e["kind"], e["target"]), "ok", e)
        self.assertTrue(all(e["status"] == "unknown" for e in report["entries"]
                            if e["kind"] in ("anon_inode", "socket")))

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

    def test_failure_after_replacing_a_std_slot_leaves_no_grant_and_no_leak(self):
        with tempfile.TemporaryFile() as inherited:
            control = run_child(["mark_base", "devnull1", "diff:ok", "eval"], stdout=inherited)
            self.assertEqual(control["notes"]["place1"], "ok")                  # controle
            self.assertEqual(len(control["notes"]["ok"]["added"]), 1)           # só a âncora
            # (a) slot ocupado por objeto herdado: dup2 já ocorreu quando a âncora falha
            result = run_child(["mark_base", "fail_anchor", "devnull1", "restore_fcntl",
                                "diff:fail", "eval"], stdout=inherited)
        self.assertEqual(result["notes"]["place1"], "place_devnull_failed")
        self.assertEqual(result["notes"]["fail"], {"added": [], "removed": []})  # sem vazamento
        entry1 = next(e for e in result["stages"][-1]["entries"] if e["fd"] == 1)
        # a autoridade herdada foi descartada; o slot é /dev/null herdável SEM grant
        self.assertEqual((entry1["kind"], entry1["cloexec"], entry1["status"], entry1["reason"]),
                         ("chr_devnull", False, "unknown", "no_grant"))
        # (b) slot fechado cujo número é reutilizado: volta a ficar fechado
        closed = run_child(["close1", "mark_base", "fail_anchor", "devnull1", "restore_fcntl",
                            "diff:fail", "devnull0", "devnull2", "eval"])
        self.assertEqual(closed["notes"]["place1"], "place_devnull_failed")
        self.assertEqual(closed["notes"]["fail"], {"added": [], "removed": []})
        self.assertEqual(closed["stages"][-1]["std_closed"], [1])

    def test_make_pipe_is_all_or_nothing(self):
        control = run_child([*CLEAN_STD, "mark_base", "pipe", "diff:ok", "eval"])
        self.assertNotIn("pipe", control["notes"])                              # controle
        self.assertEqual(len(control["notes"]["ok"]["added"]), 4)               # 2 FDs + 2 âncoras
        for step in ("fail_anchor", "fail_anchor_second"):
            result = run_child([*CLEAN_STD, "mark_base", step, "pipe", "restore_fcntl",
                                "diff:fail", "eval"])
            self.assertEqual(result["notes"]["pipe"], "make_pipe_failed", step)
            self.assertEqual(result["notes"]["fail"], {"added": [], "removed": []}, step)
            self.assertEqual(result["stages"][-1]["verdict"], "CLEAN_FOR_GRANTS", step)

    def test_kcmp_unavailable_makes_every_grant_unknown_never_authorized(self):
        control = final(CLEAN_STD)
        self.assertEqual(control["verdict"], "CLEAN_FOR_GRANTS")                # controle
        report = final([*CLEAN_STD, "kcmp_unavailable"])
        self.assertEqual(report["verdict"], "UNKNOWN_CAPABILITIES")
        for fd in (0, 1, 2):
            self.assertEqual(report["entries"][fd]["status"], "unknown")
            self.assertEqual(mismatch_of(report, fd), {"ofd_unverifiable"})
        self.assertFalse([e for e in report["entries"] if e["status"] == "authorized"
                          and e["reason"] != "registry_anchor"])

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


class ChildFaultTests(unittest.TestCase):
    """P2-01: falhas injetadas em CADA etapa das fábricas, num filho real, com o
    conjunto real de FDs abertos e o estado do registro verificados."""

    # pontos de falha que afetam make_pipe, com a n-ésima ocorrência
    PIPE_POINTS = [("anchor", 1), ("anchor", 2), ("created", 1), ("created", 2),
                   ("pending", 1), ("pending", 2), ("grant", 1), ("grant", 2),
                   ("grants", 1), ("grants", 2), ("issued", 1), ("issued", 2),
                   ("owned", 1), ("owned", 2)]
    PLACE_POINTS = [("anchor", 1), ("created", 1), ("pending", 1), ("grant", 1),
                    ("grants", 1), ("issued", 1), ("owned", 1)]

    def assert_clean_registry(self, out, label):
        self.assertEqual(out["state"], {"grants": 0, "issued": 0, "pending": 0, "owned": 0},
                         label)
        self.assertEqual(out["retry_state_before"], {"grants": 0, "owned": 0}, label)
        # nada concedido por engano: a falha não deixou capacidade autorizada
        # (a tentativa seguinte, sem falha, é o único dono dos grants)
        self.assertEqual(out["after_close"], {"grants": 0, "owned": 0, "pending": 0,
                                              "closed": True}, label)

    def test_positive_controls(self):
        for factory in ("pipe", "place"):
            out = run_fault(factory, "none")
            self.assertEqual(out["exc"], "NO_ERROR", factory)
            self.assertEqual(out["retry"], "ok", factory)
            grants = 2 if factory == "pipe" else 1
            self.assertEqual(out["state"], {"grants": grants, "issued": grants,
                                            "pending": 0, "owned": grants}, factory)
            self.assertEqual(len(out["after"]) - len(out["before"]), 2 * grants
                             if factory == "pipe" else 1, factory)   # FDs + âncoras
            self.assertEqual(out["after_close"], {"grants": 0, "owned": 0, "pending": 0,
                                                  "closed": True})

    def test_make_pipe_failure_at_every_step_is_all_or_nothing(self):
        for where, nth in self.PIPE_POINTS:
            label = "pipe/%s/%d" % (where, nth)
            out = run_fault("pipe", where, nth)
            self.assertEqual(out["exc"], "Boom", label)
            self.assertEqual(out["after"], out["before"], label)      # nenhum FD vazou
            self.assert_clean_registry(out, label)
            self.assertEqual(out["retry"], "ok", label)               # registro reutilizável
            self.assertEqual(out["retry_state"]["grants"], 2, label)
            self.assertEqual(out["retry_state"]["owned"], 2, label)
            self.assertEqual(out["retry_state"]["pending"], 0, label)

    def test_place_devnull_failure_at_every_step_leaves_nothing_behind(self):
        for slot in ("open", "closed"):
            for where, nth in self.PLACE_POINTS:
                label = "place/%s/%s/%d" % (slot, where, nth)
                out = run_fault("place", where, nth, slot=slot)
                self.assertEqual(out["exc"], "Boom", label)
                # slot aberto: continua aberto (residual documentado); fechado: volta a fechado
                self.assertEqual(out["after"], out["before"], label)
                self.assert_clean_registry(out, label)
                self.assertEqual(out["retry"], "ok", label)
                self.assertEqual(out["retry_state"], {"grants": 1, "issued": 1,
                                                      "pending": 0, "owned": 1}, label)

    def test_failure_after_first_issue_revokes_it_and_closes_each_anchor_once(self):
        for where in ("grant", "grants", "issued", "owned"):
            out = run_fault("pipe", where, 2)
            label = "second/" + where
            self.assertEqual(out["after"], out["before"], label)
            self.assertEqual(len(out["closed_log"]), len(set(out["closed_log"])), label)
            # âncora 1 (registrada), âncora 2, leitura e escrita: 4 closes, 4 números
            self.assertEqual(len(out["closed_log"]), 4, label)
            self.assert_clean_registry(out, label)

    def test_a_number_reused_between_two_closes_is_never_closed_again(self):
        # Um FD novo assume o número recém-liberado após CADA close. Se o código
        # fechasse um mesmo número duas vezes, fecharia o FD novo.
        for factory, points in (("pipe", self.PIPE_POINTS), ("place", self.PLACE_POINTS)):
            for where, nth in points:
                label = "interpose/%s/%s/%d" % (factory, where, nth)
                out = run_fault(factory, where, nth, interpose=True)
                self.assertEqual(len(out["closed_log"]), len(set(out["closed_log"])), label)
                # a interposição realmente ocorreu em cada close, e nada a fechou depois
                self.assertEqual(out["interposed"], out["closed_log"], label)
                self.assertEqual(out["interposed_open"], sorted(set(out["interposed"])), label)
                self.assertEqual(out["state"], {"grants": 0, "issued": 0, "pending": 0,
                                                "owned": 0}, label)

    def test_close_releases_each_anchor_once_and_is_idempotent(self):
        for factory, anchors in (("pipe", 4), ("place", 1)):   # a repetição reaproveita o slot
            out = run_fault(factory, "none", interpose=True)
            self.assertEqual(out["exc"], "NO_ERROR", factory)
            # duas chamadas a close(): cada âncora é fechada uma única vez e o FD novo
            # que assumiu o número liberado nunca é fechado
            self.assertEqual(len(out["close_log"]), anchors, factory)
            self.assertEqual(len(set(out["close_log"])), anchors, factory)
            self.assertEqual(out["close_interposed"], sorted(out["close_log"]), factory)
            self.assertEqual(out["close_interposed_open"], out["close_interposed"], factory)
            self.assertEqual(out["after_close"], {"grants": 0, "owned": 0, "pending": 0,
                                                  "closed": True}, factory)

    def test_closed_registry_is_refused_and_has_no_authorized_fd(self):
        result = run_child([*CLEAN_STD, "pipe", "eval", "shutdown_registry", "eval"])
        self.assertEqual(result["stages"][0]["verdict"], "CLEAN_FOR_GRANTS")      # controle
        final_report = result["stages"][-1]
        self.assertEqual((final_report["verdict"], final_report["reason"]),
                         ("REFUSED", "registry_closed"))
        self.assertEqual(result["notes"]["grants_after_close"], 0)


if __name__ == "__main__":
    unittest.main()
