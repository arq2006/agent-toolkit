#!/usr/bin/env python3
"""Protótipo GH-F1.18/PR-B: diagnóstico de descritores herdados do supervisor.

Inventaria /proc/self/fd (inclusive FDs 0, 1 e 2), distingue capacidades que
o PRÓPRIO supervisor criou e registrou das desconhecidas, e recusa inventário
incompleto ou malformado. close_range NÃO é usado: ele não faz inventário.

Somente diagnóstico. Nunca declara o bootstrap confiável ou completo, não
fecha nem altera descritores, não executa agentes. STRONG=UNAVAILABLE e
readiness=BLOCKED permanecem. Um registro de capacidade só nasce das fábricas
da classe CapabilityRegistry (FD criado aqui); descritor herdado nunca é
autorizado por simples declaração.
"""
import dataclasses
import errno
import fcntl
import os
import stat
import sys
import threading

from trusted_root import INVARIANTS

SCHEMA = "supervisor-boot-diagnostic/1"
KINDS = ("directory", "regular", "chr_devnull", "chr_other", "tty",
         "fifo", "socket", "anon_inode", "other")
_ENTRY_KEYS = frozenset(("fd", "kind", "dev", "ino", "cloexec", "flags",
                         "access", "opath", "target"))
_INVENTORY_KEYS = frozenset(("complete", "entries", "transient", "sentinel_verified"))
_DEVNULL_RDEV = os.makedev(1, 3) if hasattr(os, "makedev") else None
_O_PATH = getattr(os, "O_PATH", 0o10000000)
_ACCESS = {os.O_RDONLY: "rdonly", os.O_WRONLY: "wronly", os.O_RDWR: "rdwr"}
_VERDICTS = ("CLEAN_FOR_GRANTS", "UNKNOWN_CAPABILITIES", "REFUSED")

LIMITATIONS = (
    "diagnóstico de uma observação: descritores podem mudar depois dela",
    "exige processo monothread; threads criadas por terceiros invalidam o inventário",
    "/proc é assumido como procfs do próprio processo (verificação parcial por pid)",
    "identidade (kind, dev, ino) não distingue open file descriptions diferentes do mesmo objeto",
    "grants cobrem apenas FDs criados por este módulo; não autenticam origem externa",
    "não fecha, não marca CLOEXEC e não reposiciona descritores",
)
NOT_VERIFIED = (
    "ambiente (envp) e diretório de trabalho",
    "terminal controlador, sessão e grupo de processos",
    "mounts, namespaces e capacidades de rede já presentes no processo",
    "IPC e SCM_RIGHTS",
    "comportamento do SRT/bubblewrap com descritores preexistentes",
    "no_new_privs, dumpable, ptrace",
)


class BootRefused(ValueError):
    """Recusa estável; str(e) é o código."""

    @property
    def code(self):
        return str(self)


@dataclasses.dataclass(frozen=True)
class Grant:
    fd: int
    kind: str
    dev: int
    ino: int
    inheritable: bool
    purpose: str


def _require_platform():
    if sys.platform != "linux":
        raise BootRefused("unsupported_platform")


def _kind_of(st, fd, target):
    mode = st.st_mode
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "regular"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode):
        if st.st_rdev == _DEVNULL_RDEV:
            return "chr_devnull"
        try:
            if os.isatty(fd):
                return "tty"
        except OSError:
            pass
        return "chr_other"
    if target.startswith("anon_inode:"):
        return "anon_inode"
    return "other"


def _safe_target(target):
    """Mantém só alvos não pessoais; caminhos de arquivo são redigidos."""
    if target.startswith(("pipe:", "socket:", "anon_inode:")) or target == "/dev/null":
        return target[:64]
    if target.startswith(("/dev/pts/", "/dev/tty")):
        return "<tty>"
    return "<redacted-path>"


def _describe_fd(fd):
    """Levanta OSError se o FD não existir mais (ex.: o FD da própria listagem)."""
    st = os.fstat(fd)
    target = os.readlink("/proc/self/fd/%d" % fd)
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    cloexec = bool(fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC)
    return {"fd": fd, "kind": _kind_of(st, fd, target), "dev": int(st.st_dev),
            "ino": int(st.st_ino), "cloexec": cloexec, "flags": int(flags),
            "access": _ACCESS.get(flags & os.O_ACCMODE, "other"),
            "opath": bool(flags & _O_PATH), "target": _safe_target(target)}


class CapabilityRegistry:
    """Capacidades que ESTE processo criou. Não há registro por declaração.

    As fábricas abrem o objeto aqui e registram a identidade observada logo
    depois. Os testes só as chamam em subprocessos descartáveis.
    """

    def __init__(self):
        self.grants = {}

    def _record(self, fd, purpose, inheritable):
        entry = _describe_fd(fd)
        self.grants[fd] = Grant(fd, entry["kind"], entry["dev"], entry["ino"],
                                inheritable, purpose)
        return fd

    def place_devnull(self, target_fd):
        """Abre /dev/null NOVO (não duplica FD herdado) e o coloca em 0, 1 ou 2."""
        if target_fd not in (0, 1, 2):
            raise BootRefused("invalid_target")
        tmp = os.open("/dev/null", os.O_RDWR | os.O_CLOEXEC)
        try:
            os.dup2(tmp, target_fd, inheritable=True)  # deve atravessar execve
        finally:
            if tmp != target_fd:
                os.close(tmp)
        return self._record(target_fd, "stdio_devnull", True)

    def make_pipe(self):
        """Pipe criado aqui, com CLOEXEC; devolve (leitura, escrita)."""
        r, w = os.pipe2(os.O_CLOEXEC)
        self._record(r, "supervisor_pipe_read", False)
        self._record(w, "supervisor_pipe_write", False)
        return r, w


