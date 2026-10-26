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
import re
import resource
import stat
import sys
import threading
import types

from trusted_root import INVARIANTS, check_report

SCHEMA = "supervisor-boot-diagnostic/3"
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
_PROVENANCE = ("none", "collected_in_process", "caller_supplied_unverified")
_MAX_PROBE = 1 << 20
# Único formato de `target` aceito num relatório: valores que _safe_target() produz.
# Nada que o chamador escreva (caminhos, "pipe:/x", quebras de linha) é reproduzido.
_SAFE_TARGET = re.compile(
    r"(?:/dev/null|<tty>|<redacted-path>"
    r"|(?:pipe|socket):\[[0-9]{1,20}\]"
    r"|anon_inode:\[?[A-Za-z0-9_-]{1,32}\]?)\Z")
_NR_KCMP = {"x86_64": 312, "amd64": 312, "aarch64": 272, "arm64": 272}
_KCMP_FILE = 0

LIMITATIONS = (
    "diagnóstico de uma observação: descritores podem mudar depois dela",
    "exige processo monothread; threads criadas por terceiros invalidam o inventário",
    "/proc é assumido como procfs do próprio processo (verificação parcial por pid)",
    "inventário estruturalmente consistente NÃO é inventário efetivamente completo",
    "ausência de capacidades não observadas NÃO é comprovada",
    "identidade de open file description só via kcmp contra âncora do registro; sem kcmp, grants ficam unknown",
    "grants cobrem apenas FDs criados por este módulo; não autenticam origem externa",
    "encapsulamento do registro (sem API de declaração, estado privado) NÃO resiste a código arbitrário no mesmo processo Python (A3 fora da garantia)",
    "inventário recebido como dicionário não tem proveniência confiável só por passar na validação estrutural",
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
    "unobserved_capabilities_excluded", "inventory_provenance", "provenance"))


class BootRefused(ValueError):
    """Recusa estável; str(e) é o código."""

    @property
    def code(self):
        return str(self)


@dataclasses.dataclass(frozen=True)
class Grant:
    """Concessão emitida por uma fábrica do registro: identidade E direitos.

    `flags` é o F_GETFL completo (modo de acesso, O_PATH, O_APPEND, ...).
    `anchor_fd` é um dup privado (mesma open file description) usado para
    comprovar por kcmp que o FD concedido não foi trocado. Construir um Grant
    não concede nada: só vale o que o próprio registro emitiu e ainda guarda.
    """
    fd: int
    kind: str
    dev: int
    ino: int
    flags: int
    inheritable: bool
    purpose: str
    anchor_fd: int


class _Created:
    """Recibo de um FD que uma fábrica criou agora e ainda não foi emitido."""
    __slots__ = ("fd", "anchor", "entry", "purpose", "inheritable")

    def __init__(self, fd, anchor, entry, purpose, inheritable):
        self.fd, self.anchor, self.entry = fd, anchor, entry
        self.purpose, self.inheritable = purpose, inheritable


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
    """Só devolve alvos que casam com o formato fechado _SAFE_TARGET; caminhos de
    arquivo e qualquer outra coisa viram "<redacted-path>"."""
    if _SAFE_TARGET.match(target):
        return target
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


def _close_quietly(fd):
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass


