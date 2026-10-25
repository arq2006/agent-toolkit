#!/usr/bin/env python3
"""GH-F1.14: disposable synthetic copied-inode snapshot under read-only SRT.

Not a generic file copier or agent launcher. Only the fixed canary created by
srt_launcher.create_fixture() can be staged by the closed CLI. All source
reads pass through openat2; the staged copy is independent and contains no
source hardlink. Native process confinement is tested, not assumed.
STRONG and agent/file/cloud permissions remain UNAVAILABLE/BLOCKED.
"""
import argparse
import json
import os
import secrets
import stat
import sys

import linux_openat2_guard as G
import pathguard
import srt_launcher as L
import srt_readonly_pilot as R

SNAPSHOT_DIR = "snapshot-synthetic"
COPY_NAME = "sample.txt"
MAX_OUTPUT = 8192
REQUIRED_RESULTS = frozenset((
    "native_snapshot_read", "native_external_denied",
    "native_source_denied", "native_hardlink_denied",
    "native_symlink_denied", "native_create_denied",
    "native_truncate_denied", "native_list_exact",
))

# Fixed worker executed only inside the same synthetic SRT fixture.
# No arbitrary scripts, paths or commands are accepted from an external user.
WORKER_SRC = r'''
import json, os, sys
data = json.loads(sys.argv[1])
if os.getcwd() != data["snapshot"]:
    raise SystemExit(12)
def native_read(path, expected):
    try:
        with open(path, "rb") as inp:
            return {"opened": True, "matched": inp.read(256) == expected.encode("utf-8")}
    except OSError:
        return {"opened": False, "matched": False}
def blocked_read(path):
    return native_read(path, data["secret"])["opened"] is False
def denied_write(path, mode):
    try:
        with open(path, mode) as out:
            out.write(b"CHANGED-FICTITIOUS")
        return False
    except OSError:
        return True
try:
    names = os.listdir(".")
except OSError:
    names = None
results = {
    "native_snapshot_read": native_read("sample.txt", data["authorized"]),
    "native_external_denied": blocked_read(data["external"]),
    "native_source_denied": blocked_read(data["source"]),
    "native_hardlink_denied": blocked_read(data["hardlink"]),
    "native_symlink_denied": blocked_read(data["symlink"]),
    "native_create_denied": denied_write("created.txt", "xb"),
    "native_truncate_denied": denied_write("sample.txt", "wb"),
    "native_list_exact": names == ["sample.txt"],
}
print(json.dumps({"nonce":data["nonce"], "results":results}, separators=(",", ":")))
'''


class SnapshotRefused(ValueError):
    """Fail closed; never print user paths or contents."""


def _write_all(fd, data):
    pos = 0
    while pos < len(data):
        count = os.write(fd, data[pos:])
        if type(count) is not int or count <= 0:
            raise SnapshotRefused("short_write")
        pos += count


