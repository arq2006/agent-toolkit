#!/usr/bin/env python3
"""Launcher restritivo do srt (GH-F1.8, ADR-011, PR3). Não é uma API de execução de comandos.

Python 3.11+, só biblioteca padrão. O srt e o bubblewrap são dependências externas apenas
DETECTADAS; nada é instalado. Versão do srt suportada: exatamente SUPPORTED_SRT_VERSION (a dos
spikes históricos); qualquer outra é recusada, sem presumir compatibilidade.

O que este módulo executa: somente os canários internos (PROBE_SRC + operações fechadas em
`build_ops`) sobre um `Fixture` sintético descartável. Não há entrada de comando, argv ou script
vindos de fora, de agentes ou de IA. Nenhum uso de shell. Todo erro recusa (LauncherError); não existe
caminho que execute sem o srt ou sem `--settings`. Rede: apenas `deny` (allowlist é recusada até
haver validação específica). O resultado de um canário NÃO autoriza executar agentes.
"""
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field

import pathguard

SUPPORTED_SRT_VERSION = "0.0.81"
MIN_BWRAP = (0, 8, 0)         # srt documenta --disable-userns a partir da 0.8.0
VALIDATED_BWRAP = "0.12.0"    # única versão exercitada nos spikes
DEFAULT_TIMEOUT = 60
MAX_OUTPUT = 65_536
INTERPRETER = "/usr/bin/python3"

# Leituras mínimas do runtime dentro do sandbox (tudo o mais é negado por denyRead "/").
# Cada entrada tem justificativa; a necessidade é verificada pelo canário positivo do doctor.
RUNTIME_READ = (
    ("/usr", "interpretador, bash, bibliotecas compartilhadas e stdlib (distros usr-merge)"),
    ("/etc/ld.so.cache", "cache do carregador dinâmico (libc/libpython)"),
)
# Só entram se existirem como diretórios reais (em usr-merge são symlinks para /usr).
RUNTIME_READ_NON_USRMERGE = (
    ("/lib", "bibliotecas em distros sem usr-merge"),
    ("/lib64", "carregador dinâmico em distros sem usr-merge"),
    ("/bin", "bash em distros sem usr-merge"),
    ("/sbin", "binários em distros sem usr-merge"),
)

# Ambiente do processo isolado: construído do zero (lista fechada), nunca herdado.
ENV_ALLOWED = ("PATH", "HOME", "LANG", "LC_ALL", "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE", "TMPDIR")


class LauncherError(Exception):
    """Falha ao preparar ou executar: nada deve prosseguir (fail-closed)."""


class LauncherRefused(LauncherError):
    """Política recusa a execução (ex.: allowlist de rede ainda não validada)."""


@dataclass(frozen=True)
class DepInfo:
    name: str
    path: str = ""
    version: str = ""
    ok: bool = False
    reason: str = ""


@dataclass(frozen=True)
class Dependencies:
    items: dict

    @property
    def all_ok(self):
        return all(d.ok for d in self.items.values())

    def get(self, name):
        return self.items[name]