class CapabilityRegistry:
    """Capacidades que ESTE processo criou. Não há API de declaração.

    Só as fábricas (`place_devnull`, `make_pipe`) criam o FD e emitem o grant;
    nenhum método aceita um FD já existente. `grants` é uma visão somente
    leitura. `close()` (idempotente) libera as âncoras e invalida todos os
    grants; os FDs entregues ao chamador (pipes, slots 0-2) não são fechados.
    Os testes só chamam as fábricas em subprocessos descartáveis.

    Limite: isto elimina o caminho de concessão por declaração da interface
    operacional; não é fronteira de segurança contra código Python arbitrário
    no mesmo processo, que pode alterar qualquer objeto (A3, fora da garantia).
    """
    __slots__ = ("_grants", "_issued", "_pending", "_closed")

    def __init__(self):
        self._grants = {}
        self._issued = set()    # ids dos Grants emitidos por ESTE registro
        self._pending = []      # recibos criados e ainda não emitidos
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def grants(self):
        return types.MappingProxyType(self._grants)

    @property
    def closed(self):
        return self._closed

    def _require_open(self):
        if self._closed:
            raise BootRefused("registry_closed")

    def _issue(self, created):
        """Emite o grant de um recibo criado por uma fábrica; recusa qualquer
        outra coisa (inclusive um int: "registrar" um FD por declaração)."""
        if type(created) is not _Created or not any(created is p for p in self._pending):
            raise BootRefused("declaration_refused")
        self._require_open()
        self._pending = [p for p in self._pending if p is not created]
        self._revoke(created.fd)
        entry = created.entry
        grant = Grant(created.fd, entry["kind"], entry["dev"], entry["ino"],
                      entry["flags"], created.inheritable, created.purpose,
                      created.anchor)
        self._grants[created.fd] = grant
        self._issued.add(id(grant))

    def _revoke(self, fd):
        grant = self._grants.pop(fd, None)
        if grant is not None:
            self._issued.discard(id(grant))
            _close_quietly(grant.anchor_fd)

    def close(self):
        """Libera âncoras e invalida os grants. Idempotente."""
        for fd in list(self._grants):
            self._revoke(fd)
        for created in self._pending:
            _close_quietly(created.anchor)
        self._pending = []
        self._closed = True

    def place_devnull(self, target_fd):
        """Abre /dev/null NOVO (não duplica FD herdado) em 0, 1 ou 2, herdável.

        Confia que o /dev/null do namespace atual é o dispositivo 1:3 (verificado
        por rdev após a abertura); não protege contra quem controla /dev.
        Se o slot estava fechado e open() reutilizou exatamente esse número,
        o dup2(fd, fd) seria um no-op: as flags são ajustadas explicitamente.
        Falha fechado: se o estado efetivo não for o contratado, levanta
        BootRefused e nada é emitido; um slot que esta chamada abriu é devolvido
        fechado. Se a falha ocorrer DEPOIS de o dup2 ter substituído o objeto
        herdado, o slot permanece como /dev/null herdável, sem grant (a
        autoridade herdada anterior já foi descartada e não é restaurável).
        """
        self._require_open()
        if type(target_fd) is not int or target_fd not in (0, 1, 2):
            raise BootRefused("invalid_target")
        try:
            tmp = os.open("/dev/null", os.O_RDWR | os.O_CLOEXEC)
        except OSError:
            raise BootRefused("place_devnull_failed") from None
        anchor, issued = None, False
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
            # Âncora >= 3 para nunca ocupar um slot padrão fechado.
            anchor = fcntl.fcntl(target_fd, fcntl.F_DUPFD_CLOEXEC, 3)
            created = _Created(target_fd, anchor, state, "stdio_devnull", True)
            self._pending.append(created)
            self._issue(created)
            issued = True
            return target_fd
        except BaseException as e:
            _close_quietly(tmp)  # se tmp reutilizou o slot, devolve-o fechado
            if anchor is not None and not issued:
                _close_quietly(anchor)
                self._pending = [p for p in self._pending if p.anchor != anchor]
            if isinstance(e, BootRefused):
                raise
            if isinstance(e, OSError):
                raise BootRefused("place_devnull_failed") from None
            raise

    def make_pipe(self):
        """Pipe criado aqui, com CLOEXEC; devolve (leitura, escrita).

        Tudo ou nada: se qualquer etapa falhar, nenhum grant é emitido e os
        dois FDs e as âncoras são fechados.
        """
        self._require_open()
        try:
            r, w = os.pipe2(os.O_CLOEXEC)
        except OSError:
            raise BootRefused("make_pipe_failed") from None
        made = []
        try:
            for fd, purpose in ((r, "supervisor_pipe_read"), (w, "supervisor_pipe_write")):
                state = _describe_fd(fd)
                anchor = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)
                created = _Created(fd, anchor, state, purpose, False)
                self._pending.append(created)
                made.append(created)
            for created in made:
                self._issue(created)
            return r, w
        except BaseException as e:
            for created in made:
                self._revoke(created.fd)
                _close_quietly(created.anchor)
            self._pending = [p for p in self._pending if not any(p is m for m in made)]
            _close_quietly(r)
            _close_quietly(w)
            if isinstance(e, (OSError, BootRefused)):
                raise BootRefused("make_pipe_failed") from None
            raise


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
    - structurally_consistent: sentinela ok E duas descrições idênticas de cada
      FD E uma segunda listagem coerente com a primeira.
    O dicionário devolvido NÃO tem proveniência confiável para quem o recebe.
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
        if limit == resource.RLIM_INFINITY or not (3 <= limit <= _MAX_PROBE):
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
            relisted = {int(n) for n in _list_fd_names()}
        except (OSError, ValueError):
            raise BootRefused("inventory_unstable") from None
        # Nada novo (nem sumido) entre as duas listagens dentro do intervalo sondado.
        stable = again == entries and (relisted & probed) == (listed & probed) \
            and len(relisted - probed) == 1
    finally:
        os.close(sentinel)
    return {"structurally_consistent": bool(sentinel_ok and stable),
            "entries": entries, "transient": len(transient),
            "sentinel_verified": sentinel_ok,
            "probe_agrees": not omitted and len(transient) == 1,
            "probe_range": limit}


