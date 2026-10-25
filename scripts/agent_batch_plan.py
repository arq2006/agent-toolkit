#!/usr/bin/env python3
"""GH-F1.11: deterministic offline multi-task coordination PREVIEW only.

This module NEVER launches agents, reserves real files, creates worktrees,
reads project files, reaches a provider or grants an action. Path kinds,
agent names, Git labels and spending are unverified caller-supplied claims.
"""
import argparse
import json

import agent_task_policy as gate

ASSIGNMENT_FIELDS = frozenset(("task", "agent_id", "branch_tag", "worktree_tag"))
RESULT_AUTH_FIELDS = ("agent_execution_authorized", "file_operations_authorized",
                      "cloud_call_authorized", "data_transfer_authorized")


def _ident(value):
    return gate._name(value)


def _paths_overlap(a, b):
    """Compare untrusted relative labels only, on component boundaries."""
    return gate._under(a, b) or gate._under(b, a)


def _candidate(route):
    return route in ("LOCAL_PLAN_ONLY", "CLOUD_OWNER_REVIEW_REQUIRED")


def _block(result, reason):
    result["route"] = "BLOCKED"
    result["reasons"] = sorted(set(result["reasons"] + [reason]))


def plan_batch(policy, assignments):
    """Advisory-only decisions, with fail-closed overlap in a single batch."""
    gate.validate_policy(policy)
    if type(assignments) is not list or not 1 <= len(assignments) <= 16:
        raise gate.PolicyDenied("invalid_assignments")

    seen_tasks, seen_agents = set(), set()
    prepared = []
    for row in assignments:
        gate._record(row, ASSIGNMENT_FIELDS)
        agent_id = _ident(row["agent_id"])
        request = row["task"]
        result = gate.evaluate(policy, request)  # validates every field and scope
        task_id = result["task_id"]
        if task_id in seen_tasks or agent_id in seen_agents:
            raise gate.PolicyDenied("duplicate_assignment")
        seen_tasks.add(task_id)
        seen_agents.add(agent_id)
        if request["action"] == "write":
            # These are symbolic future tags, NOT verified Git refs or paths.
            branch_tag = _ident(row["branch_tag"])
            worktree_tag = _ident(row["worktree_tag"])
        else:
            if row["branch_tag"] is not None or row["worktree_tag"] is not None:
                raise gate.PolicyDenied("read_task_must_not_reserve_worktree")
            branch_tag = worktree_tag = None

        route = {"LOCAL_PROPOSED": "LOCAL_PLAN_ONLY",
                 "CLOUD_REVIEW_REQUIRED": "CLOUD_OWNER_REVIEW_REQUIRED",
                 "BLOCKED": "BLOCKED"}[result["route"]]
        item = {"task_id": task_id, "agent_id": agent_id,
                "role": request["role"], "specialty": request["specialty"],
                "route": route, "reasons": list(result["reasons"]),
                "branch_tag": branch_tag, "worktree_tag": worktree_tag,
                "file_scope_verified": False, "git_state_verified": False,
                "real_reservation_created": False}
        paths = tuple(path for path, kind in gate._validate_request(request))
        # A file and its apparent descendants cannot simultaneously be a
        # coherent request, even if both are called "file" by the caller.
        if any(_paths_overlap(a, b) for i, a in enumerate(paths)
               for b in paths[i + 1:]):
            _block(item, "AMBIGUOUS_INTRA_TASK_PATHS")
        prepared.append((item, request, paths))

    # Conflicts must be symmetric and independent of input order.
    for i, (left, lr, lp) in enumerate(prepared):
        for right, rr, rp in prepared[i + 1:]:
            if not (_candidate(left["route"]) and _candidate(right["route"])):
                continue
            # Separate worktrees and Git branches for concurrent writers.
            if lr["action"] == "write" and rr["action"] == "write":
                if (left["worktree_tag"] == right["worktree_tag"]
                        or left["branch_tag"] == right["branch_tag"]):
                    _block(left, "DUPLICATE_WRITE_CONTEXT")
                    _block(right, "DUPLICATE_WRITE_CONTEXT")
            # Read/read overlap is harmless for a proposed snapshot. Any
            # concurrent writer vs a reader or writer is conservatively stopped.
            if (lr["action"] == "write" or rr["action"] == "write") and any(
                    _paths_overlap(a, b) for a in lp for b in rp):
                _block(left, "FILE_OWNERSHIP_CONFLICT")
                _block(right, "FILE_OWNERSHIP_CONFLICT")

    # No shared/batched cloud spending is proven. Multiple cloud proposals
    # are explicitly refused instead of claiming each independently fits a
    # joint daily/project cap. Single proposals still require owner review.
    cloud = [item for item, request, _ in prepared
             if request["provider"] == "cloud"
             and item["route"] == "CLOUD_OWNER_REVIEW_REQUIRED"]
    if len(cloud) > 1:
        for item in cloud:
            _block(item, "CLOUD_BATCH_BUDGET_NOT_VERIFIED")

    return {
        "mode": "advisory_only", "workspace_id": policy["workspace_id"],
        "local_first": True, "cloud_default": "DENY",
        "assignments": [item for item, _, _ in prepared],
        "agent_execution_authorized": False,
        "file_operations_authorized": False,
        "cloud_call_authorized": False,
        "data_transfer_authorized": False,
        "filesystem_isolation_verified": False,
        "real_reservations_verified": False,
        "git_worktrees_verified": False,
        "budget_ledger_verified": False,
        "human_approvals_verified": False,
    }


def demo():
    """Synthetic data, independent of machine filesystem, Git and providers."""
    policy = {"version": 2, "workspace_id": "fictional-project",
              "editable": [{"path": "demo/src", "kind": "directory"}],
              "read_only": [{"path": "demo/docs", "kind": "directory"}],
              "protected": [{"path": "demo/src/secrets", "kind": "directory"}],
              "cloud_task_cap_cents": 0, "cloud_day_cap_cents": 0,
              "cloud_project_cap_cents": 0}

    def request(task_id, role, action, path, specialty):
        return {"task_id": task_id, "role": role, "action": action,
                "specialty": specialty, "provider": "local",
                "complexity": "routine", "local_available": True,
                "paths": [{"path": path, "kind": "file"}],
                "estimated_cloud_cents": None,
                "spent_today_cents": 0, "spent_project_cents": 0}

    return plan_batch(policy, [
        {"agent_id": "writer-alpha", "branch_tag": "demo-a",
         "worktree_tag": "synthetic-wt-a",
         "task": request("TASK-A", "implementer", "write",
                         "demo/src/a.py", "backend")},
        {"agent_id": "writer-beta", "branch_tag": "demo-b",
         "worktree_tag": "synthetic-wt-b",
         "task": request("TASK-B", "implementer", "write",
                         "demo/src/b.py", "frontend")},
        {"agent_id": "reviewer", "branch_tag": None, "worktree_tag": None,
         "task": request("TASK-C", "auditor", "read",
                         "demo/docs/readme.md", "security")},
    ])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline task coordination demo")
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = demo()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("ADVISORY_ONLY — no agents, file reservations or cloud enabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
