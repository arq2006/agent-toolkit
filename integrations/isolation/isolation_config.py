#!/usr/bin/env python3
"""Carregador estrito da configuração do isolamento (GH-F1.8, ADR-011). Proposta; não isola nada.

Python 3.11+ (tomllib, biblioteca padrão). A pasta autorizada é escolhida pelo usuário no arquivo
de configuração, indicado explicitamente; este módulo não procura configuração, não lê variáveis
de ambiente e não toca credenciais. Arquivo ausente, ilegível ou inválido recusa (ConfigError).
"""
import os
import re
import stat
import tomllib
from dataclasses import dataclass

import pathguard

MAX_CONFIG_BYTES = 65_536
AUTH_MODES = ("none", "claude-ai-outside-boundary")
NETWORK_MODES = ("deny", "allowlist")
_HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")


class ConfigError(Exception):
    """Configuração ausente ou inválida: nada deve iniciar."""


@dataclass(frozen=True)
class Config:
    authorized_dir: str
    auth_mode: str
    network_mode: str
    network_allow: tuple


def _table(d, name, allowed, required):
    t = d.get(name)
    if not isinstance(t, dict):
        raise ConfigError(f"seção [{name}] ausente ou inválida")
    extra = set(t) - set(allowed)
    if extra:
        raise ConfigError(f"[{name}]: chaves desconhecidas: {sorted(extra)}")
    missing = [k for k in required if k not in t]
    if missing:
        raise ConfigError(f"[{name}]: chaves obrigatórias ausentes: {missing}")
    return t


def _check_authorized_dir(value):
    """Mesma validação do pathguard.open_root (inclui home da conta pelo banco de contas,
    nunca pela variável HOME). Abre e fecha a pasta só para provar que existe e é segura."""
    if not isinstance(value, str) or not value:
        raise ConfigError("authorized.dir deve ser texto não vazio")
    try:
        os.close(pathguard.open_root(value))
    except pathguard.PathGuardError as e:
        raise ConfigError(f"authorized.dir recusado: {e}") from None
    return value


def parse(text):
    try:
        return _parse(text)
    except ConfigError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError, AttributeError, KeyError):
        raise ConfigError("configuração inválida (erro inesperado de validação)") from None


def _parse(text):
    if len(text.encode("utf-8", "replace")) > MAX_CONFIG_BYTES:
        raise ConfigError("configuração grande demais")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"TOML inválido: {e}") from None
    extra = set(data) - {"version", "authorized", "auth", "network"}
    if extra:
        raise ConfigError(f"chaves desconhecidas: {sorted(extra)}")
    if data.get("version") != 1 or isinstance(data.get("version"), bool):
        raise ConfigError("version deve ser 1")
    a = _table(data, "authorized", ("dir",), ("dir",))
    au = _table(data, "auth", ("mode",), ("mode",))
    n = _table(data, "network", ("mode", "allow"), ("mode",))
    adir = _check_authorized_dir(a["dir"])
    if au["mode"] not in AUTH_MODES:
        raise ConfigError(f"auth.mode deve ser um de {AUTH_MODES}")
    if n["mode"] not in NETWORK_MODES:
        raise ConfigError(f"network.mode deve ser um de {NETWORK_MODES}")
    if n["mode"] == "deny":
        if "allow" in n:
            raise ConfigError("network.allow é incompatível com mode = \"deny\" (qualquer valor)")
        allow = []
    else:
        if "allow" not in n:
            raise ConfigError("network.allow é obrigatório com mode = \"allowlist\"")
        allow = n["allow"]
        if not isinstance(allow, list) or not allow or len(allow) > 64:
            raise ConfigError("network.allow deve ser lista não vazia (até 64 hosts)")
        for h in allow:
            if not isinstance(h, str) or not _HOST.match(h):
                raise ConfigError("network.allow: host inválido (sem curinga, esquema, porta ou IP)")
            if re.fullmatch(r"[0-9.]+", h):
                raise ConfigError("network.allow: IPs não são aceitos")
        if len(set(allow)) != len(allow):
            raise ConfigError("network.allow: hosts duplicados")
    return Config(adir, au["mode"], n["mode"], tuple(allow))


def load(path):
    """Lê a configuração do caminho EXPLÍCITO informado pelo usuário. Abertura não bloqueante
    com O_NOFOLLOW e fstat: só arquivo regular; FIFO/dispositivo/diretório são recusados sem
    bloquear. Plataforma sem esses recursos recusa."""
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ConfigError("caminho da configuração ausente")
    if not hasattr(os, "O_NONBLOCK") or not hasattr(os, "O_NOFOLLOW"):
        raise ConfigError("plataforma sem O_NONBLOCK/O_NOFOLLOW: recusado")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    except (OSError, ValueError) as e:
        raise ConfigError(f"configuração ausente ou ilegível: {getattr(e, 'strerror', None) or e}") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ConfigError("configuração não é arquivo regular")
        if st.st_size > MAX_CONFIG_BYTES:
            raise ConfigError("configuração grande demais")
        raw = os.read(fd, MAX_CONFIG_BYTES + 1)
    except OSError as e:
        raise ConfigError(f"falha ao ler a configuração: {e.strerror}") from None
    finally:
        os.close(fd)
    if len(raw) > MAX_CONFIG_BYTES:
        raise ConfigError("configuração grande demais")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigError("configuração não é UTF-8") from None
    return parse(text)
