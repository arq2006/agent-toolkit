#!/usr/bin/env python3
"""GH-F1.12: static, offline delegation CATALOGUE preview, not actual agents.

Takes untrusted fictional task metadata and rechecks it via GH-F1.11.
Never grants execution, reads real workspaces, creates subagents/worktrees,
transfers data, spends tokens or records human approvals.
"""
import argparse
import json

import agent_batch_plan as batch
import agent_task_policy as gate

# Conservative subset of the proposed 12 GH-F1.7 specialist domains.
# Only these five may carry an implementer label in an advisory proposal.
# Roles here DO NOT imply permissions to execute or write files.
IMPLEMENTATION_DOMAINS = frozenset((
    "frontend", "backend", "apis", "ui-ux", "documentation",
))
REVIEW_ONLY_DOMAINS = frozenset((
    "security", "qa", "architecture", "database",
    "devops", "performance", "management",
))
CATALOG = {
    domain: ("planner", "implementer", "auditor")
    for domain in sorted(IMPLEMENTATION_DOMAINS)
}
CATALOG.update({
    domain: ("planner", "auditor") for domain in sorted(REVIEW_ONLY_DOMAINS)
})
DELEGATION_FIELDS = frozenset((
    "task_id", "parent_task", "delegated_by",
    "delegated_to", "base_role", "domain",
))
RESERVED_IDS = frozenset(("claude-main", "orchestrator", "human", "codex"))


def describe_catalogue():
    """Return stable, immutable-by-caller descriptors (copies of constants)."""
    return [
        {"domain": domain, "supported_roles": list(CATALOG[domain]),
         "agent_installed": False, "tool_permissions_verified": False,
         "execution_authorized": False}
        for domain in sorted(CATALOG)
    ]


def preview_delegations(policy, assignments, delegations, root_task):
    """Propose static main -> orchestrator -> specialist edges only.

    Invalid topology/claims fail closed via PolicyDenied; blocked task
    admission from GH-F1.11 stays blocked in the returned preview.
    """
    root = gate._name(root_task)
    admission = batch.plan_batch(policy, assignments)
    admitted = {item["task_id"]: item for item in admission["assignments"]}
    if root in admitted:
        raise gate.PolicyDenied("root_task_collision")
    if (type(delegations) is not list
            or len(delegations) != len(admission["assignments"])):
        raise gate.PolicyDenied("invalid_delegation_count")

    prepared = {}
    for item in delegations:
        gate._record(item, DELEGATION_FIELDS)
        task_id = gate._name(item["task_id"])
        parent_task = gate._name(item["parent_task"])
        delegated_to = gate._name(item["delegated_to"])
        delegated_by = gate._name(item["delegated_by"])
        base_role = gate._name(item["base_role"])
        domain = gate._name(item["domain"])

        if (task_id in prepared or task_id not in admitted
                or parent_task != root or delegated_by != "orchestrator"
                or delegated_to in RESERVED_IDS):
            raise gate.PolicyDenied("invalid_delegation_graph")
        target = admitted[task_id]
        # Never allow delegation metadata to override the admission result.
        if (delegated_to != target["agent_id"]
                or base_role != target["role"]
                or domain != target["specialty"]):
            raise gate.PolicyDenied("delegation_assignment_mismatch")
        if domain not in CATALOG:
            raise gate.PolicyDenied("unknown_specialist_domain")

        route = target["route"]
        reasons = list(target["reasons"])
        if base_role not in CATALOG[domain]:
            route = "BLOCKED"
            reasons = sorted(set(reasons + ["DOMAIN_ROLE_NOT_PERMITTED"]))

        prepared[task_id] = {
            "task_id": task_id, "parent_task": root,
            "delegated_by": "orchestrator",
            "delegated_to": delegated_to,
            "base_role": base_role, "domain": domain,
            "depth_below_main": 2,
            "route": route, "reasons": reasons,
            "task_approved": False, "owner_approval_inherited": False,
            "action_authorizations_inherited": False,
            "delegation_activated": False,
            "tools_constrained_by_runtime": False,
            "independent_codex_audit_verified": False,
        }

    if set(prepared) != set(admitted):
        raise gate.PolicyDenied("missing_delegation")

    return {
        "mode": "advisory_only",
        "workspace_id": admission["workspace_id"],
        "root_task": root,
        "hierarchy": ["claude-main", "orchestrator", "specialist"],
        "max_preview_depth_below_main": 2,
        "agent_catalogue_only": True,
        "specialists": describe_catalogue(),
        "delegations": [prepared[a["task_id"]] for a in admission["assignments"]],
        "local_first": True,
        "cloud_default": "DENY",
        "agent_execution_authorized": False,
        "file_operations_authorized": False,
        "cloud_call_authorized": False,
        "data_transfer_authorized": False,
        "orchestrator_installed": False,
        "specialist_agents_installed": False,
        "human_approvals_verified": False,
        "independent_codex_audit_verified": False,
        "filesystem_isolation_verified": False,
        "real_reservations_verified": False,
        "git_worktrees_verified": False,
        "budget_ledger_verified": False,
    }


def demo():
    """Entirely fictional tasks and policy; no workspace or provider access."""
    policy = {
        "version": 2, "workspace_id": "fictional-delegation",
        "editable": [],
        "read_only": [{"path": "Example/docs", "kind": "directory"}],
        "protected": [{"path": "Example/docs/secrets", "kind": "directory"}],
        "cloud_task_cap_cents": 0, "cloud_day_cap_cents": 0,
        "cloud_project_cap_cents": 0,
    }

    def task(task_id, domain, role, file_path):
        return {
            "task_id": task_id, "specialty": domain, "role": role,
            "action": "read", "paths": [{"path": file_path, "kind": "file"}],
            "provider": "local", "complexity": "routine",
            "local_available": True, "estimated_cloud_cents": None,
            "spent_today_cents": 0, "spent_project_cents": 0,
        }

    assignments = [
        {"agent_id": "review-qa", "branch_tag": None, "worktree_tag": None,
         "task": task("TASK-QA", "qa", "auditor", "Example/docs/spec.md")},
        {"agent_id": "review-security", "branch_tag": None, "worktree_tag": None,
         "task": task("TASK-SEC", "security", "planner", "Example/docs/policy.md")},
        {"agent_id": "review-docs", "branch_tag": None, "worktree_tag": None,
         "task": task("TASK-DOC", "documentation", "planner",
                      "Example/docs/README.md")},
    ]
    delegations = [
        {"task_id": row["task"]["task_id"], "parent_task": "TASK-ROOT",
         "delegated_by": "orchestrator", "delegated_to": row["agent_id"],
         "base_role": row["task"]["role"],
         "domain": row["task"]["specialty"]}
        for row in assignments
    ]
    return preview_delegations(policy, assignments, delegations, "TASK-ROOT")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Offline and synthetic-only delegation preview")
    parser.add_argument("--synthetic-only", required=True, action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = demo()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("ADVISORY_ONLY — no orchestrator, specialists, or files activated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
