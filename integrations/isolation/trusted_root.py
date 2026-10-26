#!/usr/bin/env python3
"""Protótipo GH-F1.18/PR-B: identidade de uma raiz SINTÉTICA pelo kernel.

Abre um diretório sintético com openat2 (BENEATH, NO_SYMLINKS, NO_MAGICLINKS,
NO_XDEV) a partir de um FD âncora e observa a identidade do FD aberto com
fstat + statx(AT_EMPTY_PATH). Qualquer requisito mínimo não comprovado resulta
em recusa (RootRefused); nunca em sucesso implícito.

NÃO é autorização: identidade de raiz não equivale a concessão do proprietário,
autenticação, proteção contra ABA ou exclusão de escritores externos. Não
aceita caminho de projeto real: somente diretórios criados por
make_synthetic_fixture(). STRONG=UNAVAILABLE e readiness=BLOCKED permanecem.
"""
import ctypes
import dataclasses
import errno
import os
import platform
import shutil
import stat
import sys
import tempfile
import types

SYNTHETIC_PREFIX = "gh-f1-18-synthetic-"
MARKER_NAME = ".gh-f1-18-synthetic"
MARKER_CONTENT = b"SYNTHETIC-ROOT-GH-F1-18\n"

# Invariantes herdadas; nenhum resultado deste módulo as altera. A visão é
# somente leitura (protege contra atribuição acidental, não contra um processo
# Python comprometido, que está fora da garantia).
INVARIANTS = types.MappingProxyType({
    "strong": "UNAVAILABLE",
    "readiness": "BLOCKED",
    "agent_execution_authorized": False,
    "file_operations_authorized": False,
    "cloud_call_authorized": False,
    "data_transfer_authorized": False,
})
_NEVER_TRUE = ("bootstrap_trusted", "bootstrap_complete", "owner_authenticated",
               "owner_grant_implemented", "aba_protection_proven",
               "external_writers_excluded", "anchor_provenance_verified",
               "inventory_effectively_complete", "unobserved_capabilities_excluded")
CLEANUP_CODES = ("anchor_close", "root_close", "fixture_remove")
_ROOT_RESULTS = ("IDENTITY_OBSERVED_NOT_AUTHORIZED", "OBSERVED_WITH_CLEANUP_FAILURE",
                 "REFUSED")


def check_report(report):
    """Recusa (ValueError) um relatório cujas invariantes não sejam exatamente
    as constantes, com tipos exatos. Campos "nunca verdadeiros" só são exigidos
    quando presentes (não são adicionados artificialmente). Não é prova contra
    processo comprometido."""
    if type(report) is not dict:
        raise ValueError("report_not_dict")
    for key, value in INVARIANTS.items():
        if key not in report or type(report[key]) is not type(value) \
                or report[key] != value:
            raise ValueError("invariant_violated")
    for key in _NEVER_TRUE:
        if key in report and not (type(report[key]) is bool and report[key] is False):
            raise ValueError("invariant_violated")
    return report


def check_root_report(report):
    """Invariantes + coerência entre result, reason e cleanup_failures."""
    check_report(report)
    result = report.get("result")
    failures = report.get("cleanup_failures")
    if result not in _ROOT_RESULTS or type(failures) is not list \
            or any(f not in CLEANUP_CODES for f in failures) \
            or failures != sorted(set(failures)):
        raise ValueError("report_malformed")
    if (result == "REFUSED") != ("reason" in report) \
            or ("reason" in report and type(report["reason"]) is not str):
        raise ValueError("report_malformed")
    if result == "IDENTITY_OBSERVED_NOT_AUTHORIZED" and failures:
        raise ValueError("report_contradictory")      # limpeza falha ≠ sucesso integral
    if result == "OBSERVED_WITH_CLEANUP_FAILURE" and not failures:
        raise ValueError("report_contradictory")
    if result != "REFUSED" and report.get("synthetic_only") is not True:
        raise ValueError("report_malformed")
    return report


