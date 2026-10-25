#!/usr/bin/env python3
"""GH-F1.13: fail-closed readiness diagnostics for EXISTING synthetic SRT probes.

No execution/permissions grant is possible. No paths, files, credentials,
commands, API keys or agents can be supplied through the CLI. When explicitly
requested, only existing fixed fixture-only probes are run.
"""
import argparse
import json

import srt_openat2_probe as openat2_probe
import srt_readonly_pilot as readonly_pilot

BASELINE_CHECKS = frozenset((
    "baseline_executed", "authorized_read", "authorized_list",
    "reject_traversal", "reject_absolute", "reject_write_request",
    "native_external_read_blocked", "native_write_blocked",
    "native_existing_overwrite_blocked", "native_existing_truncate_blocked",
    "host_existing_files_intact", "hardlink_suite_executed",
    "hardlink_denied", "normal_read_denied_with_hardlink",
    "native_hardlink_result_consistent",
))
OPENAT2_CHECKS = frozenset((
    "worker_executed", "openat2_authorized_read",
    "openat2_authorized_list", "openat2_reject_symlink",
    "openat2_reject_hardlink", "openat2_reject_traversal",
    "openat2_reject_absolute", "srt_native_external_read_blocked",
    "srt_native_write_blocked",
))
EXPECTED_MOUNT_STATUS = "NOT_TESTED_REQUIRES_ISOLATED_MOUNT_NAMESPACE"


def _complete(report, expected):
    """Accept only a complete, unique, verified positive canary set.

    Reports are untrusted observations, not an authorization source. Strict
    built-in types prevent booleans being mistaken for exit codes.
    """
    if type(report) is not dict:
        return False
    if (report.get("mode") != "synthetic-only"
            or report.get("strong") != "UNAVAILABLE"
            or report.get("file_operations") != "BLOCKED_FOR_AGENTS"
            or report.get("agent_execution_authorized") is not False
            or type(report.get("exit_code")) is not int
            or report["exit_code"] != 0):
        return False
    checks = report.get("checks")
    if type(checks) is not list or len(checks) != len(expected):
        return False
    seen = set()
    for row in checks:
        if type(row) is not dict:
            return False
        ident = row.get("id")
        if type(ident) is not str or ident not in expected or ident in seen:
            return False
        if row.get("status") != "PASS":
            return False
        seen.add(ident)
    return seen == expected


def assess_reports(readonly, openat2):
    """Assess historical fixture evidence but NEVER declare STRONG available."""
    read_ok = _complete(readonly, BASELINE_CHECKS)
    open_ok = _complete(openat2, OPENAT2_CHECKS)
    reasons = []

    if not read_ok:
        reasons.append("SRT_READONLY_CANARIES_NOT_VERIFIED")
    if not open_ok:
        reasons.append("OPENAT2_CANARIES_NOT_VERIFIED")

    # SRT v0.0.81 may pass all existing canaries while reporting a native
    # hardlink read of a fictional decoy. That finding MUST block readiness.
    native_status = (readonly.get("native_hardlink_limitation")
                     if type(readonly) is dict else None)
    leak_observed = native_status == "NATIVE_HARDLINK_LEAK_REPRODUCED"
    if leak_observed:
        reasons.append("NATIVE_HARDLINK_LEAK_REPRODUCED")
    elif native_status == "NATIVE_READ_NOT_OBSERVED":
        # A single negative observation does not establish isolation of all
        # native tools against a concurrent untrusted filesystem.
        reasons.append("NATIVE_HARDLINK_DENIAL_NOT_PROVEN")
    else:
        reasons.append("NATIVE_HARDLINK_TEST_INCOMPLETE")

    mount_status = (openat2.get("bind_mount_test")
                    if type(openat2) is dict else None)
    if mount_status != EXPECTED_MOUNT_STATUS:
        reasons.append("BIND_MOUNT_REPORT_UNRECOGNIZED")
    # Even the documented NO_XDEV flag is not proof of an actual mount
    # namespace test; no privileged mount is attempted here.
    reasons.extend((
        "REAL_BIND_MOUNT_ISOLATION_NOT_TESTED",
        "CONCURRENT_MUTATION_AND_TOCTOU_NOT_VERIFIED",
        "NATIVE_AGENT_TOOL_BOUNDARY_NOT_VERIFIED",
        "TRUSTED_ROOT_FD_AND_WORKTREE_NOT_VERIFIED",
    ))

    return {
        "mode": "diagnostic_only",
        "readiness": "BLOCKED",
        "strong": "UNAVAILABLE",
        "readonly_canaries_complete": read_ok,
        "openat2_canaries_complete": open_ok,
        "native_hardlink_leak_observed": leak_observed,
        "real_bind_mount_tested": False,
        "concurrent_mutation_tested": False,
        "agent_execution_authorized": False,
        "file_operations_authorized": False,
        "cloud_call_authorized": False,
        "data_transfer_authorized": False,
        "native_tools_isolated": False,
        "real_worktree_verified": False,
        "root_fd_verified": False,
        "owner_approvals_verified": False,
        "reasons": sorted(set(reasons)),
        "exit_code": 2,
    }


def run_synthetic():
    """Only existing fixed SRT fixtures; never a user-supplied workspace."""
    try:
        readonly = readonly_pilot.run_synthetic()
    except Exception:
        readonly = None  # Fail closed. Never echo exceptions/paths.
    try:
        openat2 = openat2_probe.run_synthetic()
    except Exception:
        openat2 = None
    return assess_reports(readonly, openat2)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fail-closed fixture-only native filesystem diagnostic")
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = run_synthetic()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        for reason in result["reasons"]:
            print("BLOCKED:", reason)
        print("STRONG: UNAVAILABLE | Agentes: NÃO AUTORIZADOS")
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
