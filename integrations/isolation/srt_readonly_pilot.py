#!/usr/bin/env python3
"""Piloto SRT + readonly_executor: SOMENTE fixtures sintéticas descartáveis.

Sem Claude, comandos da IA, CLI arbitrária, projetos reais ou autorização STRONG.
Executa código fixo de testes dentro de srt 0.0.81, com allowWrite=[].
O subprocesso NÃO herda credenciais e só recebe marcadores FICTÍCIOS.
"""
import argparse
import dataclasses
import json
import os
import secrets
import stat
import sys

import isolation_config
import pathguard
import srt_launcher as L

MAX_SOURCE_BYTES = 128 * 1024
MAX_PILOT_OUTPUT = 8192
SOURCE_FILES = ("pathguard.py", "readonly_executor.py")

# Código CONSTANTE: sem código, comando, argv executável ou prompt vindo do usuário.
# As únicas variáveis no argumento são caminhos e marcadores criados na fixture.
WORKER_SRC = r'''
import json, os, sys
payload = json.loads(sys.argv[1])
if os.getcwd() != payload["authorized"] or payload["suite"] not in ("baseline", "hardlink"):
    raise SystemExit(12)
sys.path.insert(0, os.getcwd())
import readonly_executor as E

fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
results = {}
def request(name, data):
    try:
        response = E.dispatch_json(fd, json.dumps(data, separators=(",", ":")).encode("utf-8"))
        results[name] = {"ok": True, "response": response}
    except E.RequestDenied as e:
        results[name] = {"ok": False, "code": str(e)}

def native_read(path, marker):
    try:
        with open(path, "rb") as f:
            data = f.read(256)
        return {"opened": True, "matched": data == marker.encode("utf-8")}
    except (OSError, UnicodeError):
        return {"opened": False, "matched": False}

try:
    if payload["suite"] == "baseline":
        request("read_inside", {"op":"read", "path":"sample.txt"})
        request("list_inside", {"op":"list"})
        request("reject_traversal", {"op":"read", "path":"../external/secret.txt"})
        request("reject_absolute", {"op":"read", "path":payload["external"]})
        request("reject_write_request", {"op":"write", "path":"write-probe.txt"})
        results["native_external_read"] = native_read(payload["external"], payload["secret"])
        try:
            fdwrite = os.open("write-probe.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        except OSError:
            results["native_write_denied"] = True
        else:
            os.close(fdwrite)
            results["native_write_denied"] = False
    else:
        request("hardlink_denied", {"op":"read", "path":"hardlink.txt"})
        request("normal_read_denied_with_hardlink", {"op":"read", "path":"sample.txt"})
        # Observação informativa: a leitura nativa pode revelar conteúdo via hardlink.
        results["native_hardlink"] = native_read("hardlink.txt", payload["secret"])
finally:
    os.close(fd)
print(json.dumps({"nonce": payload["nonce"], "suite":payload["suite"], "results":results}, separators=(",", ":")))
'''


class SyntheticPilotError(Exception):
    """Falha no piloto; nunca permite fallback fora do sandbox."""