def _validate_inventory(inv):
    """Valida tipos E relações entre campos. Passar aqui NÃO dá proveniência:
    um dicionário recebido de fora continua sendo dado não confiável."""
    if type(inv) is not dict or set(inv) != _INVENTORY_KEYS:
        raise BootRefused("inventory_malformed")
    for key in ("structurally_consistent", "sentinel_verified", "probe_agrees"):
        if type(inv[key]) is not bool:
            raise BootRefused("inventory_malformed")
    if any(type(inv[k]) is not int for k in ("transient", "probe_range")) \
            or type(inv["entries"]) is not list or inv["transient"] < 0:
        raise BootRefused("inventory_malformed")
    limit = inv["probe_range"]
    if not (3 <= limit <= _MAX_PROBE):
        raise BootRefused("inventory_malformed")
    previous = -1
    for entry in inv["entries"]:
        if type(entry) is not dict or set(entry) != _ENTRY_KEYS:
            raise BootRefused("inventory_malformed")
        if any(type(entry[k]) is not int or entry[k] < 0
               for k in ("fd", "dev", "ino", "flags")):
            raise BootRefused("inventory_malformed")
        if any(type(entry[k]) is not bool for k in ("cloexec", "opath")):
            raise BootRefused("inventory_malformed")
        if entry["kind"] not in KINDS or type(entry["access"]) is not str \
                or type(entry["target"]) is not str:
            raise BootRefused("inventory_malformed")
        # Regra de recusa (não de reescrita): o alvo vira texto de relatório, então
        # só o formato fechado de _safe_target() passa; "pipe:/private" também não.
        if not _SAFE_TARGET.match(entry["target"]):
            raise BootRefused("inventory_target_invalid")
        if entry["fd"] <= previous:   # duplicata ou fora de ordem
            raise BootRefused("inventory_malformed")
        previous = entry["fd"]
        # Campos derivados precisam concordar com os flags brutos.
        if entry["access"] != _ACCESS.get(entry["flags"] & os.O_ACCMODE, "other") \
                or entry["opath"] != bool(entry["flags"] & _O_PATH):
            raise BootRefused("inventory_contradictory")
        if entry["fd"] >= limit:      # fora do intervalo efetivamente sondado
            raise BootRefused("inventory_contradictory")
    # Relações entre as afirmações de sucesso.
    if inv["structurally_consistent"] and not inv["sentinel_verified"]:
        raise BootRefused("inventory_contradictory")
    if inv["probe_agrees"] and inv["transient"] != 1:
        raise BootRefused("inventory_contradictory")
    if not (inv["structurally_consistent"] and inv["sentinel_verified"]
            and inv["probe_agrees"]):
        raise BootRefused("inventory_inconsistent")


