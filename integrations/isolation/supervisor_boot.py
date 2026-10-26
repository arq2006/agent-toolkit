#!/usr/bin/env python3
"""Protótipo GH-F1.18/PR-B: diagnóstico de descritores herdados do supervisor.

Inventaria /proc/self/fd (inclusive FDs 0, 1 e 2), confronta a listagem com uma
sondagem independente por fcntl, distingue capacidades que o PRÓPRIO supervisor
criou e registrou das desconhecidas e recusa inventário inconsistente ou
malformado. close_range NÃO é usado: ele não faz inventário.

Somente diagnóstico. Nunca declara o bootstrap confiável ou completo, não
fecha nem altera descritores herdados, não executa agentes. STRONG=UNAVAILABLE e
readiness=BLOCKED permanecem. Grants só nascem das fábricas de
CapabilityRegistry (FD criado aqui); descritor herdado nunca é autorizado por
declaração. Encapsulamento é proteção contra uso acidental: um processo Python
capaz de alterar objetos arbitrariamente está FORA da garantia.

Três coisas distintas, que este módulo nunca confunde:
- inventário estruturalmente consistente: listagem, sondagem e metadados
  concordam entre si nesta observação;
- inventário efetivamente completo: NÃO comprovável (corridas, /proc
  adulterado de forma consistente); o relatório afirma sempre False;
- ausência de capacidades não observadas: NÃO comprovada (sempre False).
"""
import ctypes
import dataclasses
import errno
import fcntl
import os
import platform
import resource
import stat
import sys
import threading
import types

from trusted_root import INVARIANTS, check_report

SCHEMA = "supervisor-boot-diagnostic/2"
KINDS = ("directory", "regular", "chr_devnull", "chr_other", "tty",
         "fifo", "socket", "anon_inode", "other")
_ENTRY_KEYS = frozenset(("fd", "kind", "dev", "ino", "cloexec", "flags",
                         "access", "opath", "target"))
_INVENTORY_KEYS = frozenset(("structurally_consistent", "entries", "transient",
                             "sentinel_verified", "probe_agrees", "probe_range"))
_DEVNULL_RDEV = os.makedev(1, 3)
_O_PATH = getattr(os, "O_PATH", 0o10000000)
_ACCESS = {os.O_RDONLY: "rdonly", os.O_WRONLY: "wronly", os.O_RDWR: "rdwr"}
_VERDICTS = ("CLEAN_FOR_GRANTS", "UNKNOWN_CAPABILITIES", "REFUSED")
_MAX_PROBE = 1 << 20
_NR_KCMP = {"x86_64": 312, "amd64": 312, "aarch64": 272, "arm64": 272}
_KCMP_FILE = 0
_MINT = object()  # só as fábricas de CapabilityRegistry o possuem

LIMITATIONS = (
    "diagnóstico de uma observação: descritores podem mudar depois dela",
    "exige processo monothread; threads criadas por terceiros invalidam o inventário",
    "/proc é assumido como procfs do próprio processo (verificação parcial por pid)",
    "inventário estruturalmente consistente NÃO é inventário efetivamente completo",
    "ausência de capacidades não observadas NÃO é comprovada",
    "identidade de open file description só via kcmp contra âncora do registro; sem kcmp, grants ficam unknown",
    "grants cobrem apenas FDs criados por este módulo; não autenticam origem externa",
    "encapsulamento do registro não resiste a processo Python comprometido (A3 fora da garantia)",
    "não fecha, não marca CLOEXEC e não reposiciona descritores herdados",
)
NOT_VERIFIED = (
    "ambiente (envp) e diretório de trabalho",
    "terminal controlador, sessão e grupo de processos",
    "mounts, namespaces e capacidades de rede já presentes no processo",
    "IPC e SCM_RIGHTS",
    "comportamento do SRT/bubblewrap com descritores preexistentes",
    "no_new_privs, dumpable, ptrace",
)
_RESERVED = frozenset(INVARIANTS) | frozenset((
    "schema", "verdict", "bootstrap_trusted", "bootstrap_complete",
    "inventory_source", "close_range_used", "limitations", "not_verified",
    "inventory_structurally_consistent", "inventory_effectively_complete",
    "unobserved_capabilities_excluded"))


class BootRefused(ValueError):
    """Recusa estável; str(e) é o código."""

    @property
    def code(self):
        return str(self)


