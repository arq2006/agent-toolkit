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
_INVENTORY_SOURCE = "/proc/self/fd + fcntl probe"
_MAX_PROBE = 1 << 20
# `target` só aparece num relatório em formato fechado E coerente com o `kind`;
# nada que o chamador escreva (caminhos, "pipe:/x", colchetes soltos) é reproduzido.
_GENERIC_TARGET = "<redacted-path>"
_ANON_TARGET = re.compile(
    r"anon_inode:(?:\[[A-Za-z0-9_-]{1,32}\]|[A-Za-z0-9_-]{1,32})\Z")
_TARGET_FORMATS = types.MappingProxyType({
    "fifo": re.compile(r"pipe:\[[0-9]{1,20}\]\Z"),
    "socket": re.compile(r"socket:\[[0-9]{1,20}\]\Z"),
    "chr_devnull": re.compile(r"/dev/null\Z"),
    "tty": re.compile(r"<tty>\Z"),
    "anon_inode": _ANON_TARGET,
})
_MISMATCH_ORDER = ("identity", "access", "opath", "flags", "cloexec", "ofd",
                   "ofd_unverifiable")
_CLASS_KEYS = frozenset(("status", "reason", "mismatch"))
# razão autorizada -> (kinds permitidos, cloexec, access, FDs permitidos)
_AUTHORIZED = types.MappingProxyType({
    "stdio_devnull": (("chr_devnull",), False, "rdwr", (0, 1, 2)),
    "supervisor_pipe_read": (("fifo",), True, "rdonly", None),
    "supervisor_pipe_write": (("fifo",), True, "wronly", None),
    "registry_anchor": (("chr_devnull", "fifo"), True, None, None),
})
_UNKNOWN_REASONS = ("grant_mismatch", "anchor_mismatch", "no_grant")
# Únicos motivos que um relatório REFUSED pode carregar.
_REFUSAL_REASONS = frozenset((
    "unsupported_platform", "multithreaded", "proc_mismatch", "probe_range_exceeded",
    "inventory_unavailable", "inventory_malformed", "inventory_unstable",
    "inventory_inconsistent", "inventory_contradictory", "inventory_target_invalid",
    "invalid_registry", "registry_closed", "invalid_grant",
    "unexpected_capability_kind", "evidence_insufficient"))
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
    "validar um relatório (forma e coerência) NÃO prova autenticidade nem proveniência: um relatório forjado e coerente passa",
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
_LIST_KEYS = ("entries", "unknown_fds", "std_closed", "grants_missing")
_REPORT_KEYS = frozenset(INVARIANTS) | frozenset((
    "schema", "verdict", "bootstrap_trusted", "bootstrap_complete",
    "inventory_source", "inventory_provenance", "close_range_used",
    "inventory_structurally_consistent", "inventory_effectively_complete",
    "unobserved_capabilities_excluded", "limitations", "not_verified"))


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
    __slots__ = ("fd", "anchor", "entry", "purpose", "inheritable", "used")

    def __init__(self, fd, anchor, entry, purpose, inheritable):
        self.fd, self.anchor, self.entry = fd, anchor, entry
        self.purpose, self.inheritable = purpose, inheritable
        self.used = False


def _require_platform():
    if sys.platform != "linux":
        raise BootRefused("unsupported_platform")


def _kind_of(st, fd, target):
    # anon_inode primeiro: o kernel dá a esses inodes um modo regular, então o
    # tipo do stat sozinho os classificaria como "regular".
    if _ANON_TARGET.match(target):
        return "anon_inode"
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
    return "other"


def _safe_target(target, kind):
    """Só devolve alvos no formato fechado do `kind`; caminhos de arquivo e
    qualquer outra coisa viram "<redacted-path>" (genérico, válido p/ qualquer kind)."""
    fmt = _TARGET_FORMATS.get(kind)
    if fmt is not None and fmt.match(target):
        return target
    if kind == "tty" and target.startswith(("/dev/pts/", "/dev/tty")):
        return "<tty>"
    return _GENERIC_TARGET


def _target_state(kind, target):
    """"ok" | "invalid" (formato desconhecido) | "contradictory" (formato válido
    de OUTRO kind)."""
    if target == _GENERIC_TARGET:
        return "ok"
    fmt = _TARGET_FORMATS.get(kind)
    if fmt is not None and fmt.match(target):
        return "ok"
    if any(f.match(target) for f in _TARGET_FORMATS.values()):
        return "contradictory"
    return "invalid"


