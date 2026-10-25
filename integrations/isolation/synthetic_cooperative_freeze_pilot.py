#!/usr/bin/env python3
"""GH-F1.17: fixture-only cooperative freeze and root-FD rebind canaries.

A POSIX flock is ADVISORY, not a sandbox or a substitute for a trusted owner.
An uncooperative writer can still mutate files through ordinary native I/O.
Always exit 2; STRONG and every agent/file/cloud permission remain BLOCKED.
"""
import argparse
import errno
import fcntl
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
import synthetic_aba_root_fd_probe as D

LOCK_NAME = "cooperative-stage.lock"
WAIT = 5
EXPECTED = {
    "fixture_cooperative_snapshot": "STAGED_UNDER_LOCK",
    "cooperative_writer_waits": "WRITER_DEFERRED_UNTIL_RELEASE",
    "root_rebind_fail_closed": "STALE_PATH_REFUSED",
    "preexisting_lock_refused": "UNTRUSTED_LOCK_NAME_REFUSED",
    "uncooperative_writer_bypass": "ADVISORY_BYPASS_REPRODUCED",
}


class FreezeRefused(ValueError):
    """Fixed-fixture refusal; diagnostic output contains no exception paths."""


def _new_lock_fd(fx):
    """Create an exclusive lock inode under a newly created FIXTURE root.

    O_EXCL/O_NOFOLLOW refuse all existing names, including symlinks, while
    open_root pins the fixture parent. No general-purpose lockfile API.
    """
    if type(fx) is not L.Fixture:
        raise FreezeRefused("invalid_fixture")
    parent = pathguard.open_root(fx.root)
    try:
        fd = os.open(LOCK_NAME, os.O_RDWR | os.O_CREAT | os.O_EXCL |
                     os.O_CLOEXEC | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    except OSError:
        raise FreezeRefused("lock_creation_refused") from None
    finally:
        os.close(parent)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                or st.st_uid != os.getuid()
                or stat.S_IMODE(st.st_mode) != 0o600):
            raise FreezeRefused("unsafe_lock_inode")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _cooperative_stage(fx):
    """Keep one lock + source FD for staging and final checks.

    Only writers that VOLUNTARILY lock the same inode are excluded.
    Returning a snapshot path is not a grant of access to a native agent.
    """
    fd = _new_lock_fd(fx)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        source_fd = pathguard.open_root(fx.authorized)
        try:
            if not D._root_path_binding_matches(fx, source_fd):
                raise FreezeRefused("root_rebound")
            root = P.stage_snapshot(fx)
            if not D._root_path_binding_matches(fx, source_fd):
                raise FreezeRefused("root_rebound")
            if P.host_snapshot_intact(fx, root) is not True:
                raise FreezeRefused("snapshot_changed")
            return root
        finally:
            os.close(source_fd)
    finally:
        os.close(fd)  # releasing flock; lock inode remains only in fixture


def _fixture_snapshot():
    with L.create_fixture() as fx:
        root = _cooperative_stage(fx)
        return ("STAGED_UNDER_LOCK"
                if P.host_snapshot_intact(fx, root) is True
                else "NOT_VERIFIED")