@dataclasses.dataclass(frozen=True)
class Grant:
    """Concessão nascida de uma fábrica: identidade E direitos do FD.

    `flags` é o F_GETFL completo (modo de acesso, O_PATH, O_APPEND, ...).
    `anchor_fd` é um dup privado (mesma open file description) usado para
    comprovar por kcmp que o FD concedido não foi trocado.
    """
    fd: int
    kind: str
    dev: int
    ino: int
    flags: int
    inheritable: bool
    purpose: str
    anchor_fd: int
    _mint: object = dataclasses.field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._mint is not _MINT:
            raise TypeError("Grant só pode ser criado pelas fábricas do registro")


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


def _kcmp_same_ofd(fd_a, fd_b):
    """True/False se os dois FDs compartilham a open file description; None se
    o kernel não permitir a comparação (informação insuficiente)."""
    nr = _NR_KCMP.get(platform.machine().lower())
    if nr is None:
        return None
    try:
        call = ctypes.CDLL(None, use_errno=True).syscall
        call.restype = ctypes.c_long
        pid = os.getpid()
        result = call(ctypes.c_long(nr), ctypes.c_long(pid), ctypes.c_long(pid),
                      ctypes.c_int(_KCMP_FILE), ctypes.c_ulong(fd_a),
                      ctypes.c_ulong(fd_b))
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if result < 0:
        return None
    return result == 0


class CapabilityRegistry:
    """Capacidades que ESTE processo criou. Não há registro por declaração.

    As fábricas abrem o objeto aqui e registram identidade e direitos logo
    depois; `grants` é uma visão somente leitura. Os testes só chamam as
    fábricas em subprocessos descartáveis.
    """
    __slots__ = ("_grants",)

    def __init__(self):
        self._grants = {}

    @property
    def grants(self):
        return types.MappingProxyType(self._grants)

    def _record(self, fd, purpose, inheritable):
        entry = _describe_fd(fd)
        # Âncora >= 3 para nunca ocupar um slot padrão fechado.
        anchor = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)
        try:
            self._grants[fd] = Grant(fd, entry["kind"], entry["dev"], entry["ino"],
                                     entry["flags"], inheritable, purpose, anchor,
                                     _mint=_MINT)
        except BaseException:
            os.close(anchor)
            raise
        return fd

    def place_devnull(self, target_fd):
        """Abre /dev/null NOVO (não duplica FD herdado) em 0, 1 ou 2, herdável.

        Confia que o /dev/null do namespace atual é o dispositivo 1:3 (verificado
        por rdev após a abertura); não protege contra quem controla /dev.
        Se o slot estava fechado e open() reutilizou exatamente esse número,
        o dup2(fd, fd) seria um no-op: as flags são ajustadas explicitamente.
        Falha fechado: se o estado efetivo não for o contratado, levanta
        BootRefused; um slot que esta chamada abriu é devolvido fechado.
        """
        if type(target_fd) is not int or target_fd not in (0, 1, 2):
            raise BootRefused("invalid_target")
        try:
            tmp = os.open("/dev/null", os.O_RDWR | os.O_CLOEXEC)
        except OSError:
            raise BootRefused("place_devnull_failed") from None
        try:
            st = os.fstat(tmp)
            if not stat.S_ISCHR(st.st_mode) or st.st_rdev != _DEVNULL_RDEV:
                raise BootRefused("devnull_identity")
            if tmp == target_fd:
                # dup2(fd, fd) não altera flags: ajusta CLOEXEC explicitamente.
                os.set_inheritable(tmp, True)
            else:
                os.dup2(tmp, target_fd, inheritable=True)
                os.close(tmp)
                tmp = None
            state = _describe_fd(target_fd)
            if (state["kind"], state["cloexec"], state["access"], state["opath"]) \
                    != ("chr_devnull", False, "rdwr", False):
                raise BootRefused("place_devnull_state")
            return self._record(target_fd, "stdio_devnull", True)
        except BootRefused:
            self._close_quietly(tmp)  # se tmp reutilizou o slot, devolve-o fechado
            raise
        except OSError:
            self._close_quietly(tmp)
            raise BootRefused("place_devnull_failed") from None

    @staticmethod
    def _close_quietly(fd):
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def make_pipe(self):
        """Pipe criado aqui, com CLOEXEC; devolve (leitura, escrita)."""
        r, w = os.pipe2(os.O_CLOEXEC)
        self._record(r, "supervisor_pipe_read", False)
        self._record(w, "supervisor_pipe_write", False)
        return r, w


def _mint_grant(fd, kind, dev, ino, flags, inheritable, purpose, anchor_fd):
    """Apenas para testes com inventários sintéticos; não faz parte da API."""
    return Grant(fd, kind, dev, ino, flags, inheritable, purpose, anchor_fd, _mint=_MINT)


def _registry_with(*grants):
    """Apenas para testes com inventários sintéticos; não faz parte da API."""
    registry = CapabilityRegistry()
    for grant in grants:
        registry._grants[grant.fd] = grant
    return registry


