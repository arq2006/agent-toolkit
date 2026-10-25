#!/usr/bin/env python3
"""Experimento opt-in Linux openat2: nunca uma ferramenta de agente.

Resolução de caminhos pelo kernel com RESOLVE_BENEATH, NO_XDEV,
NO_MAGICLINKS e NO_SYMLINKS, em um FD de raiz previamente aprovado.
Sem fallback para open()/realpath(), shell, rede ou escrita.
NÃO estabelece proveniência do root_fd e NÃO substitui pathguard,
SRT, revisão humana ou gates STRONG.
"""
import ctypes
import errno
import os
import platform
import stat
import sys

import pathguard

# UAPI Linux: x86_64 e arm64/aarch64; outras arquiteturas recusadas.
_NR_OPENAT2 = 437
_RESOLVE_NO_XDEV = 0x01
_RESOLVE_NO_MAGICLINKS = 0x02
_RESOLVE_NO_SYMLINKS = 0x04
_RESOLVE_BENEATH = 0x08
_REQUIRED_RESOLVE = (_RESOLVE_NO_XDEV | _RESOLVE_NO_MAGICLINKS |
                     _RESOLVE_NO_SYMLINKS | _RESOLVE_BENEATH)
_ALLOWED_ARCH = ("x86_64", "amd64", "aarch64", "arm64")
MAX_READ = 65536
MAX_LIST = 1024


class Openat2Denied(ValueError):
    """Recusa estável, sem dados lidos ou caminhos do usuário na resposta."""


class _OpenHow(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64),
                ("mode", ctypes.c_uint64),
                ("resolve", ctypes.c_uint64)]


def _require_platform():
    if sys.platform != "linux" or platform.machine().lower() not in _ALLOWED_ARCH:
        raise Openat2Denied("unsupported_platform")
    if not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")):
        raise Openat2Denied("unsupported_platform")


def _root_stat(root_fd):
    if type(root_fd) is not int or root_fd < 0:
        raise Openat2Denied("invalid_root")
    try:
        st = os.fstat(root_fd)
    except OSError:
        raise Openat2Denied("invalid_root") from None
    if not stat.S_ISDIR(st.st_mode):
        raise Openat2Denied("invalid_root")
    # O responsável por abrir root_fd deve comprovar origem via pathguard.open_root
    # e config explícita. Este módulo não consegue deduzi-la de um FD genérico.
    return st


def _relative(rel):
    if type(rel) is not str:
        raise Openat2Denied("invalid_path")
    try:
        pathguard.split_relpath(rel)
        encoded = rel.encode("utf-8", "strict")
    except (pathguard.PathGuardError, UnicodeError):
        raise Openat2Denied("invalid_path") from None
    if not encoded:
        raise Openat2Denied("invalid_path")
    return encoded


def _sys_openat2(root_fd, path, flags):
    """Chamada direta ao kernel; ausência/bloqueio de syscall recusa SEM fallback."""
    how = _OpenHow(int(flags), 0, _REQUIRED_RESOLVE)
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        call = libc.syscall
        call.restype = ctypes.c_long
        # syscall() é variádica; fornecemos tipos para TODOS argumentos.
        result = call(ctypes.c_long(_NR_OPENAT2), ctypes.c_int(root_fd),
                      ctypes.c_char_p(path), ctypes.byref(how),
                      ctypes.c_size_t(ctypes.sizeof(how)))
    except (AttributeError, OSError, TypeError, ValueError):
        raise Openat2Denied("syscall_unavailable") from None
    if result < 0:
        error = ctypes.get_errno()
        if error in (errno.ENOSYS, errno.EPERM, errno.EINVAL):
            raise Openat2Denied("syscall_unavailable") from None
        raise Openat2Denied("path_denied") from None
    return int(result)


def _open(root_fd, rel, flags):
    _require_platform()
    _root_stat(root_fd)
    path = _relative(rel)
    return _sys_openat2(root_fd, path, flags | os.O_CLOEXEC | os.O_NOFOLLOW)


def read_bytes(root_fd, rel, max_bytes=MAX_READ):
    """Lê só arquivo regular, link único e até max_bytes, com resolução atômica."""
    if type(max_bytes) is not int or not (1 <= max_bytes <= MAX_READ):
        raise Openat2Denied("invalid_limit")
    root = _root_stat(root_fd)
    flags = os.O_RDONLY | os.O_NONBLOCK
    fd = _open(root_fd, rel, flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_dev != root.st_dev:
            raise Openat2Denied("unsafe_file")
        if st.st_size > max_bytes:
            raise Openat2Denied("too_large")
        # Uma leitura regular pode retornar menos bytes que o solicitado sem
        # ter chegado ao EOF. Não tratar short read como conteúdo completo.
        # Ler no máximo max_bytes + 1 bytes para detectar crescimento do arquivo
        # após fstat, sem materializar uma resposta ilimitada.
        chunks = []
        total = 0
        while True:
            remaining = max_bytes + 1 - total
            if remaining <= 0:
                raise Openat2Denied("too_large")
            chunk = os.read(fd, remaining)
            if not chunk:
                return b"".join(chunks)
            total += len(chunk)
            if total > max_bytes:
                raise Openat2Denied("too_large")
            chunks.append(chunk)
    except OSError:
        raise Openat2Denied("filesystem_error") from None
    finally:
        os.close(fd)


def list_dir(root_fd, rel=None, max_entries=MAX_LIST):
    """Lista uma pasta sob root_fd sem seguir symlinks nem cruzar mounts."""
    if type(max_entries) is not int or not (1 <= max_entries <= MAX_LIST):
        raise Openat2Denied("invalid_limit")
    root = _root_stat(root_fd)
    if rel is None:
        _require_platform()
        try:
            fd = os.dup(root_fd)
        except OSError:
            raise Openat2Denied("invalid_root") from None
    else:
        fd = _open(root_fd, rel, os.O_RDONLY | os.O_DIRECTORY)
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode) or st.st_dev != root.st_dev:
            raise Openat2Denied("unsafe_directory")
        names = []
        with os.scandir(fd) as entries:
            for item in entries:
                if len(names) >= max_entries:
                    raise Openat2Denied("too_many_entries")
                # Recusa nomes que o JSON/UTF-8 estrito não consegue transportar.
                try:
                    item.name.encode("utf-8", "strict")
                except UnicodeError:
                    raise Openat2Denied("invalid_entry") from None
                names.append(item.name)
        return sorted(names)
    except OSError:
        raise Openat2Denied("filesystem_error") from None
    finally:
        os.close(fd)


def read_text(root_fd, rel, max_bytes=MAX_READ):
    try:
        return read_bytes(root_fd, rel, max_bytes).decode("utf-8", "strict")
    except UnicodeDecodeError:
        raise Openat2Denied("invalid_encoding") from None