# UAPI Linux: x86_64 e arm64/aarch64; outras arquiteturas recusadas.
_NR_OPENAT2 = 437
_NR_STATX = {"x86_64": 332, "amd64": 332, "aarch64": 291, "arm64": 291}
_RESOLVE_NO_XDEV = 0x01
_RESOLVE_NO_MAGICLINKS = 0x02
_RESOLVE_NO_SYMLINKS = 0x04
_RESOLVE_BENEATH = 0x08
_RESOLVE_ALL = (_RESOLVE_NO_XDEV | _RESOLVE_NO_MAGICLINKS |
                _RESOLVE_NO_SYMLINKS | _RESOLVE_BENEATH)

_AT_EMPTY_PATH = 0x1000
STATX_TYPE = 0x1
STATX_INO = 0x100
STATX_MNT_ID = 0x1000
STATX_MNT_ID_UNIQUE = 0x4000
_REQUIRED_MASK = STATX_TYPE | STATX_INO  # não existe STATX_DEV
_STATX_SIZE = 256


class RootRefused(ValueError):
    """Recusa estável; str(e) é o código, sem caminhos do usuário."""

    @property
    def code(self):
        return str(self)


class _OpenHow(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64),
                ("mode", ctypes.c_uint64),
                ("resolve", ctypes.c_uint64)]


class _Statx(ctypes.Structure):
    _fields_ = [("stx_mask", ctypes.c_uint32),
                ("stx_blksize", ctypes.c_uint32),
                ("stx_attributes", ctypes.c_uint64),
                ("stx_nlink", ctypes.c_uint32),
                ("stx_uid", ctypes.c_uint32),
                ("stx_gid", ctypes.c_uint32),
                ("stx_mode", ctypes.c_uint16),
                ("_pad0", ctypes.c_uint16),
                ("stx_ino", ctypes.c_uint64),
                ("stx_size", ctypes.c_uint64),
                ("stx_blocks", ctypes.c_uint64),
                ("stx_attributes_mask", ctypes.c_uint64),
                ("_timestamps", ctypes.c_uint8 * 64),  # atime, btime, ctime, mtime
                ("stx_rdev_major", ctypes.c_uint32),
                ("stx_rdev_minor", ctypes.c_uint32),
                ("stx_dev_major", ctypes.c_uint32),
                ("stx_dev_minor", ctypes.c_uint32),
                ("stx_mnt_id", ctypes.c_uint64),
                ("_rest", ctypes.c_uint8 * 104)]


assert ctypes.sizeof(_Statx) == _STATX_SIZE


@dataclasses.dataclass(frozen=True)
class RootIdentity:
    """Metadados observados. Só servem para COMPARAR com outra observação."""
    dev: int
    ino: int
    mnt_id: int
    mnt_id_variant: str  # "unique" | "legacy"; valores de variantes não se comparam
    mnt_ns: object       # link de /proc/self/ns/mnt (contexto) ou None
    statx_mask: int


def _require_platform():
    if sys.platform != "linux" or platform.machine().lower() not in _NR_STATX:
        raise RootRefused("unsupported_platform")


def _libc_syscall():
    try:
        call = ctypes.CDLL(None, use_errno=True).syscall
    except (AttributeError, OSError):
        raise RootRefused("syscall_unavailable") from None
    call.restype = ctypes.c_long
    return call


def _sys_openat2(dirfd, name, flags):
    """Chamada direta ao kernel; devolve fd ou levanta OSError com errno."""
    how = _OpenHow(int(flags), 0, _RESOLVE_ALL)
    call = _libc_syscall()
    result = call(ctypes.c_long(_NR_OPENAT2), ctypes.c_int(dirfd),
                  ctypes.c_char_p(name), ctypes.byref(how),
                  ctypes.c_size_t(ctypes.sizeof(how)))
    if result < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return int(result)


def _sys_statx(fd, mask):
    """statx(fd, "", AT_EMPTY_PATH, mask); devolve a estrutura ou OSError."""
    stx = _Statx()
    call = _libc_syscall()
    result = call(ctypes.c_long(_NR_STATX[platform.machine().lower()]),
                  ctypes.c_int(fd), ctypes.c_char_p(b""),
                  ctypes.c_int(_AT_EMPTY_PATH), ctypes.c_uint(mask),
                  ctypes.byref(stx))
    if result < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return stx