def _list_fd_names():
    return os.listdir("/proc/self/fd")


def _probe_open_fds(limit):
    """Sondagem independente de /proc: quais números aceitam F_GETFD."""
    found = set()
    for fd in range(limit):
        try:
            fcntl.fcntl(fd, fcntl.F_GETFD)
        except OSError as e:
            if e.errno != errno.EBADF:
                raise BootRefused("inventory_unavailable") from None
        else:
            found.add(fd)
    return found


def collect_inventory():
    """Lê /proc/self/fd e confronta com sondagem fcntl independente.

    Os campos descrevem consistência estrutural, nunca completude provada:
    - sentinel_verified: o FD /dev/null aberto aqui reapareceu com a identidade;
    - probe_agrees: nenhum FD sondado ficou fora da listagem e exatamente um
      número listado (o da própria listagem) não existe mais;
    - estável: uma segunda descrição de cada FD é idêntica à primeira.
    """
    _require_platform()
    if threading.active_count() != 1:
        raise BootRefused("multithreaded")
    try:
        if len(os.listdir("/proc/self/task")) != 1:
            raise BootRefused("multithreaded")
        if os.readlink("/proc/self") != str(os.getpid()):
            raise BootRefused("proc_mismatch")
        with open("/proc/self/stat", "rb") as stat_file:
            if stat_file.read(32).split(b" ", 1)[0] != str(os.getpid()).encode():
                raise BootRefused("proc_mismatch")
        limit = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
        if limit == resource.RLIM_INFINITY or limit > _MAX_PROBE:
            raise BootRefused("probe_range_exceeded")
        sentinel = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        raise BootRefused("inventory_unavailable") from None
    try:
        try:
            names = _list_fd_names()
            expected = _describe_fd(sentinel)
        except OSError:
            raise BootRefused("inventory_unavailable") from None
        try:
            listed = {int(n) for n in names}
        except ValueError:
            raise BootRefused("inventory_malformed") from None
        if len(listed) != len(names):
            raise BootRefused("inventory_malformed")
        probed = _probe_open_fds(limit)
        transient = sorted(listed - probed)   # esperado: só o FD da listagem
        omitted = sorted(probed - listed)     # FD real que a listagem não mostrou
        entries, sentinel_ok = [], False
        for fd in sorted(listed & probed):
            try:
                entry = _describe_fd(fd)
            except OSError as e:
                if e.errno in (errno.ENOENT, errno.EBADF):
                    raise BootRefused("inventory_unstable") from None
                raise BootRefused("inventory_unavailable") from None
            if fd == sentinel:
                sentinel_ok = entry == expected
                continue
            entries.append(entry)
        try:
            again = [_describe_fd(e["fd"]) for e in entries]
        except OSError:
            raise BootRefused("inventory_unstable") from None
        stable = again == entries
    finally:
        os.close(sentinel)
    return {"structurally_consistent": bool(sentinel_ok and stable),
            "entries": entries, "transient": len(transient),
            "sentinel_verified": sentinel_ok,
            "probe_agrees": not omitted and len(transient) == 1,
            "probe_range": limit}


def _validate_inventory(inv):
    if type(inv) is not dict or set(inv) != _INVENTORY_KEYS:
        raise BootRefused("inventory_malformed")
    for key in ("structurally_consistent", "sentinel_verified", "probe_agrees"):
        if type(inv[key]) is not bool:
            raise BootRefused("inventory_malformed")
    if type(inv["transient"]) is not int or type(inv["entries"]) is not list \
            or type(inv["probe_range"]) is not int:
        raise BootRefused("inventory_malformed")
    if not (inv["structurally_consistent"] and inv["sentinel_verified"]
            and inv["probe_agrees"]):
        raise BootRefused("inventory_inconsistent")
    seen = set()
    for entry in inv["entries"]:
        if type(entry) is not dict or set(entry) != _ENTRY_KEYS:
            raise BootRefused("inventory_malformed")
        if any(type(entry[k]) is not int for k in ("fd", "dev", "ino", "flags")) \
                or entry["fd"] < 0:
            raise BootRefused("inventory_malformed")
        if any(type(entry[k]) is not bool for k in ("cloexec", "opath")):
            raise BootRefused("inventory_malformed")
        if entry["kind"] not in KINDS or type(entry["access"]) is not str \
                or type(entry["target"]) is not str:
            raise BootRefused("inventory_malformed")
        if entry["fd"] in seen:
            raise BootRefused("inventory_malformed")
        seen.add(entry["fd"])