def stage_fixture(fx):
    """Copia apenas dois módulos versionados e um marcador FICTÍCIO para uma subárvore nova."""
    root = os.path.join(fx.authorized, "readonly-synthetic")
    os.mkdir(root, 0o700)
    for name in SOURCE_FILES:
        source = os.path.join(os.path.dirname(__file__), name)
        try:
            fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_SOURCE_BYTES:
                    raise SyntheticPilotError("módulo de origem recusado")
                data = os.read(fd, MAX_SOURCE_BYTES + 1)
                if len(data) > MAX_SOURCE_BYTES:
                    raise SyntheticPilotError("módulo excedeu o limite")
            finally:
                os.close(fd)
            target = os.open(os.path.join(root, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            with os.fdopen(target, "wb") as out:
                out.write(data)
        except OSError as e:
            raise SyntheticPilotError(f"falha ao preparar fixture: {type(e).__name__}") from None
    sample = os.path.join(root, "sample.txt")
    fd = os.open(sample, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(fx.auth_marker)
    # Prova que o host consegue abrir a pasta raiz via pathguard antes de passar a SRT.
    fd = pathguard.open_root(root)
    try:
        if pathguard.scan_tree(fd):
            raise SyntheticPilotError("árvore sintética insegura")
    finally:
        os.close(fd)
    return root


def build_readonly_settings(root, reads):
    """Deriva as regras restritivas existentes e REMOVE qualquer permissão de escrita."""
    cfg = isolation_config.Config(root, "none", "deny", ())
    base = L.build_settings(cfg, reads)  # valida rede, denyRead, allowRead e seccomp
    base["filesystem"]["allowWrite"] = []
    if (base["filesystem"] != {"denyRead": ["/"], "allowRead": [root, *reads],
                               "allowWrite": [], "denyWrite": []}
            or base["network"] != {"allowedDomains": [], "deniedDomains": [],
                                    "allowLocalBinding": False, "allowAllUnixSockets": False}
            or base["enableWeakerNestedSandbox"] is not False
            or base["allowNestedUserNamespaces"] is not False):
        raise SyntheticPilotError("política read-only inválida")
    return base


def _check_dependencies(deps):
    mandatory = ("srt", "node", "bwrap", "socat", "rg", "apply-seccomp")
    if any(not deps.get(name).ok for name in mandatory):
        raise SyntheticPilotError("dependências do SRT incompletas ou incompatíveis")


def _worker(deps, fx, root, suite, timeout):
    if suite not in ("baseline", "hardlink"):
        raise SyntheticPilotError("suíte não autorizada")
    _check_dependencies(deps)
    nonce = secrets.token_hex(16)
    payload = {"suite": suite, "nonce": nonce, "authorized": root,
               "external": fx.secret, "secret": fx.secret_marker}
    dirs = sorted({os.path.dirname(deps.get(n).path) for n in ("srt", "node", "bwrap", "socat", "rg")})
    env = L.build_env(fx, dirs)
    argv = [deps.get("srt").path, "--settings", fx.settings_path, "--",
            L.INTERPRETER, "-I", "-B", "-c", WORKER_SRC,
            json.dumps(payload, separators=(",", ":"))]
    rc, out, err, timed_out = L._spawn(argv, env, root, timeout)
    if timed_out or rc != 0 or len(out) > MAX_PILOT_OUTPUT:
        return None
    for line in reversed(out.decode("utf-8", "replace").splitlines()):
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if (type(parsed) is dict and parsed.get("nonce") == nonce
                and parsed.get("suite") == suite and type(parsed.get("results")) is dict):
            return parsed["results"]
    return None


def classify(baseline, hardlink, marker):
    """PASS exige controles positivos e negativos concretos na mesma execução real."""
    checks = []
    def check(name, ok):
        checks.append({"id": name, "status": "PASS" if ok else "FAIL"})
    if baseline is None:
        check("baseline_executed", False)
        return checks
    check("baseline_executed", True)
    r = baseline.get("read_inside", {})
    check("authorized_read", r.get("ok") is True
          and r.get("response") == {"ok": True, "op": "read", "text": marker})
    listed = baseline.get("list_inside", {})
    entries = listed.get("response", {}).get("entries", [])
    check("authorized_list", listed.get("ok") is True and
          isinstance(entries, list) and "sample.txt" in entries
          and all(x in entries for x in SOURCE_FILES))
    for key, expected in (("reject_traversal", "invalid_path"),
                          ("reject_absolute", "invalid_path"),
                          ("reject_write_request", "operation_denied")):
        r = baseline.get(key, {})
        check(key, r.get("ok") is False and r.get("code") == expected)
    native = baseline.get("native_external_read", {})
    check("native_external_read_blocked", native.get("opened") is False)
    check("native_write_blocked", baseline.get("native_write_denied") is True)
    if hardlink is None:
        check("hardlink_suite_executed", False)
        return checks
    check("hardlink_suite_executed", True)
    for key in ("hardlink_denied", "normal_read_denied_with_hardlink"):
        r = hardlink.get(key, {})
        check(key, r.get("ok") is False and r.get("code") == "unsafe_tree")
    # A vulnerabilidade nativa é explicitada separadamente, sem pontuar como PASS.
    return checks


def run_synthetic(deps=None, timeout=L.DEFAULT_TIMEOUT):
    """Executa SOMENTE fixture nova; não recebe caminho de projeto nem arquivo real."""
    rep = {"mode": "synthetic-only", "strong": "UNAVAILABLE",
           "file_operations": "BLOCKED_FOR_AGENTS", "agent_execution_authorized": False,
           "checks": [], "native_hardlink_limitation": "NOT_TESTED", "exit_code": 2}
    try:
        if not sys.platform.startswith("linux"):
            raise SyntheticPilotError("plataforma não validada")
        if not (1 <= timeout <= 120):
            raise SyntheticPilotError("timeout inválido")
        deps = deps if deps is not None else L.detect_dependencies()
        _check_dependencies(deps)
        reads = L.runtime_read_paths(deps)
        with L.create_fixture() as fx:
            root = stage_fixture(fx)
            policy = build_readonly_settings(root, reads)
            L._write_settings(fx, policy)
            with open(fx.settings_path, encoding="utf-8") as inp:
                if json.load(inp) != policy:
                    raise SyntheticPilotError("política gravada difere da validada")
            baseline = _worker(deps, fx, root, "baseline", timeout)
            if baseline is not None and baseline.get("read_inside", {}).get("ok") is True:
                # Só um hardlink novo da fixture fictícia, fora de quaisquer projetos reais.
                try:
                    os.link(fx.secret, os.path.join(root, "hardlink.txt"))
                except OSError:
                    hardlink = None
                else:
                    hardlink = _worker(deps, fx, root, "hardlink", timeout)
                    if hardlink is not None:
                        n = hardlink.get("native_hardlink", {})
                        rep["native_hardlink_limitation"] = (
                            "NATIVE_HARDLINK_LEAK_REPRODUCED" if
                            n.get("opened") is True and n.get("matched") is True
                            else "NATIVE_READ_NOT_OBSERVED" if n.get("opened") is False
                            else "UNEXPECTED")
            else:
                hardlink = None
            rep["checks"] = classify(baseline, hardlink, fx.auth_marker)
    except (SyntheticPilotError, L.LauncherError, pathguard.PathGuardError, OSError, ValueError) as e:
        rep["checks"].append({"id": "execution", "status": "FAIL", "reason": type(e).__name__})
    rep["exit_code"] = 0 if rep["checks"] and all(
        c["status"] == "PASS" for c in rep["checks"]) else 2
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(description="Piloto offline SRT, apenas fixture sintética")
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_synthetic()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for c in report["checks"]:
            print(f"{c['status']}: {c['id']}")
        print(f"Hardlink nativo: {report['native_hardlink_limitation']}")
        print("STRONG: UNAVAILABLE | Agentes: NÃO AUTORIZADOS")
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