def collect_inventory():
    """Lê /proc/self/fd. Devolve o inventário bruto, com marcador de completude.

    `complete` só é True se um FD sentinela aberto aqui reaparece com a
    identidade esperada e exatamente um FD transitório (o da listagem) some.
    """
    _require_platform()
    if threading.active_count() != 1:
        raise BootRefused("multithreaded")
    try:
        if len(os.listdir("/proc/self/task")) != 1:
            raise BootRefused("multithreaded")
        if os.readlink("/proc/self") != str(os.getpid()):
            raise BootRefused("proc_mismatch")
        sentinel = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        raise BootRefused("inventory_unavailable") from None
    try:
        try:
            names = os.listdir("/proc/self/fd")
            expected = _describe_fd(sentinel)
        except OSError:
            raise BootRefused("inventory_unavailable") from None
        entries, transient, sentinel_ok = [], 0, False
        for name in names:
            try:
                fd = int(name)
            except ValueError:
                raise BootRefused("inventory_malformed") from None
            try:
                entry = _describe_fd(fd)
            except OSError as e:
                if e.errno in (errno.ENOENT, errno.EBADF):
                    transient += 1
                    continue
                raise BootRefused("inventory_unavailable") from None
            if fd == sentinel:
                sentinel_ok = entry == expected
                continue
            entries.append(entry)
    finally:
        os.close(sentinel)
    entries.sort(key=lambda e: e["fd"])
    return {"complete": sentinel_ok and transient == 1, "entries": entries,
            "transient": transient, "sentinel_verified": sentinel_ok}


def _validate_inventory(inv):
    if type(inv) is not dict or set(inv) != _INVENTORY_KEYS:
        raise BootRefused("inventory_malformed")
    if inv["complete"] is not True or inv["sentinel_verified"] is not True:
        raise BootRefused("inventory_incomplete")
    if type(inv["transient"]) is not int or type(inv["entries"]) is not list:
        raise BootRefused("inventory_malformed")
    seen = set()
    for entry in inv["entries"]:
        if type(entry) is not dict or set(entry) != _ENTRY_KEYS:
            raise BootRefused("inventory_malformed")
        ints = ("fd", "dev", "ino", "flags")
        if any(type(entry[k]) is not int for k in ints) or entry["fd"] < 0:
            raise BootRefused("inventory_malformed")
        if any(type(entry[k]) is not bool for k in ("cloexec", "opath")):
            raise BootRefused("inventory_malformed")
        if entry["kind"] not in KINDS or type(entry["access"]) is not str \
                or type(entry["target"]) is not str:
            raise BootRefused("inventory_malformed")
        if entry["fd"] in seen:
            raise BootRefused("inventory_malformed")
        seen.add(entry["fd"])


def _classify(entry, grant):
    if grant is None:
        return "unknown", "no_grant"
    if (grant.kind, grant.dev, grant.ino) != (entry["kind"], entry["dev"], entry["ino"]):
        return "unknown", "grant_identity_mismatch"
    if entry["cloexec"] == grant.inheritable:
        return "unknown", "grant_cloexec_mismatch"
    return "authorized", grant.purpose


def evaluate(inventory, registry):
    """Valida o inventário e o confronta com o registro; levanta BootRefused."""
    _require_platform()
    if not isinstance(registry, CapabilityRegistry):
        raise BootRefused("invalid_registry")
    for grant in registry.grants.values():
        if grant.kind not in KINDS:
            raise BootRefused("unexpected_capability_kind")
    _validate_inventory(inventory)
    present = {e["fd"] for e in inventory["entries"]}
    classified, unknown = [], []
    for entry in inventory["entries"]:
        status, reason = _classify(entry, registry.grants.get(entry["fd"]))
        classified.append({**entry, "status": status, "reason": reason})
        if status == "unknown":
            unknown.append(entry["fd"])
    std_closed = [fd for fd in (0, 1, 2) if fd not in present]
    grants_missing = sorted(fd for fd in registry.grants if fd not in present)
    clean = not unknown and not std_closed and not grants_missing
    return _report("CLEAN_FOR_GRANTS" if clean else "UNKNOWN_CAPABILITIES",
                   entries=classified, unknown_fds=unknown,
                   std_closed=std_closed, grants_missing=grants_missing)


def _report(verdict, **extra):
    assert verdict in _VERDICTS
    return {"schema": SCHEMA, **INVARIANTS, "verdict": verdict,
            "bootstrap_trusted": False, "bootstrap_complete": False,
            "inventory_source": "/proc/self/fd", "close_range_used": False,
            "limitations": list(LIMITATIONS), "not_verified": list(NOT_VERIFIED),
            **extra}


def diagnose(registry, collect=collect_inventory):
    """Nunca levanta: exceção, saída malformada ou ausência vira REFUSED."""
    try:
        return evaluate(collect(), registry)
    except BootRefused as refused:
        return _report("REFUSED", reason=refused.code)
    except Exception:  # evidência insuficiente, nunca sucesso implícito
        return _report("REFUSED", reason="evidence_insufficient")


def main(argv):
    import json
    if list(argv) not in (["--synthetic-only"], ["--synthetic-only", "--json"]):
        print("uso: supervisor_boot.py --synthetic-only [--json]", file=sys.stderr)
        return 64
    report = diagnose(CapabilityRegistry())
    print(json.dumps(report, indent=2, sort_keys=True) if "--json" in argv
          else report["verdict"])
    return 2  # nunca 0: o diagnóstico não autoriza nada


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