def _validate_registry(registry):
    if type(registry) is not CapabilityRegistry:
        raise BootRefused("invalid_registry")
    grants = registry._grants
    for fd, grant in grants.items():
        if type(grant) is not Grant or grant._mint is not _MINT or grant.fd != fd:
            raise BootRefused("invalid_grant")
        if grant.kind not in KINDS:
            raise BootRefused("unexpected_capability_kind")
        if any(type(v) is not int for v in (grant.dev, grant.ino, grant.flags,
                                            grant.anchor_fd)) \
                or type(grant.inheritable) is not bool:
            raise BootRefused("invalid_grant")
    return grants


def _mismatches(entry, grant, same_ofd):
    """Atributos que diferenciam o FD observado da concessão (estrito)."""
    diff = []
    if (grant.kind, grant.dev, grant.ino) != (entry["kind"], entry["dev"], entry["ino"]):
        diff.append("identity")
    if (grant.flags & os.O_ACCMODE) != (entry["flags"] & os.O_ACCMODE):
        diff.append("access")
    if bool(grant.flags & _O_PATH) != entry["opath"]:
        diff.append("opath")
    if grant.flags != entry["flags"] and "access" not in diff and "opath" not in diff:
        diff.append("flags")
    if entry["cloexec"] == grant.inheritable:
        diff.append("cloexec")
    same = same_ofd(entry["fd"], grant.anchor_fd)
    if same is None:
        diff.append("ofd_unverifiable")
    elif not same:
        diff.append("ofd")
    return diff


def _classify(entry, grants, anchors, same_ofd):
    grant = grants.get(entry["fd"])
    if grant is not None:
        diff = _mismatches(entry, grant, same_ofd)
        if diff:
            return "unknown", "grant_mismatch", diff
        return "authorized", grant.purpose, []
    owner = anchors.get(entry["fd"])
    if owner is not None:  # dup privado do registro: mesma autoridade do grant
        if (owner.kind, owner.dev, owner.ino, owner.flags) == \
                (entry["kind"], entry["dev"], entry["ino"], entry["flags"]) \
                and entry["cloexec"]:
            return "authorized", "registry_anchor", []
        return "unknown", "anchor_mismatch", ["identity"]
    return "unknown", "no_grant", []


def _evaluate(inventory, registry, same_ofd):
    _require_platform()
    grants = _validate_registry(registry)
    _validate_inventory(inventory)
    anchors = {g.anchor_fd: g for g in grants.values()}
    if len(anchors) != len(grants) or set(anchors) & set(grants):
        raise BootRefused("invalid_grant")
    present = {e["fd"] for e in inventory["entries"]}
    classified, unknown = [], []
    for entry in inventory["entries"]:
        status, reason, diff = _classify(entry, grants, anchors, same_ofd)
        classified.append({**entry, "status": status, "reason": reason,
                           "mismatch": diff})
        if status == "unknown":
            unknown.append(entry["fd"])
    std_closed = [fd for fd in (0, 1, 2) if fd not in present]
    grants_missing = sorted(fd for fd in grants if fd not in present)
    clean = not unknown and not std_closed and not grants_missing
    return _report("CLEAN_FOR_GRANTS" if clean else "UNKNOWN_CAPABILITIES",
                   entries=classified, unknown_fds=unknown,
                   std_closed=std_closed, grants_missing=grants_missing)


def evaluate(inventory, registry):
    """Valida o inventário e o confronta com o registro; levanta BootRefused."""
    return _evaluate(inventory, registry, _kcmp_same_ofd)


def _report(verdict, /, **extra):
    if verdict not in _VERDICTS:
        raise ValueError("invalid_verdict")
    if _RESERVED & set(extra):
        raise ValueError("reserved_field")
    report = {**extra, "schema": SCHEMA, **INVARIANTS, "verdict": verdict,
              "bootstrap_trusted": False, "bootstrap_complete": False,
              "inventory_source": "/proc/self/fd + fcntl probe",
              "close_range_used": False,
              "inventory_structurally_consistent": verdict != "REFUSED",
              "inventory_effectively_complete": False,
              "unobserved_capabilities_excluded": False,
              "limitations": list(LIMITATIONS), "not_verified": list(NOT_VERIFIED)}
    return check_report(report)


def _diagnose(registry, collect):
    try:
        return evaluate(collect(), registry)
    except BootRefused as refused:
        return _report("REFUSED", reason=refused.code)
    except Exception:  # evidência insuficiente, nunca sucesso implícito
        return _report("REFUSED", reason="evidence_insufficient")


def diagnose(registry):
    """Nunca levanta: exceção, ausência ou saída malformada viram REFUSED."""
    return _diagnose(registry, collect_inventory)


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