def _describe_fd(fd):
    """Levanta OSError se o FD não existir mais (ex.: o FD da própria listagem)."""
    st = os.fstat(fd)
    target = os.readlink("/proc/self/fd/%d" % fd)
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    cloexec = bool(fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC)
    kind = _kind_of(st, fd, target)
    return {"fd": fd, "kind": kind, "dev": int(st.st_dev),
            "ino": int(st.st_ino), "cloexec": cloexec, "flags": int(flags),
            "access": _ACCESS.get(flags & os.O_ACCMODE, "other"),
            "opath": bool(flags & _O_PATH), "target": _safe_target(target, kind)}


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


def _release(owned, fd):
    """Fecha `fd` somente se `owned` ainda o possui, e o tira de `owned` ANTES de
    fechar: cada FD é fechado no máximo uma vez, nunca se tenta de novo, e um
    número já fechado (talvez reaproveitado por outro FD) não é fechado outra vez."""
    try:
        owned.remove(fd)
    except (KeyError, ValueError):
        return
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

    Posse de FDs (cada um fechado no máximo uma vez): durante uma fábrica, os FDs
    e âncoras recém-criados pertencem a uma lista local da chamada e saem dela
    antes de serem fechados; ao emitir o grant, a âncora passa a pertencer a
    `_owned` do registro e só `_revoke`/`close()` a fecham. `_issue` é
    transacional: se falhar, nenhum estado do registro muda e a âncora continua
    com a fábrica. Falha numa fábrica não deixa grant, recibo pendente nem âncora.

    Limite: isto elimina o caminho de concessão por declaração da interface
    operacional; não é fronteira de segurança contra código Python arbitrário
    no mesmo processo, que pode alterar qualquer objeto (A3, fora da garantia).
    """
    __slots__ = ("_grants", "_issued", "_pending", "_owned", "_closed")

    def __init__(self):
        self._grants = {}
        self._issued = set()    # ids dos Grants emitidos por ESTE registro
        self._pending = []      # recibos criados e ainda não emitidos
        self._owned = set()     # âncoras que o registro possui (uma por grant)
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
        outra coisa (inclusive um int: "registrar" um FD por declaração).

        Transacional: qualquer falha desfaz o que foi tocado e deixa o registro
        como estava. Nunca fecha a âncora do recibo: em caso de falha ela segue
        com a fábrica (que a fecha uma vez); em caso de sucesso passa ao registro."""
        if type(created) is not _Created or created.used \
                or not any(created is p for p in self._pending):
            raise BootRefused("declaration_refused")
        self._require_open()
        entry = created.entry
        grant = Grant(created.fd, entry["kind"], entry["dev"], entry["ino"],
                      entry["flags"], created.inheritable, created.purpose,
                      created.anchor)
        old = self._grants.get(created.fd)   # grant obsoleto no mesmo número
        added_issued = added_owned = False
        try:
            self._issued.add(id(grant))
            added_issued = True
            self._owned.add(created.anchor)
            added_owned = True
            self._grants[created.fd] = grant
        except BaseException:
            if added_owned:
                self._owned.discard(created.anchor)
            if added_issued:
                self._issued.discard(id(grant))
            raise
        created.used = True
        if old is not None:
            self._issued.discard(id(old))
            _release(self._owned, getattr(old, "anchor_fd", None))

    def _revoke(self, fd):
        grant = self._grants.pop(fd, None)
        if grant is not None:
            self._issued.discard(id(grant))
            _release(self._owned, getattr(grant, "anchor_fd", None))

    def _drop_pending(self, *receipts):
        self._pending = [p for p in self._pending
                         if not any(p is r for r in receipts)]

    def close(self):
        """Libera âncoras e invalida os grants. Idempotente."""
        self._closed = True
        while self._grants:
            self._revoke(next(iter(self._grants)))
        for fd in list(self._owned):
            _release(self._owned, fd)
        self._pending = []

    def place_devnull(self, target_fd):
        """Abre /dev/null NOVO (não duplica FD herdado) em 0, 1 ou 2, herdável.

        Confia que o /dev/null do namespace atual é o dispositivo 1:3 (verificado
        por rdev após a abertura); não protege contra quem controla /dev.
        Se o slot estava fechado e open() reutilizou exatamente esse número,
        o dup2(fd, fd) seria um no-op: as flags são ajustadas explicitamente.
        Falha fechado: se o estado efetivo não for o contratado, levanta
        BootRefused e nada é emitido; um slot que esta chamada abriu é devolvido
        fechado, e a âncora e o recibo criados aqui são desfeitos. Se a falha
        ocorrer DEPOIS de o dup2 ter substituído o objeto herdado, o slot
        permanece como /dev/null herdável, sem grant (a autoridade herdada
        anterior já foi descartada e não é restaurável).
        """
        self._require_open()
        if type(target_fd) is not int or target_fd not in (0, 1, 2):
            raise BootRefused("invalid_target")
        try:
            tmp = os.open("/dev/null", os.O_RDWR | os.O_CLOEXEC)
        except OSError:
            raise BootRefused("place_devnull_failed") from None
        owned = [tmp]        # FDs que ESTA chamada abriu e ainda possui
        anchor = receipt = None
        try:
            st = os.fstat(tmp)
            if not stat.S_ISCHR(st.st_mode) or st.st_rdev != _DEVNULL_RDEV:
                raise BootRefused("devnull_identity")
            if tmp == target_fd:
                # dup2(fd, fd) não altera flags: ajusta CLOEXEC explicitamente.
                os.set_inheritable(tmp, True)
            else:
                os.dup2(tmp, target_fd, inheritable=True)
                _release(owned, tmp)
            # Um grant anterior neste slot descreve um objeto já substituído.
            self._revoke(target_fd)
            state = _describe_fd(target_fd)
            if (state["kind"], state["cloexec"], state["access"], state["opath"]) \
                    != ("chr_devnull", False, "rdwr", False):
                raise BootRefused("place_devnull_state")
            # Âncora >= 3 para nunca ocupar um slot padrão fechado.
            anchor = fcntl.fcntl(target_fd, fcntl.F_DUPFD_CLOEXEC, 3)
            owned.append(anchor)
            receipt = _Created(target_fd, anchor, state, "stdio_devnull", True)
            self._pending.append(receipt)
            self._issue(receipt)
        except BaseException as e:
            self._drop_pending(receipt)
            for fd in list(owned):
                _release(owned, fd)    # tmp (se for o slot) e âncora, uma vez cada
            if isinstance(e, BootRefused):
                raise
            if isinstance(e, OSError):
                raise BootRefused("place_devnull_failed") from None
            raise
        # Emitido: a âncora é do registro e o slot é do chamador.
        owned.remove(anchor)
        if tmp in owned:
            owned.remove(tmp)
        self._drop_pending(receipt)
        return target_fd

    def make_pipe(self):
        """Pipe criado aqui, com CLOEXEC; devolve (leitura, escrita).

        Tudo ou nada: se qualquer etapa falhar, nenhum grant é emitido (um
        primeiro grant já emitido é revogado) e os dois FDs, as âncoras e os
        recibos pendentes são desfeitos, cada FD fechado uma única vez.
        """
        self._require_open()
        try:
            r, w = os.pipe2(os.O_CLOEXEC)
        except OSError:
            raise BootRefused("make_pipe_failed") from None
        owned = [r, w]
        receipts, committed = [], []
        try:
            for fd, purpose in ((r, "supervisor_pipe_read"), (w, "supervisor_pipe_write")):
                state = _describe_fd(fd)
                anchor = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)
                owned.append(anchor)
                receipt = _Created(fd, anchor, state, purpose, False)
                receipts.append(receipt)
                self._pending.append(receipt)
            for receipt in receipts:
                self._issue(receipt)
                committed.append(receipt)
                owned.remove(receipt.anchor)   # âncora agora é do registro
        except BaseException as e:
            for receipt in committed:
                self._revoke(receipt.fd)       # fecha a âncora do registro uma vez
            self._drop_pending(*receipts)
            for fd in list(owned):
                _release(owned, fd)
            if isinstance(e, (OSError, BootRefused)):
                raise BootRefused("make_pipe_failed") from None
            raise
        self._drop_pending(*receipts)
        return r, w


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