def stage_snapshot(fx):
    """Stage exactly one launcher-created fictitious file, by COPYING bytes.

    The source directory contains a synthetic external hardlink/symlink, which
    must be rejected by openat2 and must never enter the snapshot. This is
    a closed proof fixture, NOT a reusable arbitrary-path staging API.
    """
    if type(fx) is not L.Fixture:
        raise SnapshotRefused("invalid_fixture")
    if not os.path.isfile(fx.hardlink):
        raise SnapshotRefused("hardlink_fixture_unavailable")
    hard = os.stat(fx.hardlink, follow_symlinks=False)
    decoy = os.stat(fx.secret, follow_symlinks=False)
    if (not stat.S_ISREG(hard.st_mode) or hard.st_nlink < 2
            or (hard.st_dev, hard.st_ino) != (decoy.st_dev, decoy.st_ino)):
        raise SnapshotRefused("invalid_hardlink_fixture")

    source_fd = pathguard.open_root(fx.authorized)
    try:
        # Evidence that neither indirect name can be read via this guard.
        for name in ("hard_to_external", "link_to_external"):
            try:
                G.read_bytes(source_fd, name)
            except G.Openat2Denied as denied:
                if str(denied) not in ("unsafe_file", "path_denied"):
                    raise SnapshotRefused("source_boundary_unavailable") from None
            else:
                raise SnapshotRefused("indirect_source_accepted")
        before = os.stat(fx.auth_canary, follow_symlinks=False)
        data = G.read_bytes(source_fd, "canary_read.txt")
        after = os.stat(fx.auth_canary, follow_symlinks=False)
        if (not data or data != fx.auth_marker.encode("utf-8")
                or not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1 or after.st_nlink != 1
                or (before.st_dev, before.st_ino, before.st_size)
                != (after.st_dev, after.st_ino, after.st_size)):
            raise SnapshotRefused("source_not_stable")
    finally:
        os.close(source_fd)

    snapshot = os.path.join(fx.authorized, SNAPSHOT_DIR)
    os.mkdir(snapshot, 0o700)
    target = os.path.join(snapshot, COPY_NAME)
    out_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        _write_all(out_fd, data)
        os.fchmod(out_fd, 0o400)
        os.fsync(out_fd)
    finally:
        os.close(out_fd)
    copied = os.stat(target, follow_symlinks=False)
    if (not stat.S_ISREG(copied.st_mode) or copied.st_nlink != 1
            or (copied.st_dev, copied.st_ino) == (before.st_dev, before.st_ino)
            or copied.st_size != len(data)
            or os.listdir(snapshot) != [COPY_NAME]):
        raise SnapshotRefused("copy_not_independent")
    return snapshot


def seal_snapshot(root):
    """Remove directory write bits before the read-only SRT process starts."""
    os.chmod(root, 0o500)
    st = os.stat(root, follow_symlinks=False)
    f = os.stat(os.path.join(root, COPY_NAME), follow_symlinks=False)
    if (not stat.S_ISDIR(st.st_mode) or st.st_mode & 0o222
            or not stat.S_ISREG(f.st_mode) or f.st_mode & 0o222
            or f.st_nlink != 1):
        raise SnapshotRefused("snapshot_not_sealed")


def host_snapshot_intact(fx, root):
    """Supervisor checks bytes and independent inode after attempted native I/O."""
    try:
        copied = os.stat(os.path.join(root, COPY_NAME), follow_symlinks=False)
        source = os.stat(fx.auth_canary, follow_symlinks=False)
        decoy = os.stat(fx.secret, follow_symlinks=False)
        # Supervisor must not follow a symlink inserted by an unsafe worker.
        # A plain open(root/sample.txt) here could itself disclose outside data.
        root_fd = pathguard.open_root(root)
        try:
            data = G.read_bytes(root_fd, COPY_NAME)
            names = sorted(os.listdir(root_fd))
        finally:
            os.close(root_fd)
        with open(fx.secret, "rb") as inp:
            secret = inp.read(256)
        return (
            stat.S_ISREG(copied.st_mode) and copied.st_nlink == 1
            and (copied.st_dev, copied.st_ino) != (source.st_dev, source.st_ino)
            and copied.st_size == len(data)
            and data == fx.auth_marker.encode("utf-8")
            and secret == fx.secret_marker.encode("utf-8")
            and not os.path.lexists(os.path.join(root, "created.txt"))
            and names == [COPY_NAME]
            and stat.S_ISREG(decoy.st_mode) and decoy.st_nlink >= 2
        )
    except (OSError, G.Openat2Denied, pathguard.PathGuardError):
        return False