def _plain_env(extra_path_dirs=()):
    dirs = []
    for d in (*extra_path_dirs, "/usr/local/bin", "/usr/bin", "/bin"):
        if d and d not in dirs:
            dirs.append(d)
    return {"PATH": ":".join(dirs), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _version_run(path, args, env):
    try:
        r = subprocess.run([path, *args], env=env, stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=15, check=False, close_fds=True)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"falha ao executar: {type(e).__name__}"
    if r.returncode != 0:
        return None, f"código de saída {r.returncode}"
    return (r.stdout or b"").decode("utf-8", "replace").strip(), ""


def _find(name):
    p = shutil.which(name)
    if not p:
        return ""
    p = os.path.realpath(p)
    if not (os.path.isfile(p) and os.access(p, os.X_OK)):
        return ""
    return p


def detect_dependencies():
    """Detecta (sem instalar) srt, node, bubblewrap, socat e ripgrep. Versão do srt exata; do
    bubblewrap, mínima. Qualquer item ausente ou incompatível fica ok=False com o motivo."""
    found = {n: _find(n) for n in ("srt", "node", "bwrap", "socat", "rg")}
    env = _plain_env({os.path.dirname(p) for p in found.values() if p})
    out = {}
    for name in ("node", "socat", "rg"):
        p = found[name]
        out[name] = DepInfo(name, p, "", bool(p), "" if p else "não encontrado no PATH")
    p = found["srt"]
    if not p:
        out["srt"] = DepInfo("srt", "", "", False, "não encontrado no PATH")
    elif not found["node"]:
        out["srt"] = DepInfo("srt", p, "", False, "node ausente (necessário para executar o srt)")
    else:
        v, err = _version_run(p, ["--version"], env)
        if v is None:
            out["srt"] = DepInfo("srt", p, "", False, f"--version falhou ({err})")
        elif v != SUPPORTED_SRT_VERSION:
            out["srt"] = DepInfo("srt", p, v[:40], False,
                                 f"versão incompatível: suportada exatamente {SUPPORTED_SRT_VERSION}")
        else:
            out["srt"] = DepInfo("srt", p, v, True)
    p = found["bwrap"]
    if not p:
        out["bwrap"] = DepInfo("bwrap", "", "", False, "não encontrado no PATH")
    else:
        v, err = _version_run(p, ["--version"], env)
        m = re.fullmatch(r"bubblewrap (\d+)\.(\d+)\.(\d+)", v or "")
        if not m:
            out["bwrap"] = DepInfo("bwrap", p, (v or "")[:40], False, f"versão não reconhecida {err}".strip())
        elif tuple(int(x) for x in m.groups()) < MIN_BWRAP:
            out["bwrap"] = DepInfo("bwrap", p, ".".join(m.groups()), False,
                                   f"versão abaixo do mínimo {'.'.join(map(str, MIN_BWRAP))}")
        else:
            ver = ".".join(m.groups())
            note = "" if ver == VALIDATED_BWRAP else f"aceita, mas só {VALIDATED_BWRAP} foi exercitada"
            out["bwrap"] = DepInfo("bwrap", p, ver, True, note)
    return Dependencies(out)


def runtime_read_paths():
    """Lista mínima de leituras do runtime; recusa se o interpretador fixo estiver fora de /usr."""
    if not os.path.isfile(INTERPRETER) or not os.access(INTERPRETER, os.X_OK):
        raise LauncherError(f"interpretador {INTERPRETER} ausente: runtime mínimo indisponível")
    real = os.path.realpath(INTERPRETER)
    if not (real == "/usr" or real.startswith("/usr/")):
        raise LauncherError("interpretador fora de /usr: fora do conjunto mínimo de leitura")
    paths = [p for p, _ in RUNTIME_READ if os.path.exists(p)]
    if "/usr" not in paths:
        raise LauncherError("/usr ausente")
    for p, _ in RUNTIME_READ_NON_USRMERGE:
        if os.path.isdir(p) and not os.path.islink(p):
            paths.append(p)
    return paths


def build_settings(config, runtime_reads):
    """Política restritiva do srt (formato 0.0.81): leitura negada em '/', exceções mínimas, escrita só
    na pasta autorizada, rede negada. Recusa rede diferente de `deny`."""
    if config.network_mode != "deny":
        raise LauncherRefused("rede em allowlist não é liberada nesta etapa (PR3): use network.mode = \"deny\"")
    adir = config.authorized_dir
    pathguard.check_authorized_path(adir)
    settings = {
        "network": {"allowedDomains": [], "deniedDomains": [], "allowLocalBinding": False,
                    "allowAllUnixSockets": False},
        "filesystem": {"denyRead": ["/"], "allowRead": [adir, *runtime_reads],
                       "allowWrite": [adir], "denyWrite": []},
        "enableWeakerNestedSandbox": False,
        "allowNestedUserNamespaces": False,
    }
    validate_settings(settings, adir, runtime_reads)
    return settings


def validate_settings(s, adir, runtime_reads):
    """Confere que a política a ser aplicada é exatamente a restritiva esperada (anti-regressão)."""
    expected_keys = {"network", "filesystem", "enableWeakerNestedSandbox", "allowNestedUserNamespaces"}
    if not isinstance(s, dict) or set(s) != expected_keys:
        raise LauncherError("política com chaves inesperadas")
    n, f = s["network"], s["filesystem"]
    if (n.get("allowedDomains") != [] or n.get("deniedDomains") != [] or n.get("allowLocalBinding") is not False
            or n.get("allowAllUnixSockets") is not False or set(n) != {"allowedDomains", "deniedDomains",
                                                                       "allowLocalBinding", "allowAllUnixSockets"}):
        raise LauncherError("política de rede não é deny total")
    if (set(f) != {"denyRead", "allowRead", "allowWrite", "denyWrite"} or f["denyRead"] != ["/"]
            or f["allowWrite"] != [adir] or f["allowRead"] != [adir, *runtime_reads] or f["denyWrite"] != []):
        raise LauncherError("política de arquivos não é a restritiva esperada")
    if s["enableWeakerNestedSandbox"] is not False or s["allowNestedUserNamespaces"] is not False:
        raise LauncherError("política enfraquece o sandbox")


def build_env(fixture, extra_path_dirs=()):
    """Ambiente mínimo e fechado: nada é herdado de os.environ (sem tokens, SSH_AUTH_SOCK, proxies,
    LD_PRELOAD, NODE_OPTIONS, PYTHON*...). HOME e TMPDIR apontam para diretórios do fixture."""
    env = _plain_env(extra_path_dirs)
    env.update({"HOME": fixture.home, "TMPDIR": fixture.tmp, "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    assert set(env) <= set(ENV_ALLOWED)
    return env


@dataclass
class Fixture:
    """Árvore sintética descartável (única coisa sobre a qual o launcher opera no PR3)."""
    root: str
    authorized: str
    external: str
    home: str
    tmp: str
    nonce: str
    settings_path: str
    _closed: bool = field(default=False, repr=False)

    @property
    def auth_canary(self):
        return os.path.join(self.authorized, "canary_read.txt")

    @property
    def auth_write(self):
        return os.path.join(self.authorized, "written_by_probe.txt")

    @property
    def secret(self):
        return os.path.join(self.external, "secret.txt")

    @property
    def external_target(self):
        return os.path.join(self.external, "writable_target.txt")

    @property
    def external_new(self):
        return os.path.join(self.external, "created_by_probe.txt")

    @property
    def home_decoy(self):
        return os.path.join(self.home, ".ssh", "id_fake")

    @property
    def symlink(self):
        return os.path.join(self.authorized, "link_to_external")

    @property
    def hardlink(self):
        return os.path.join(self.authorized, "hard_to_external")

    @property
    def dotdot(self):
        return os.path.join(self.authorized, "..", "external", "secret.txt")

    @property
    def auth_marker(self):
        return f"AUTHORIZED-CANARY-{self.nonce}"

    @property
    def secret_marker(self):
        return f"EXTERNAL-DECOY-{self.nonce}"

    def cleanup(self):
        if not self._closed:
            self._closed = True
            shutil.rmtree(self.root, ignore_errors=True)  # rmtree não segue symlinks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()
        return False


def create_fixture():
    """Cria o fixture em diretório temporário 0700, com marcadores fictícios. Symlink e hardlink
    para o decoy externo ficam dentro da pasta autorizada (cenário de caminhos indiretos)."""
    root = os.path.realpath(tempfile.mkdtemp(prefix="toolkit-doctor-"))
    try:
        os.chmod(root, 0o700)
        nonce = secrets.token_hex(8)
        d = {k: os.path.join(root, k) for k in ("authorized", "external", "home", "tmp")}
        for p in d.values():
            os.mkdir(p, 0o700)
        os.mkdir(os.path.join(d["home"], ".ssh"), 0o700)
        fx = Fixture(root, d["authorized"], d["external"], d["home"], d["tmp"], nonce,
                     os.path.join(root, "srt-settings.json"))
        for path, text in ((fx.auth_canary, fx.auth_marker), (fx.secret, fx.secret_marker),
                           (fx.external_target, "ORIGINAL-" + nonce), (fx.home_decoy, "FAKE-KEY-" + nonce)):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        os.symlink(fx.secret, fx.symlink)
        try:
            os.link(fx.secret, fx.hardlink)
        except OSError:
            pass  # sistema de arquivos sem hardlink: o check correspondente fica NOT_TESTED
        return fx
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


# Programa dos canários, executado DENTRO do sandbox como `python3 -I -c PROBE_SRC <json>`.
# Executa apenas operações de um conjunto fechado e imprime uma linha JSON com o nonce.
PROBE_SRC = r'''
import json, os, socket, subprocess, sys
P = json.loads(sys.argv[1])
def rd(path):
    try:
        with open(path, "rb") as f:
            return {"ok": True, "data": f.read(256).decode("utf-8", "replace")}
    except Exception as e:
        return {"ok": False, "err": type(e).__name__}
def wr(path):
    try:
        with open(path, "wb") as f:
            f.write(b"probe-write")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "err": type(e).__name__}
def child(kind, path):
    code = ("import json,sys\ntry:\n f=open(sys.argv[2],'rb' if sys.argv[1]=='r' else 'wb')\n"
            " d=f.read(256).decode('utf-8','replace') if sys.argv[1]=='r' else f.write(b'probe-write')\n"
            " print(json.dumps({'ok':True,'data':d if sys.argv[1]=='r' else ''}))\n"
            "except Exception as e:\n print(json.dumps({'ok':False,'err':type(e).__name__}))")
    try:
        r = subprocess.run([sys.executable, "-I", "-c", code, kind, path], capture_output=True, timeout=20)
        return json.loads(r.stdout.decode().strip().splitlines()[-1])
    except Exception as e:
        return {"ok": False, "err": "child:" + type(e).__name__}
def tcp(host, port):
    try:
        s = socket.create_connection((host, port), timeout=3)
        s.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "err": type(e).__name__}
def proc(pid):
    r = {}
    for n in ("environ", "cmdline"):
        r[n] = rd("/proc/%d/%s" % (pid, n))["ok"]
    return {"ok": any(r.values()), "detail": r}
def envinfo(sentinel):
    vals = list(os.environ.values())
    return {"ok": True, "keys": sorted(os.environ), "sentinel_visible": any(sentinel in v for v in vals)}
res = {}
for name, kind, arg in P["ops"]:
    if kind == "read": res[name] = rd(arg)
    elif kind == "write": res[name] = wr(arg)
    elif kind == "child_read": res[name] = child("r", arg)
    elif kind == "child_write": res[name] = child("w", arg)
    elif kind == "tcp": res[name] = tcp(arg[0], arg[1])
    elif kind == "proc": res[name] = proc(arg)
    elif kind == "env": res[name] = envinfo(arg)
print(json.dumps({"nonce": P["nonce"], "results": res}))
'''


@dataclass
class SuiteResult:
    ran: bool
    reason: str = ""
    returncode: int | None = None
    timed_out: bool = False
    results: dict = field(default_factory=dict)
    stderr_tail: str = ""


def build_ops(fx, tcp_loopback, tcp_external, host_pid, sentinel):
    """Operações fechadas dos canários; todas sobre caminhos do fixture."""
    ops = [
        ("auth_read", "read", fx.auth_canary),
        ("auth_write", "write", fx.auth_write),
        ("auth_child_read", "child_read", fx.auth_canary),
        ("ext_read", "read", fx.secret),
        ("ext_write_existing", "write", fx.external_target),
        ("ext_create", "write", fx.external_new),
        ("home_decoy_read", "read", fx.home_decoy),
        ("settings_read", "read", fx.settings_path),
        ("child_ext_read", "child_read", fx.secret),
        ("child_ext_write", "child_write", fx.external_target),
        ("dotdot_read", "read", fx.dotdot),
        ("symlink_read", "read", fx.symlink),
        ("hardlink_read", "read", fx.hardlink),
        ("proc_host", "proc", host_pid),
        ("env", "env", sentinel),
    ]
    if tcp_loopback:
        ops.append(("tcp_loopback", "tcp", list(tcp_loopback)))
    if tcp_external:
        ops.append(("tcp_external", "tcp", list(tcp_external)))
    return ops


def _kill_group(proc):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            continue


def _spawn(argv, env, cwd, timeout):
    """subprocess sem shell, stdin fechado, novo grupo de processos; timeout encerra o grupo."""
    try:
        proc = subprocess.Popen(argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, close_fds=True, start_new_session=True, shell=False)
    except OSError as e:
        raise LauncherError(f"falha ao iniciar o processo: {type(e).__name__}") from None
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc)
        try:
            out, err = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
    finally:
        if proc.poll() is None:
            _kill_group(proc)
    return proc.returncode, out[:MAX_OUTPUT], err[-4096:], timed_out


def _execute(deps, fx, settings_path, ops, timeout):
    srt, node = deps.get("srt"), deps.get("node")
    if not (srt.ok and deps.get("bwrap").ok and deps.get("socat").ok and deps.get("rg").ok and node.ok):
        raise LauncherError("dependências ausentes ou incompatíveis: execução recusada")
    nonce = secrets.token_hex(8)
    payload = json.dumps({"nonce": nonce, "ops": ops}, separators=(",", ":"))
    dirs = {os.path.dirname(deps.get(n).path) for n in ("srt", "node", "bwrap", "socat", "rg")}
    env = build_env(fx, sorted(dirs))
    argv = [srt.path, "--settings", settings_path, "--", INTERPRETER, "-I", "-c", PROBE_SRC, payload]
    rc, out, err, timed_out = _spawn(argv, env, fx.authorized, timeout)
    tail = err.decode("utf-8", "replace")[-600:]
    if timed_out:
        return SuiteResult(False, "timeout: processo encerrado", rc, True, {}, tail)
    parsed = None
    for line in reversed(out.decode("utf-8", "replace").splitlines()):
        try:
            cand = json.loads(line)
        except ValueError:
            continue
        if isinstance(cand, dict) and cand.get("nonce") == nonce and isinstance(cand.get("results"), dict):
            parsed = cand
            break
    if rc != 0 or parsed is None:
        return SuiteResult(False, "o canário não executou até o fim dentro do sandbox", rc, False, {}, tail)
    return SuiteResult(True, "", rc, False, parsed["results"], tail)


def _write_settings(fx, settings):
    fd = os.open(fx.settings_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def run_suite(deps, config, fx, tcp_loopback=None, tcp_external=None, host_pid=None, sentinel="",
              timeout=DEFAULT_TIMEOUT):
    """Executa a suíte de canários no srt com a política restritiva. Só opera sobre `fx`:
    recusa se a pasta autorizada da config não for a do fixture sintético."""
    if config.authorized_dir != fx.authorized:
        raise LauncherRefused("PR3: somente o fixture sintético pode ser usado; pasta real recusada")
    reads = runtime_read_paths()
    settings = build_settings(config, reads)
    _write_settings(fx, settings)
    with open(fx.settings_path, encoding="utf-8") as f:
        if json.load(f) != settings:
            raise LauncherError("política gravada difere da gerada")
    ops = build_ops(fx, tcp_loopback, tcp_external, host_pid if host_pid is not None else os.getpid(), sentinel)
    return _execute(deps, fx, fx.settings_path, ops, timeout)


def run_fail_closed_probe(deps, fx, kind, timeout=DEFAULT_TIMEOUT):
    """Canário de fail-closed: aponta o srt para uma política ausente ou inválida e exige recusa.
    Resultado esperado: ran=False (nenhum comando executou)."""
    if kind == "missing":
        path = os.path.join(fx.root, "no-such-settings.json")
    elif kind == "invalid":
        path = os.path.join(fx.root, "invalid-settings.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
    else:
        raise LauncherError("tipo de canário desconhecido")
    ops = [("auth_write", "write", fx.auth_write + "." + kind)]
    return _execute(deps, fx, path, ops, timeout)


class TcpListeners:
    """Ouvintes TCP no host (loopback e, se houver, interface não loopback) para provar que o
    sandbox não os alcança. Um accept() significa vazamento de rede."""

    def __init__(self):
        self.socks = {}
        self.hits = {}
        self.threads = []
        self.control_ok = {}

    @staticmethod
    def _external_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))  # UDP: não envia pacotes; só consulta a rota
            ip = s.getsockname()[0]
        except OSError:
            return None
        finally:
            s.close()
        return None if ip.startswith("127.") or ip == "0.0.0.0" else ip

    def start(self):
        for label, ip in (("loopback", "127.0.0.1"), ("external", self._external_ip())):
            if not ip:
                continue
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind((ip, 0))
                s.listen(4)
            except OSError:
                s.close()
                continue
            s.settimeout(0.2)
            self.socks[label] = (s, ip, s.getsockname()[1])
            self.hits[label] = 0
        self._stop = threading.Event()
        for label in self.socks:
            t = threading.Thread(target=self._loop, args=(label,), daemon=True)
            t.start()
            self.threads.append(t)
        return self

    def _loop(self, label):
        s = self.socks[label][0]
        while not self._stop.is_set():
            try:
                c, _ = s.accept()
                self.hits[label] += 1
                c.close()
            except (socket.timeout, OSError):
                continue

    def target(self, label):
        e = self.socks.get(label)
        return (e[1], e[2]) if e else None

    def host_control(self, label):
        """Controle: o próprio host consegue conectar (prova que o ouvinte funciona)."""
        t = self.target(label)
        if not t:
            return False
        try:
            socket.create_connection(t, timeout=2).close()
            return True
        except OSError:
            return False

    def stop(self):
        self._stop.set()
        for t in self.threads:
            t.join(timeout=2)
        for s, _, _ in self.socks.values():
            s.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False