def _writer_waits():
    """A separate fd/thread must fail LOCK_NB inside the stage and write after."""
    with L.create_fixture() as fx:
        start = threading.Event()
        attempted = threading.Event()
        release = threading.Event()
        done = threading.Event()
        outcome = {"blocked": False, "after": False, "error": False}

        def writer():
            fd = None
            try:
                if not start.wait(WAIT):
                    outcome["error"] = True
                    return
                fd = os.open(os.path.join(fx.root, LOCK_NAME),
                             os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    outcome["blocked"] = exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                attempted.set()
                if not release.wait(WAIT):
                    outcome["error"] = True
                    return
                fcntl.flock(fd, fcntl.LOCK_EX)
                with open(fx.auth_canary, "r+b") as out:
                    out.write(b"X" * len(fx.auth_marker.encode("utf-8")))
                    out.flush()
                    os.fsync(out.fileno())
                outcome["after"] = True
            except OSError:
                outcome["error"] = True
            finally:
                attempted.set()
                if fd is not None:
                    os.close(fd)
                done.set()

        t = threading.Thread(target=writer, daemon=True)
        t.start()
        original = P.stage_snapshot
        observed_during = [False]

        def staged(fx_arg):
            start.set()
            if not attempted.wait(WAIT):
                raise FreezeRefused("writer_timed_out")
            observed_during[0] = outcome["blocked"] is True and not outcome["after"]
            return original(fx_arg)

        root = None
        try:
            with mock.patch.object(P, "stage_snapshot", side_effect=staged):
                root = _cooperative_stage(fx)
        finally:
            release.set()
            start.set()
            t.join(WAIT)

        if t.is_alive() or not done.is_set() or outcome["error"]:
            return "NOT_VERIFIED"
        if not (observed_during[0] and outcome["blocked"] and outcome["after"]
                and root is not None):
            return "NOT_VERIFIED"
        root_fd = pathguard.open_root(root)
        try:
            copy = G.read_bytes(root_fd, P.COPY_NAME)
        finally:
            os.close(root_fd)
        with open(fx.auth_canary, "rb") as inp:
            source = inp.read(256)
        return ("WRITER_DEFERRED_UNTIL_RELEASE"
                if copy == fx.auth_marker.encode("utf-8") and source != copy
                else "NOT_VERIFIED")


def _root_rebind():
    """Replace ONLY the fixture path during stage; pinned FD must mismatch."""
    with L.create_fixture() as fx:
        original = P.stage_snapshot
        replaced = [False]

        def stage_then_rebind(fx_arg):
            root = original(fx_arg)
            os.rename(fx.authorized,
                      os.path.join(fx.root, "detached-synthetic"))
            os.mkdir(fx.authorized, 0o700)
            replaced[0] = True
            return root

        with mock.patch.object(P, "stage_snapshot", side_effect=stage_then_rebind):
            try:
                _cooperative_stage(fx)
            except FreezeRefused as exc:
                return ("STALE_PATH_REFUSED" if replaced[0]
                        and str(exc) == "root_rebound" else "NOT_VERIFIED")
            return "NOT_VERIFIED"


def _preexisting_lock():
    with L.create_fixture() as fx:
        os.symlink(fx.secret, os.path.join(fx.root, LOCK_NAME))
        try:
            _cooperative_stage(fx)
        except FreezeRefused as exc:
            return ("UNTRUSTED_LOCK_NAME_REFUSED"
                    if str(exc) == "lock_creation_refused"
                    and os.path.islink(os.path.join(fx.root, LOCK_NAME))
                    else "NOT_VERIFIED")
        return "NOT_VERIFIED"


def _uncooperative_bypass():
    """Advisory locks cannot stop a writer that never participates in flock."""
    with L.create_fixture() as fx:
        fd = _new_lock_fd(fx)
        done = threading.Event()
        outcome = {"changed": False, "restored": False, "error": False}
        original = fx.auth_marker.encode("utf-8")

        def writer():
            try:
                with open(fx.auth_canary, "r+b") as stream:
                    other = b"X" * len(original)
                    if other == original:
                        outcome["error"] = True
                        return
                    stream.write(other)
                    stream.flush()
                    os.fsync(stream.fileno())
                    stream.seek(0)
                    outcome["changed"] = stream.read() == other
                    stream.seek(0)
                    stream.write(original)
                    stream.flush()
                    os.fsync(stream.fileno())
                    stream.seek(0)
                    outcome["restored"] = stream.read() == original
            except OSError:
                outcome["error"] = True
            finally:
                done.set()

        t = None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            t = threading.Thread(target=writer, daemon=True)
            t.start()
            complete_while_locked = done.wait(WAIT)
        finally:
            os.close(fd)
            if t is not None:
                t.join(WAIT)
        return ("ADVISORY_BYPASS_REPRODUCED"
                if complete_while_locked and not t.is_alive()
                and outcome["changed"] and outcome["restored"]
                and not outcome["error"] else "NOT_VERIFIED")


CASES = {
    "fixture_cooperative_snapshot": _fixture_snapshot,
    "cooperative_writer_waits": _writer_waits,
    "root_rebind_fail_closed": _root_rebind,
    "preexisting_lock_refused": _preexisting_lock,
    "uncooperative_writer_bypass": _uncooperative_bypass,
}


def classify(values):
    if type(values) is not dict or set(values) != set(EXPECTED):
        return [{"id": case, "observation": "NOT_VERIFIED"}
                for case in EXPECTED]
    return [
        {"id": case, "observation":
            values[case] if type(values[case]) is str
            and values[case] == EXPECTED[case] else "NOT_VERIFIED"}
        for case in EXPECTED
    ]


def run_synthetic():
    """Evidence is diagnostic-only, no code path authorizes real operations."""
    report = {
        "mode": "synthetic-only-diagnostic",
        "readiness": "BLOCKED", "strong": "UNAVAILABLE",
        "agent_execution_authorized": False,
        "file_operations_authorized": False,
        "cloud_call_authorized": False,
        "data_transfer_authorized": False,
        "trusted_owner_provenance_verified": False,
        "uncooperative_writers_isolated": False,
        "aba_protection_proven": False,
        "native_tools_isolated_for_agents": False,
        "real_bind_mount_tested": False,
        "real_worktree_verified": False,
        "real_workspace_used": False,
        "srt_runtime_revalidated": False,
        "observations": [],
        "reasons": [
            "ADVISORY_LOCK_DOES_NOT_EXCLUDE_UNCOOPERATIVE_WRITERS",
            "TRUSTED_OWNER_AND_ROOT_FD_PROVENANCE_NOT_VERIFIED",
            "ABA_AND_REAL_NATIVE_AGENT_BOUNDARY_NOT_RESOLVED",
            "REAL_MOUNT_BOUNDARY_NOT_VERIFIED",
        ],
        "exit_code": 2,
    }
    if sys.platform != "linux":
        report["observations"] = classify({})
        report["reasons"].append("PLATFORM_NOT_VERIFIED")
        return report
    observed = {}
    for case, fn in CASES.items():
        try:
            observed[case] = fn()
        except (OSError, ValueError, G.Openat2Denied, pathguard.PathGuardError,
                P.SnapshotRefused):
            observed[case] = "NOT_VERIFIED"
    report["observations"] = classify(observed)
    if any(x["observation"] == "NOT_VERIFIED" for x in report["observations"]):
        report["reasons"].append("SYNTHETIC_EVIDENCE_INCOMPLETE")
    if observed.get("uncooperative_writer_bypass") == "ADVISORY_BYPASS_REPRODUCED":
        report["reasons"].append("UNCOOPERATIVE_WRITE_BYPASS_REPRODUCED")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fixed-fixture cooperative freeze probe; always blocked")
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