def _check_entry(entry):
    """Valida UMA entrada de FD (tipos, domínios e relações); levanta BootRefused.
    Compartilhada pelo inventário recebido e pela validação de relatórios."""
    if type(entry) is not dict or set(entry) != _ENTRY_KEYS:
        raise BootRefused("inventory_malformed")
    if any(type(entry[k]) is not int or entry[k] < 0
           for k in ("fd", "dev", "ino", "flags")):
        raise BootRefused("inventory_malformed")
    if any(type(entry[k]) is not bool for k in ("cloexec", "opath")):
        raise BootRefused("inventory_malformed")
    if type(entry["kind"]) is not str or entry["kind"] not in KINDS \
            or type(entry["access"]) is not str or type(entry["target"]) is not str:
        raise BootRefused("inventory_malformed")
    # Regra de recusa (não de reescrita): o alvo vira texto de relatório, então
    # só o formato fechado, coerente com o kind, passa; "pipe:/private" também não.
    state = _target_state(entry["kind"], entry["target"])
    if state == "invalid":
        raise BootRefused("inventory_target_invalid")
    if state == "contradictory":
        raise BootRefused("inventory_contradictory")
    # Campos derivados precisam concordar com os flags brutos.
    if entry["access"] != _ACCESS.get(entry["flags"] & os.O_ACCMODE, "other") \
            or entry["opath"] != bool(entry["flags"] & _O_PATH):
        raise BootRefused("inventory_contradictory")


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
        _check_entry(entry)
        if entry["fd"] <= previous:   # duplicata ou fora de ordem
            raise BootRefused("inventory_malformed")
        previous = entry["fd"]
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