def _validate_registry(registry):
    if type(registry) is not CapabilityRegistry:
        raise BootRefused("invalid_registry")
    if registry._closed:
        raise BootRefused("registry_closed")
    grants = registry._grants
    for fd, grant in grants.items():
        if type(grant) is not Grant or id(grant) not in registry._issued \
                or grant.fd != fd:
            raise BootRefused("invalid_grant")   # não emitido por este registro
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


def _evaluate(inventory, registry, same_ofd, provenance):
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
                   provenance=provenance, entries=classified, unknown_fds=unknown,
                   std_closed=std_closed, grants_missing=grants_missing)


def evaluate(inventory, registry):
    """Valida o inventário e o confronta com o registro; levanta BootRefused.

    O inventário é dado do chamador (proveniência não confiável); o relatório
    o declara em `inventory_provenance`."""
    return _evaluate(inventory, registry, _kcmp_same_ofd, "caller_supplied_unverified")


def check_boot_report(report):
    """Invariantes + coerência entre verdict e demais campos; levanta ValueError."""
    check_report(report)
    verdict = report.get("verdict")
    if verdict not in _VERDICTS or report.get("schema") != SCHEMA:
        raise ValueError("report_malformed")
    for key in ("bootstrap_trusted", "bootstrap_complete",
                "inventory_effectively_complete", "unobserved_capabilities_excluded"):
        if key not in report:
            raise ValueError("report_malformed")
    consistent = report.get("inventory_structurally_consistent")
    if type(consistent) is not bool or consistent != (verdict != "REFUSED"):
        raise ValueError("report_contradictory")
    if report.get("inventory_provenance") not in _PROVENANCE \
            or report.get("close_range_used") is not False:
        raise ValueError("report_malformed")
    lists = ("entries", "unknown_fds", "std_closed", "grants_missing")
    if verdict == "REFUSED":
        if type(report.get("reason")) is not str or any(k in report for k in lists):
            raise ValueError("report_contradictory")
        return report
    if "reason" in report or any(type(report.get(k)) is not list for k in lists):
        raise ValueError("report_malformed")
    entry_unknown = sorted(e["fd"] for e in report["entries"]
                           if e.get("status") != "authorized")
    if entry_unknown != sorted(report["unknown_fds"]):
        raise ValueError("report_contradictory")
    has_problem = bool(report["unknown_fds"] or report["std_closed"]
                       or report["grants_missing"])
    if has_problem != (verdict == "UNKNOWN_CAPABILITIES"):
        raise ValueError("report_contradictory")
    return report


def _report(verdict, /, *, provenance="none", **extra):
    if verdict not in _VERDICTS:
        raise ValueError("invalid_verdict")
    if _RESERVED & set(extra):
        raise ValueError("reserved_field")
    report = {**extra, "schema": SCHEMA, **INVARIANTS, "verdict": verdict,
              "bootstrap_trusted": False, "bootstrap_complete": False,
              "inventory_source": "/proc/self/fd + fcntl probe",
              "inventory_provenance": provenance,
              "close_range_used": False,
              "inventory_structurally_consistent": verdict != "REFUSED",
              "inventory_effectively_complete": False,
              "unobserved_capabilities_excluded": False,
              "limitations": list(LIMITATIONS), "not_verified": list(NOT_VERIFIED)}
    return check_boot_report(report)


def _diagnose(registry, collect):
    provenance = ("collected_in_process" if collect is collect_inventory
                  else "caller_supplied_unverified")
    try:
        return _evaluate(collect(), registry, _kcmp_same_ofd, provenance)
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
    with CapabilityRegistry() as registry:
        report = diagnose(registry)
    print(json.dumps(report, indent=2, sort_keys=True) if "--json" in argv
          else report["verdict"])
    return 2  # nunca 0: o diagnóstico não autoriza nada


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