_OPEN_ERRORS = {
    errno.EXDEV: "xdev_refused",
    errno.ELOOP: "symlink_refused",
    errno.ENOENT: "root_missing",
    errno.ENOTDIR: "not_directory",
    errno.EBADF: "invalid_anchor",
    errno.EACCES: "access_denied",
    errno.EAGAIN: "resolution_race",   # fail-closed: sem retry, flags inalteradas
    errno.ENOSYS: "syscall_unavailable",
    errno.EPERM: "syscall_unavailable",
    errno.EINVAL: "syscall_unavailable",
}


def _check_name(name):
    if type(name) is not str or name in ("", ".", ".."):
        raise RootRefused("invalid_name")
    if "/" in name or "\x00" in name:
        raise RootRefused("invalid_name")
    try:
        return name.encode("utf-8", "strict")
    except UnicodeError:
        raise RootRefused("invalid_name") from None


def _check_anchor(anchor_fd):
    if type(anchor_fd) is not int or anchor_fd < 0:
        raise RootRefused("invalid_anchor")
    try:
        if not stat.S_ISDIR(os.fstat(anchor_fd).st_mode):
            raise RootRefused("invalid_anchor")
    except OSError:
        raise RootRefused("invalid_anchor") from None


def _open_dir(anchor_fd, name):
    """Abre `name` (componente único) sob anchor_fd; recusa symlink e mount.

    NO_XDEV é política de recusa: um mountpoint legítimo também resulta em
    xdev_refused e não é relaxado.
    """
    _require_platform()
    _check_anchor(anchor_fd)
    encoded = _check_name(name)
    try:
        return _sys_openat2(anchor_fd, encoded,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as e:
        raise RootRefused(_OPEN_ERRORS.get(e.errno, "open_failed")) from None


def _fstat(fd):
    try:
        return os.fstat(fd)
    except OSError:
        raise RootRefused("invalid_fd") from None


def _mnt_ns():
    try:
        return os.readlink("/proc/self/ns/mnt")
    except OSError:
        return None


def _statx_or_refuse(fd, mask):
    try:
        return _sys_statx(fd, mask)
    except OSError as e:
        if e.errno == errno.EBADF:
            raise RootRefused("invalid_fd") from None
        raise RootRefused("syscall_unavailable") from None


def observe(fd):
    """fstat -> statx -> fstat sobre o FD já aberto; recusa se incompleto.

    Os campos de um statx e as três chamadas NÃO são atômicos: a verificação
    detecta apenas divergência visível, não elimina corridas.
    """
    _require_platform()
    if type(fd) is not int or fd < 0:
        raise RootRefused("invalid_fd")
    pre = _fstat(fd)
    if not stat.S_ISDIR(pre.st_mode):
        raise RootRefused("not_directory")
    stx = _statx_or_refuse(fd, STATX_TYPE | STATX_INO | STATX_MNT_ID_UNIQUE)
    variant = None
    if stx.stx_mask & STATX_MNT_ID_UNIQUE:
        variant = "unique"
    else:
        stx = _statx_or_refuse(fd, STATX_TYPE | STATX_INO | STATX_MNT_ID)
        if stx.stx_mask & STATX_MNT_ID:
            variant = "legacy"
    if (stx.stx_mask & _REQUIRED_MASK) != _REQUIRED_MASK:
        raise RootRefused("identity_incomplete")
    if variant is None:
        raise RootRefused("identity_incomplete")  # sem identificador de montagem
    if not stat.S_ISDIR(stx.stx_mode):
        raise RootRefused("not_directory")
    post = _fstat(fd)
    if (pre.st_dev, pre.st_ino) != (post.st_dev, post.st_ino):
        raise RootRefused("unstable_observation")
    if stx.stx_ino != pre.st_ino:
        raise RootRefused("ino_mismatch")
    # Sem bit de máscara para dev: compara com fstat e recusa se divergir.
    if os.makedev(stx.stx_dev_major, stx.stx_dev_minor) != pre.st_dev:
        raise RootRefused("dev_mismatch")
    return RootIdentity(dev=int(pre.st_dev), ino=int(pre.st_ino),
                        mnt_id=int(stx.stx_mnt_id), mnt_id_variant=variant,
                        mnt_ns=_mnt_ns(), statx_mask=int(stx.stx_mask))


def compare(recorded, current):
    """Igualdade de metadados; divergência ou não-comparabilidade recusa."""
    if not isinstance(recorded, RootIdentity) or not isinstance(current, RootIdentity):
        raise RootRefused("invalid_identity")
    if recorded.mnt_id_variant != current.mnt_id_variant:
        raise RootRefused("variant_not_comparable")
    if recorded.mnt_ns is None or current.mnt_ns is None:
        raise RootRefused("mount_namespace_unknown")
    if recorded.mnt_ns != current.mnt_ns:
        raise RootRefused("mount_namespace_changed")
    if (recorded.dev, recorded.ino, recorded.mnt_id) != \
            (current.dev, current.ino, current.mnt_id):
        raise RootRefused("identity_diverged")


class OpenedRoot:
    """FD de raiz sintética + identidade observada. Não é uma concessão."""

    def __init__(self, fd, identity):
        self.fd = fd
        self.identity = identity

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            finally:
                self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def revalidate_fd(self):
        """Reobserva o FD. Um FD obsoleto (pasta renomeada) AINDA passa aqui:
        só reopen_and_compare() enxerga o nome atual. Diretório removido recusa."""
        if self.fd is None:
            raise RootRefused("invalid_fd")
        if _fstat(self.fd).st_nlink == 0:
            raise RootRefused("root_unlinked")
        compare(self.identity, observe(self.fd))

    def reopen_and_compare(self, anchor_fd, name):
        """Reabre pelo nome sob a âncora e compara com a identidade registrada."""
        fresh = _open_dir(anchor_fd, name)
        try:
            compare(self.identity, observe(fresh))
        finally:
            os.close(fresh)

    def describe(self):
        ident = dataclasses.asdict(self.identity)
        return check_report({"schema": "trusted-root-diagnostic/1", **INVARIANTS,
                "identity": ident,
                "identity_scope": "comparison_only",
                "synthetic_only": True,
                "owner_grant_implemented": False,
                "owner_authenticated": False,
                "aba_protection_proven": False,
                "external_writers_excluded": False,
                "anchor_provenance_verified": False})


def _verify_marker(root_fd):
    try:
        fd = _sys_openat2(root_fd, MARKER_NAME.encode(),
                          os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    except OSError:
        raise RootRefused("not_synthetic") from None
    try:
        if not stat.S_ISREG(_fstat(fd).st_mode):
            raise RootRefused("not_synthetic")
        if os.read(fd, len(MARKER_CONTENT) + 1) != MARKER_CONTENT:
            raise RootRefused("not_synthetic")
    except OSError:
        raise RootRefused("not_synthetic") from None
    finally:
        os.close(fd)


def open_synthetic_root(anchor_fd, name):
    """Abre e identifica uma raiz sintética sob anchor_fd.

    O nome deve começar por SYNTHETIC_PREFIX e a pasta conter o marcador:
    guardas contra uso acidental com caminhos reais, não prova de origem.
    """
    _check_name(name)
    if not name.startswith(SYNTHETIC_PREFIX):
        raise RootRefused("not_synthetic")
    fd = _open_dir(anchor_fd, name)
    try:
        _verify_marker(fd)
        return OpenedRoot(fd, observe(fd))
    except BaseException:
        os.close(fd)
        raise


class FixtureSetupError(Exception):
    """Criação parcial da fixture falhou; `reason` e `cleanup_failures` são
    códigos sanitizados (sem caminhos)."""

    def __init__(self, reason, cleanup_failures):
        super().__init__(reason)
        self.reason = reason
        self.cleanup_failures = list(cleanup_failures)


def _remove_fixture(parent):
    """Remove SOMENTE uma fixture criada por make_synthetic_fixture neste
    processo (nome, diretório temporário e não-symlink conferidos). Devolve a
    lista de códigos de falha; vazia só se o diretório realmente sumiu."""
    safe = (isinstance(parent, str)
            and os.path.basename(parent).startswith("gh-f1-18-fixture-")
            and os.path.dirname(parent) == os.path.realpath(tempfile.gettempdir())
            and not os.path.islink(parent))
    if safe:
        try:
            shutil.rmtree(parent)
        except OSError:
            pass
    return ["fixture_remove"] if (not safe or os.path.lexists(parent)) else []


def make_synthetic_fixture():
    """Cria <tmp>/gh-f1-18-fixture-XXXX/gh-f1-18-synthetic-root com marcador.

    Devolve (diretório_pai, nome). Se a criação falhar depois do mkdtemp, a
    fixture parcial é removida e a falha (e a de limpeza, se houver) sobe como
    FixtureSetupError. O chamador remove o pai com _remove_fixture.
    """
    parent = os.path.realpath(tempfile.mkdtemp(prefix="gh-f1-18-fixture-"))
    name = SYNTHETIC_PREFIX + "root"
    root = os.path.join(parent, name)
    try:
        os.mkdir(root, 0o700)
        fd = os.open(os.path.join(root, MARKER_NAME),
                     os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600)
        try:
            if os.write(fd, MARKER_CONTENT) != len(MARKER_CONTENT):
                raise OSError(errno.EIO, "short write")
        finally:
            os.close(fd)
    except Exception as e:
        raise FixtureSetupError(_infra_code(e), _remove_fixture(parent)) from None
    return parent, name


def open_anchor(parent):
    """Abre a âncora sintética (sem seguir symlink final)."""
    return os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def _infra_code(exc):
    if isinstance(exc, RootRefused):
        return exc.code
    if isinstance(exc, OSError):
        return "infrastructure_" + errno.errorcode.get(exc.errno, "error")
    return "unexpected_failure"


def _refused_report(reason, cleanup_failures=()):
    return check_root_report({
        "schema": "trusted-root-diagnostic/1", **INVARIANTS,
        "result": "REFUSED", "reason": reason, "synthetic_only": True,
        "cleanup_failures": sorted(set(cleanup_failures))})


def _run_synthetic():
    """Cria, abre, descreve e limpa a fixture. Nunca levanta: qualquer falha vira
    relatório sanitizado (só códigos, sem caminhos nem tracebacks). Falha de
    limpeza nunca aparece como sucesso integral."""
    failures = set()
    report = None
    parent = anchor = root = None
    try:
        parent, name = make_synthetic_fixture()
        anchor = open_anchor(parent)
        root = open_synthetic_root(anchor, name)
        report = root.describe()
        report["result"] = "IDENTITY_OBSERVED_NOT_AUTHORIZED"
    except FixtureSetupError as setup:
        report = _refused_report(setup.reason)
        failures.update(setup.cleanup_failures)
    except Exception as e:
        report = _refused_report(_infra_code(e))
    if root is not None:
        try:
            root.close()
        except OSError:
            failures.add("root_close")
    if anchor is not None:
        try:
            os.close(anchor)
        except OSError:
            failures.add("anchor_close")
    if parent is not None:
        failures.update(_remove_fixture(parent))
    report = dict(report)
    if failures and report["result"] != "REFUSED":
        report["result"] = "OBSERVED_WITH_CLEANUP_FAILURE"
    report["cleanup_failures"] = sorted(failures)
    try:
        return check_root_report(report)
    except ValueError:      # nunca devolver relatório incoerente
        return _refused_report("report_invalid", failures)


def main(argv):
    import json
    if list(argv) not in (["--synthetic-only"], ["--synthetic-only", "--json"]):
        print("uso: trusted_root.py --synthetic-only [--json]", file=sys.stderr)
        return 64
    report = _run_synthetic()
    if "--json" in argv:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        suffix = ("; cleanup_failures=" + ",".join(report["cleanup_failures"])
                  if report["cleanup_failures"] else "")
        print(report["result"] + (":" + report["reason"] if "reason" in report else "")
              + suffix)
    return 2  # nunca 0: o diagnóstico não autoriza nada


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