def _check_classified(item):
    """Entrada de relatório: entrada de FD válida + status/reason/mismatch coerentes."""
    if type(item) is not dict or set(item) != _ENTRY_KEYS | _CLASS_KEYS:
        raise ValueError("report_malformed")
    try:
        _check_entry({k: item[k] for k in _ENTRY_KEYS})
    except BootRefused:
        raise ValueError("report_malformed") from None
    status, reason, mismatch = item["status"], item["reason"], item["mismatch"]
    if type(status) is not str or type(reason) is not str or type(mismatch) is not list \
            or status not in ("authorized", "unknown"):
        raise ValueError("report_malformed")
    if any(type(m) is not str or m not in _MISMATCH_ORDER for m in mismatch):
        raise ValueError("report_malformed")
    order = [_MISMATCH_ORDER.index(m) for m in mismatch]
    if order != sorted(set(order)):          # únicos e na ordem canônica
        raise ValueError("report_malformed")
    if status == "authorized":
        rule = _AUTHORIZED.get(reason)
        if rule is None or mismatch:
            raise ValueError("report_contradictory")
        kinds, cloexec, access, fds = rule
        if item["kind"] not in kinds or item["cloexec"] is not cloexec \
                or item["opath"] or (access is not None and item["access"] != access) \
                or (fds is not None and item["fd"] not in fds):
            raise ValueError("report_contradictory")
    else:
        if reason not in _UNKNOWN_REASONS \
                or (reason == "grant_mismatch" and not mismatch) \
                or (reason == "anchor_mismatch" and mismatch != ["identity"]) \
                or (reason == "no_grant" and mismatch):
            raise ValueError("report_contradictory")


def _fd_list(value):
    """Lista de FDs: int exato >= 0, estritamente crescente (ordenada e única)."""
    if type(value) is not list or any(type(v) is not int or v < 0 for v in value) \
            or value != sorted(set(value)):
        raise ValueError("report_malformed")
    return value


def check_boot_report(report):
    """Esquema estrito, tipos, entradas e coerência verdict/status/listas; levanta
    ValueError. Valida FORMA e COERÊNCIA interna: NÃO prova autenticidade nem
    proveniência. Um relatório forjado, mas internamente coerente, passa."""
    check_report(report)
    verdict = report.get("verdict")
    refused = verdict == "REFUSED"
    if type(verdict) is not str or verdict not in _VERDICTS:
        raise ValueError("report_malformed")
    expected = _REPORT_KEYS | ({"reason"} if refused else set(_LIST_KEYS))
    if set(report) != expected or report["schema"] != SCHEMA \
            or type(report["schema"]) is not str:
        raise ValueError("report_malformed")
    for key in ("bootstrap_trusted", "bootstrap_complete", "close_range_used",
                "inventory_effectively_complete", "unobserved_capabilities_excluded"):
        if report[key] is not False:
            raise ValueError("report_malformed")
    if report["inventory_source"] != _INVENTORY_SOURCE \
            or type(report["inventory_source"]) is not str \
            or report["limitations"] != list(LIMITATIONS) \
            or report["not_verified"] != list(NOT_VERIFIED):
        raise ValueError("report_malformed")
    consistent = report["inventory_structurally_consistent"]
    if type(consistent) is not bool or consistent == refused:
        raise ValueError("report_contradictory")
    provenance = report["inventory_provenance"]
    if type(provenance) is not str or provenance not in _PROVENANCE:
        raise ValueError("report_malformed")
    if refused:
        if provenance != "none":      # nada foi observado nem recebido
            raise ValueError("report_contradictory")
        reason = report["reason"]
        if type(reason) is not str or reason not in _REFUSAL_REASONS:
            raise ValueError("report_malformed")
        return report
    if provenance == "none":
        raise ValueError("report_contradictory")
    entries = report["entries"]
    if type(entries) is not list:
        raise ValueError("report_malformed")
    for item in entries:
        _check_classified(item)
    fds = [item["fd"] for item in entries]
    if fds != sorted(set(fds)):
        raise ValueError("report_malformed")
    unknown, std_closed, missing = (_fd_list(report[k]) for k in
                                    ("unknown_fds", "std_closed", "grants_missing"))
    if unknown != [i["fd"] for i in entries if i["status"] == "unknown"] \
            or std_closed != [fd for fd in (0, 1, 2) if fd not in fds] \
            or set(missing) & set(fds):
        raise ValueError("report_contradictory")
    has_problem = bool(unknown or std_closed or missing)
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
              "inventory_source": _INVENTORY_SOURCE,
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
        code = refused.code if refused.code in _REFUSAL_REASONS else "evidence_insufficient"
        return _report("REFUSED", reason=code)
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