def _worker(deps, fx, root, timeout):
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise SnapshotRefused("invalid_timeout")
    R._check_dependencies(deps)
    nonce = secrets.token_hex(16)
    payload = {
        "nonce": nonce, "snapshot": root, "source": fx.auth_canary,
        "hardlink": fx.hardlink, "symlink": fx.symlink,
        "external": fx.secret, "authorized": fx.auth_marker,
        "secret": fx.secret_marker,
    }
    dirs = sorted({os.path.dirname(deps.get(name).path)
                   for name in ("srt", "node", "bwrap", "socat", "rg")})
    argv = [deps.get("srt").path, "--settings", fx.settings_path, "--",
            L.INTERPRETER, "-I", "-B", "-c", WORKER_SRC,
            json.dumps(payload, separators=(",", ":"))]
    rc, out, _err, timed_out = L._spawn(argv, L.build_env(fx, dirs), root, timeout)
    if timed_out or rc != 0 or len(out) > MAX_OUTPUT:
        return None
    for line in reversed(out.decode("utf-8", "replace").splitlines()):
        try:
            obj = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if (type(obj) is dict and obj.get("nonce") == nonce
                and type(obj.get("results")) is dict):
            return obj["results"]
    return None


def classify(result, host_intact, policy_verified, independent_copy):
    """Only strict, complete native observations can PASS the *pilot*."""
    checks = []
    def check(key, value):
        checks.append({"id": key, "status": "PASS" if value is True else "FAIL"})

    check("snapshot_independent_inode", independent_copy is True)
    check("readonly_policy_verified", policy_verified is True)
    check("host_snapshot_unchanged", host_intact is True)
    check("worker_executed", type(result) is dict)
    for key in sorted(REQUIRED_RESULTS):
        obj = result.get(key) if type(result) is dict else None
        if key == "native_snapshot_read":
            valid = obj == {"opened": True, "matched": True}
        else:
            valid = obj is True
        check(key, valid)
    return checks


def run_synthetic(deps=None, timeout=L.DEFAULT_TIMEOUT):
    """Run only disposable fixture, without mounting or authorizing agents."""
    report = {
        "mode": "synthetic-only", "strong": "UNAVAILABLE",
        "readiness": "BLOCKED", "agent_execution_authorized": False,
        "file_operations_authorized": False, "cloud_call_authorized": False,
        "data_transfer_authorized": False,
        "native_tools_isolated_for_agents": False,
        "real_bind_mount_tested": False, "concurrency_verified": False,
        "real_workspace_used": False, "snapshot_hardlink_copy_test": "NOT_TESTED",
        "checks": [], "exit_code": 2,
    }
    root = None
    try:
        if sys.platform != "linux" or type(timeout) is not int or not 1 <= timeout <= 120:
            raise SnapshotRefused("platform_or_timeout_refused")
        deps = deps if deps is not None else L.detect_dependencies()
        R._check_dependencies(deps)
        runtime_reads = L.runtime_read_paths(deps)
        with L.create_fixture() as fx:
            try:
                root = stage_snapshot(fx)
                copied = os.stat(os.path.join(root, COPY_NAME))
                original = os.stat(fx.auth_canary)
                independent = copied.st_nlink == 1 and (
                    copied.st_dev, copied.st_ino) != (original.st_dev, original.st_ino)
                report["snapshot_hardlink_copy_test"] = (
                    "INDEPENDENT_INODE" if independent else "FAILED")
                seal_snapshot(root)
                settings = R.build_readonly_settings(root, runtime_reads)
                L._write_settings(fx, settings)
                with open(fx.settings_path, encoding="utf-8") as inp:
                    verified = json.load(inp) == settings
                result = _worker(deps, fx, root, timeout) if verified else None
                host_intact = host_snapshot_intact(fx, root)
                report["checks"] = classify(result, host_intact, verified, independent)
            finally:
                # Restore permissions only in the supervisor, for cleanup.
                if root is not None:
                    os.chmod(root, 0o700)
    except (SnapshotRefused, G.Openat2Denied, pathguard.PathGuardError,
            R.SyntheticPilotError, L.LauncherError, OSError, ValueError):
        report["checks"].append({"id": "execution", "status": "FAIL"})
    report["exit_code"] = (0 if report["checks"] and all(
        x["status"] == "PASS" for x in report["checks"]) else 2)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fixed native-read snapshot canary; synthetic only")
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_synthetic()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for item in report["checks"]:
            print(item["status"] + ": " + item["id"])
        print("STRONG: UNAVAILABLE | Agentes: NÃO AUTORIZADOS")
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
