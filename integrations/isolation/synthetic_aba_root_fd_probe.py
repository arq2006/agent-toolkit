#!/usr/bin/env python3
"""GH-F1.16 fixture-only ABA and root-FD path-binding limitations.

DIAGNOSTIC, NOT A MITIGATION, and never an authority to run agents. All file
mutations occur exclusively inside new srt_launcher.create_fixture() trees.
A passing ABA reproduction is a *blocker*. Exit code is ALWAYS 2.
"""
import argparse
import json
import os
import stat
import sys
import threading
from unittest import mock

import linux_openat2_guard as G
import pathguard
import srt_launcher as L
import srt_snapshot_pilot as P

SYNC_TIMEOUT = 5
EXPECTED = {
    "root_fd_baseline": "BOUND",
    "root_fd_foreign": "REJECTED",
    "root_fd_replaced_path": "STALE_FD_DETECTED",
    "aba_reverted_between_reads": "ABA_UNDETECTED",
}


class DiagnosticRefused(ValueError):
    """No exception payloads or paths appear in the public report."""


def _root_path_binding_matches(fx, fd):
    """Compare path and open FD IN THIS FIXTURE at one instant only.

    This does not establish that the path or FD came from an authorized owner,
    and does not stop races, bind mounts or forged root identities.
    """
    if type(fx) is not L.Fixture or type(fd) is not int or fd < 0:
        return False
    try:
        pinned = os.fstat(fd)
        named = os.stat(fx.authorized, follow_symlinks=False)
        return (stat.S_ISDIR(pinned.st_mode)
                and stat.S_ISDIR(named.st_mode)
                and (pinned.st_dev, pinned.st_ino)
                    == (named.st_dev, named.st_ino))
    except (OSError, ValueError, TypeError):
        return False


def _fd_baseline():
    with L.create_fixture() as fx:
        fd = pathguard.open_root(fx.authorized)
        try:
            return ("BOUND" if _root_path_binding_matches(fx, fd)
                    else "NOT_VERIFIED")
        finally:
            os.close(fd)


def _fd_foreign():
    with L.create_fixture() as fx:
        fd = pathguard.open_root(fx.external)
        try:
            return ("REJECTED" if not _root_path_binding_matches(fx, fd)
                    else "NOT_VERIFIED")
        finally:
            os.close(fd)


def _fd_path_replaced():
    """Only swap paths under the disposable test-owned fixture root."""
    with L.create_fixture() as fx:
        fd = pathguard.open_root(fx.authorized)
        try:
            if not _root_path_binding_matches(fx, fd):
                return "NOT_VERIFIED"
            detached = os.path.join(fx.root, "authorized-detached-synthetic")
            os.rename(fx.authorized, detached)
            os.mkdir(fx.authorized, 0o700)
            new_fd = pathguard.open_root(fx.authorized)
            try:
                # The *old* FD still reads the detached old tree. A filename
                # alone is not proof that a pinned FD still belongs to it.
                still_reads_old = (
                    G.read_bytes(fd, "canary_read.txt")
                    == fx.auth_marker.encode("utf-8"))
                return ("STALE_FD_DETECTED"
                        if still_reads_old
                        and not _root_path_binding_matches(fx, fd)
                        and _root_path_binding_matches(fx, new_fd)
                        else "NOT_VERIFIED")
            finally:
                os.close(new_fd)
        finally:
            os.close(fd)


