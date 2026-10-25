#!/usr/bin/env python3
"""Canário Linux openat2 sob SRT: SOMENTE fixture fictícia; sem agentes.

Não altera mount namespace, não executa comandos arbitrários, não instala
dependências e não autoriza acesso a arquivos reais/STRONG.
"""
import argparse
import json
import os
import secrets
import stat
import sys

import pathguard
import srt_launcher as L
import srt_readonly_pilot as R

MAX_OUTPUT = 8192
GUARD_FILE = "linux_openat2_guard.py"

WORKER_SRC = r'''
import json, os, sys
info = json.loads(sys.argv[1])
if os.getcwd() != info["authorized"]:
    raise SystemExit(13)
sys.path.insert(0, os.getcwd())
import linux_openat2_guard as G
fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
result = {}
def read(k, path):
    try:
        result[k] = {"ok": True, "text": G.read_text(fd, path)}
    except G.Openat2Denied as e:
        result[k] = {"ok": False, "code": str(e)}
try:
    read("inside", "sample.txt")
    read("symlink", "alias-symlink.txt")
    read("hardlink", "alias-hardlink.txt")
    read("traversal", "../external/secret.txt")
    read("absolute", info["external"])
    try:
        entries = G.list_dir(fd)
        result["list"] = {"ok": True, "entries": entries}
    except G.Openat2Denied as e:
        result["list"] = {"ok": False, "code": str(e)}
    try:
        with open(info["external"], "rb") as outside:
            result["native_external_blocked"] = False
    except OSError:
        result["native_external_blocked"] = True
    try:
        attempt = os.open("native-write.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        result["native_write_blocked"] = True
    else:
        os.close(attempt)
        result["native_write_blocked"] = False
finally:
    os.close(fd)
print(json.dumps({"nonce": info["nonce"], "results": result}, separators=(",", ":")))
'''


class ProbeRefused(ValueError):
    pass


def stage_guard(root):
    """Copia somente o módulo fixo do próprio repositório para a fixture nova."""
    source = os.path.join(os.path.dirname(__file__), GUARD_FILE)
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            meta = os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_size > 128 * 1024:
                raise ProbeRefused("module_rejected")
            data = os.read(fd, 128 * 1024 + 1)
            if len(data) > 128 * 1024:
                raise ProbeRefused("module_too_large")
        finally:
            os.close(fd)
        dst = os.open(os.path.join(root, GUARD_FILE), os.O_WRONLY | os.O_CREAT
                      | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        with os.fdopen(dst, "wb") as out:
            out.write(data)
    except OSError:
        raise ProbeRefused("staging_failed") from None


def _run_worker(deps, fx, root, timeout):
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ProbeRefused("invalid_timeout")
    R._check_dependencies(deps)
    nonce = secrets.token_hex(16)
    payload = {"nonce": nonce, "authorized": root, "external": fx.secret}
    dirs = sorted({os.path.dirname(deps.get(name).path)
                   for name in ("srt", "node", "bwrap", "socat", "rg")})
    argv = [deps.get("srt").path, "--settings", fx.settings_path, "--",
            L.INTERPRETER, "-I", "-B", "-c", WORKER_SRC,
            json.dumps(payload, separators=(",", ":"))]
    rc, out, _err, timed_out = L._spawn(argv, L.build_env(fx, dirs), root, timeout)
    if rc != 0 or timed_out or len(out) > MAX_OUTPUT:
        return None
    for line in reversed(out.decode("utf-8", "replace").splitlines()):
        try:
            msg = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if (type(msg) is dict and msg.get("nonce") == nonce
                and type(msg.get("results")) is dict):
            return msg["results"]
    return None


def _item(results, key):
    if type(results) is not dict:
        return {}
    obj = results.get(key)
    return obj if type(obj) is dict else {}


def classify(result, marker):
    checks = []
    def check(k, condition):
        checks.append({"id": k, "status": "PASS" if condition is True else "FAIL"})
    if result is None:
        check("worker_executed", False)
        return checks
    check("worker_executed", True)
    inside = _item(result, "inside")
    check("openat2_authorized_read", inside == {"ok": True, "text": marker})
    listing = _item(result, "list")
    entries = listing.get("entries")
    check("openat2_authorized_list", listing.get("ok") is True
          and type(entries) is list and "sample.txt" in entries and GUARD_FILE in entries)
    for k, error in (("symlink", "path_denied"), ("hardlink", "unsafe_file"),
                     ("traversal", "invalid_path"), ("absolute", "invalid_path")):
        v = _item(result, k)
        check("openat2_reject_" + k, v == {"ok": False, "code": error})
    check("srt_native_external_read_blocked", result.get("native_external_blocked") is True)
    check("srt_native_write_blocked", result.get("native_write_blocked") is True)
    return checks


def run_synthetic(deps=None, timeout=L.DEFAULT_TIMEOUT):
    report = {"mode": "synthetic-only", "strong": "UNAVAILABLE",
              "file_operations": "BLOCKED_FOR_AGENTS",
              "agent_execution_authorized": False,
              "bind_mount_test": "NOT_TESTED_REQUIRES_ISOLATED_MOUNT_NAMESPACE",
              "native_hardlinks": "NOT_MITIGATED_FOR_NATIVE_READ",
              "checks": [], "exit_code": 2}
    try:
        if sys.platform != "linux":
            raise ProbeRefused("unsupported_platform")
        if type(timeout) is not int or not 1 <= timeout <= 120:
            raise ProbeRefused("invalid_timeout")
        deps = deps if deps is not None else L.detect_dependencies()
        R._check_dependencies(deps)
        reads = L.runtime_read_paths(deps)
        with L.create_fixture() as fx:
            root = R.stage_fixture(fx)
            stage_guard(root)
            os.symlink(fx.secret, os.path.join(root, "alias-symlink.txt"))
            os.link(fx.secret, os.path.join(root, "alias-hardlink.txt"))
            policy = R.build_readonly_settings(root, reads)
            L._write_settings(fx, policy)
            with open(fx.settings_path, encoding="utf-8") as f:
                if json.load(f) != policy:
                    raise ProbeRefused("invalid_settings")
            result = _run_worker(deps, fx, root, timeout)
            report["checks"] = classify(result, fx.auth_marker)
    except (ProbeRefused, R.SyntheticPilotError, L.LauncherError,
            pathguard.PathGuardError, OSError, ValueError):
        report["checks"].append({"id": "execution", "status": "FAIL"})
    report["exit_code"] = 0 if report["checks"] and all(
        c["status"] == "PASS" for c in report["checks"]) else 2
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="openat2 + SRT (somente dados fictícios)")
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_synthetic()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for c in report["checks"]:
            print(f"{c['status']}: {c['id']}")
        print("STRONG: UNAVAILABLE | Agentes: NÃO AUTORIZADOS")
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
