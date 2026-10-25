#!/usr/bin/env python3
"""GH-F1.15: deterministic concurrent interleavings on disposable fixtures ONLY.

Fixed mutation threads exercise snapshot staging; never SRT, agents, real
projects, mounts, network or arbitrary operator-supplied files. No isolation
or permission is granted; even perfect results leave STRONG=UNAVAILABLE.
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

SCENARIOS = (
    "baseline",
    "source_inplace_same_size",
    "source_symlink_before_read",
    "source_hardlink_before_recheck",
    "target_symlink_after_write",
    "target_hardlink_after_write",
)
SYNC_TIMEOUT = 5


class RaceRefused(ValueError):
    """Fail-closed fixture-only interleaving error."""


def _mutate_fixture(fx, scenario):
    """Change only known, freshly-created synthetic paths."""
    if scenario == "source_inplace_same_size":
        source = fx.auth_canary
        before = os.stat(source, follow_symlinks=False)
        with open(source, "r+b") as out:
            out.write(b"X" * len(fx.auth_marker.encode("utf-8")))
            out.flush()
            os.fsync(out.fileno())
        after = os.stat(source, follow_symlinks=False)
        return ((before.st_dev, before.st_ino, before.st_size)
                == (after.st_dev, after.st_ino, after.st_size)
                and stat.S_ISREG(after.st_mode))
    if scenario in ("source_symlink_before_read",
                    "source_hardlink_before_recheck"):
        source = fx.auth_canary
        os.unlink(source)
        if scenario == "source_symlink_before_read":
            os.symlink(fx.secret, source)
            return os.path.islink(source)
        os.link(fx.secret, source)
        after = os.stat(source, follow_symlinks=False)
        decoy = os.stat(fx.secret, follow_symlinks=False)
        return ((after.st_dev, after.st_ino) == (decoy.st_dev, decoy.st_ino)
                and after.st_nlink >= 2)
    target = os.path.join(fx.authorized, P.SNAPSHOT_DIR, P.COPY_NAME)
    if scenario == "target_symlink_after_write":
        os.unlink(target)
        os.symlink(fx.secret, target)
        return os.path.islink(target)
    if scenario == "target_hardlink_after_write":
        alias = os.path.join(fx.authorized, "copy-alias-synthetic.txt")
        os.link(target, alias)
        return os.stat(target, follow_symlinks=False).st_nlink == 2
    raise RaceRefused("invalid_scenario")


def _run_case(scenario):
    """Force an exact interleaving using a separate thread and handshake.

    A successful attack means the test MUST see staging REFUSED, never PASS.
    Negative outcomes with an untriggered/failed attacker cannot score PASS.
    """
    if scenario not in SCENARIOS or type(scenario) is not str:
        return False
    try:
        with L.create_fixture() as fx:
            if scenario == "baseline":
                root = P.stage_snapshot(fx)
                return P.host_snapshot_intact(fx, root) is True

            fire = threading.Event()
            finished = threading.Event()
            cancel = threading.Event()
            state = {"triggered": False, "changed": False, "error": False}

            def attacker():
                if not fire.wait(SYNC_TIMEOUT) or cancel.is_set():
                    finished.set()
                    return
                try:
                    state["changed"] = _mutate_fixture(fx, scenario) is True
                except (OSError, RaceRefused):
                    state["error"] = True
                finally:
                    finished.set()

            def synchronize():
                state["triggered"] = True
                fire.set()
                if not finished.wait(SYNC_TIMEOUT):
                    raise RaceRefused("mutation_timeout")

            t = threading.Thread(target=attacker, daemon=True)
            t.start()
            real_read = P.G.read_bytes
            real_write = P._write_all
            read_calls = [0]

            def read_hook(root_fd, rel, *args, **kwargs):
                if rel == "canary_read.txt":
                    read_calls[0] += 1
                    if scenario == "source_symlink_before_read" and read_calls[0] == 1:
                        synchronize()
                    result = real_read(root_fd, rel, *args, **kwargs)
                    if (scenario in ("source_inplace_same_size",
                                     "source_hardlink_before_recheck")
                            and read_calls[0] == 1):
                        synchronize()
                    return result

                return real_read(root_fd, rel, *args, **kwargs)

            def write_hook(fd, data):
                real_write(fd, data)
                if scenario in ("target_symlink_after_write",
                                "target_hardlink_after_write"):
                    synchronize()

            refused = False
            try:
                with mock.patch.object(P.G, "read_bytes", side_effect=read_hook), \
                     mock.patch.object(P, "_write_all", side_effect=write_hook):
                    try:
                        P.stage_snapshot(fx)
                    except (P.SnapshotRefused, G.Openat2Denied,
                            pathguard.PathGuardError, OSError, RaceRefused):
                        refused = True
            finally:
                cancel.set()
                fire.set()
                t.join(SYNC_TIMEOUT)
            return (refused and not t.is_alive()
                    and state["triggered"] is True
                    and state["changed"] is True
                    and state["error"] is False)
    except (P.SnapshotRefused, G.Openat2Denied,
            pathguard.PathGuardError, OSError, RaceRefused):
        return False


def classify(outcomes):
    """Untrusted observation dictionary: exact booleans and exact case set."""
    if type(outcomes) is not dict or set(outcomes) != set(SCENARIOS):
        return [{"id": s, "status": "FAIL"} for s in SCENARIOS]
    return [
        {"id": name, "status": "PASS" if outcomes[name] is True else "FAIL"}
        for name in SCENARIOS
    ]


def run_synthetic():
    report = {
        "mode": "synthetic-only",
        "readiness": "BLOCKED",
        "strong": "UNAVAILABLE",
        "agent_execution_authorized": False,
        "file_operations_authorized": False,
        "cloud_call_authorized": False,
        "data_transfer_authorized": False,
        "native_tools_isolated_for_agents": False,
        "real_bind_mount_tested": False,
        "arbitrary_concurrency_proven": False,
        "real_workspace_used": False,
        "srt_runtime_revalidated": False,
        "cases": [],
        "exit_code": 2,
    }
    if sys.platform != "linux":
        report["cases"] = classify({})
        return report
    observed = {case: _run_case(case) for case in SCENARIOS}
    report["cases"] = classify(observed)
    if len(report["cases"]) == len(SCENARIOS) and all(
            row["status"] == "PASS" for row in report["cases"]):
        report["exit_code"] = 0
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fixture-only controlled race detection; no real agents")
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_synthetic()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for row in report["cases"]:
            print(f'{row["status"]}: {row["id"]}')
        print("STRONG: UNAVAILABLE | Agentes: NÃO AUTORIZADOS")
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