def _aba_reversion():
    """Mutate, then restore exact bytes IN BETWEEN the two guarded reads.

    Deliberately verifies that the GH-F1.15 double-read staging may accept
    the resulting original bytes. It does not use or modify real workspaces.
    """
    with L.create_fixture() as fx:
        original = fx.auth_marker.encode("utf-8")
        original_stat = os.stat(fx.auth_canary, follow_symlinks=False)
        fire, done = threading.Event(), threading.Event()
        state = {"wrote_other": False, "restored": False, "error": False}
        def attacker():
            try:
                if not fire.wait(SYNC_TIMEOUT):
                    state["error"] = True
                    return
                with open(fx.auth_canary, "r+b") as handle:
                    other = b"X" * len(original)
                    if other == original:
                        state["error"] = True
                        return
                    handle.write(other)
                    handle.flush()
                    os.fsync(handle.fileno())
                    handle.seek(0)
                    state["wrote_other"] = handle.read() == other
                    handle.seek(0)
                    handle.write(original)
                    handle.flush()
                    os.fsync(handle.fileno())
                    handle.seek(0)
                    state["restored"] = handle.read() == original
            except OSError:
                state["error"] = True
            finally:
                done.set()

        worker = threading.Thread(target=attacker, daemon=True)
        worker.start()
        original_read = P.G.read_bytes
        calls = [0]
        def read_with_aba(fd, rel, *args, **kwargs):
            value = original_read(fd, rel, *args, **kwargs)
            if rel == "canary_read.txt":
                calls[0] += 1
                if calls[0] == 1:
                    fire.set()
                    if not done.wait(SYNC_TIMEOUT):
                        raise DiagnosticRefused("fixture_mutation_timeout")
            return value

        accepted = False
        root = None
        try:
            with mock.patch.object(P.G, "read_bytes", side_effect=read_with_aba):
                try:
                    root = P.stage_snapshot(fx)
                    accepted = True
                except (P.SnapshotRefused, G.Openat2Denied,
                        pathguard.PathGuardError, OSError, DiagnosticRefused):
                    accepted = False
        finally:
            fire.set()
            worker.join(SYNC_TIMEOUT)

        if worker.is_alive() or state["error"] or not (
                state["wrote_other"] and state["restored"] and calls[0] >= 2):
            return "NOT_VERIFIED"
        now = os.stat(fx.auth_canary, follow_symlinks=False)
        same_identity = (
            (original_stat.st_dev, original_stat.st_ino, original_stat.st_size)
            == (now.st_dev, now.st_ino, now.st_size))
        if not same_identity or not accepted or root is None:
            return "NOT_VERIFIED"
        if P.host_snapshot_intact(fx, root) is not True:
            return "NOT_VERIFIED"
        return "ABA_UNDETECTED"


CASES = {
    "root_fd_baseline": _fd_baseline,
    "root_fd_foreign": _fd_foreign,
    "root_fd_replaced_path": _fd_path_replaced,
    "aba_reverted_between_reads": _aba_reversion,
}


def classify(observed):
    """Closed set, exact literal evidence only (no truthy coercions)."""
    if type(observed) is not dict or set(observed) != set(EXPECTED):
        return [{"id": name, "observation": "NOT_VERIFIED"}
                for name in EXPECTED]
    return [
        {"id": name, "observation": value if type(value) is str
         and value == EXPECTED[name] else "NOT_VERIFIED"}
        for name, value in ((key, observed[key]) for key in EXPECTED)
    ]


def run_synthetic():
    """Always blocked even when all fixed synthetic findings are reproduced."""
    report = {
        "mode": "diagnostic_only",
        "readiness": "BLOCKED",
        "strong": "UNAVAILABLE",
        "agent_execution_authorized": False,
        "file_operations_authorized": False,
        "cloud_call_authorized": False,
        "data_transfer_authorized": False,
        "native_tools_isolated_for_agents": False,
        "root_fd_owner_provenance_verified": False,
        "aba_protection_proven": False,
        "real_bind_mount_tested": False,
        "real_worktree_verified": False,
        "real_workspace_used": False,
        "srt_runtime_revalidated": False,
        "observations": [],
        "reasons": ["ROOT_FD_OWNER_PROVENANCE_NOT_VERIFIED",
                    "ABA_AND_POST_VERIFICATION_RACES_NOT_PREVENTED",
                    "REAL_BIND_MOUNT_AND_NATIVE_TOOLS_NOT_VERIFIED"],
        "exit_code": 2,
    }
    if sys.platform != "linux":
        report["observations"] = classify({})
        report["reasons"].append("PLATFORM_NOT_VERIFIED")
        return report
    observed = {}
    for name, runner in CASES.items():
        try:
            observed[name] = runner()
        except (OSError, ValueError, G.Openat2Denied,
                pathguard.PathGuardError, P.SnapshotRefused):
            observed[name] = "NOT_VERIFIED"
    report["observations"] = classify(observed)
    if any(row["observation"] == "NOT_VERIFIED"
           for row in report["observations"]):
        report["reasons"].append("SYNTHETIC_EVIDENCE_INCOMPLETE")
    if observed.get("aba_reverted_between_reads") == "ABA_UNDETECTED":
        report["reasons"].append("ABA_UNDETECTED_REPRODUCED")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fixed synthetic ABA and root-FD diagnostic; always blocked")
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_synthetic()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for row in report["observations"]:
            print(row["id"] + ": " + row["observation"])
        print("STRONG: UNAVAILABLE | Agentes: NÃO AUTORIZADOS")
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
