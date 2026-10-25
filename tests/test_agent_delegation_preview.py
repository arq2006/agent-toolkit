#!/usr/bin/env python3
"""GH-F1.12 synthetic delegation-only tests; no agents or real projects."""
import copy
import io
import pathlib
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import agent_delegation_preview as D  # noqa: E402


def policy():
    return {
        "version": 2, "workspace_id": "synthetic-delegation",
        "editable": [{"path": "demo/src", "kind": "directory"}],
        "read_only": [{"path": "demo/docs", "kind": "directory"}],
        "protected": [{"path": "demo/src/secret", "kind": "directory"}],
        "cloud_task_cap_cents": 50, "cloud_day_cap_cents": 100,
        "cloud_project_cap_cents": 200,
    }


def assignment(task_id="TASK-A", domain="qa", role="auditor", path="demo/docs/a.md",
               action="read", agent_id=None, provider="local", cost=None):
    return {
        "agent_id": agent_id or ("agent-" + task_id),
        "branch_tag": "branch-" + task_id if action == "write" else None,
        "worktree_tag": "worktree-" + task_id if action == "write" else None,
        "task": {
            "task_id": task_id, "role": role, "specialty": domain,
            "action": action, "paths": [{"path": path, "kind": "file"}],
            "provider": provider, "complexity": "critical",
            "local_available": True, "estimated_cloud_cents": cost,
            "spent_today_cents": 0, "spent_project_cents": 0,
        },
    }


def delegation(row, root="TASK-ROOT"):
    return {
        "task_id": row["task"]["task_id"], "parent_task": root,
        "delegated_by": "orchestrator", "delegated_to": row["agent_id"],
        "base_role": row["task"]["role"], "domain": row["task"]["specialty"],
    }


def run(*rows, refs=None, root="TASK-ROOT", configured_policy=None):
    tasks = list(rows)
    refs = [delegation(row, root) for row in tasks] if refs is None else refs
    return D.preview_delegations(
        configured_policy or policy(), tasks, refs, root,
    )


class DelegationTests(unittest.TestCase):
    def test_fixed_catalogue_has_exactly_twelve_domains(self):
        catalogue = D.describe_catalogue()
        self.assertEqual(len(catalogue), 12)
        self.assertEqual({x["domain"] for x in catalogue},
                         D.IMPLEMENTATION_DOMAINS | D.REVIEW_ONLY_DOMAINS)
        self.assertEqual(len({x["domain"] for x in catalogue}), 12)

    def test_main_orchestrator_specialist_depth_is_fixed(self):
        p = run(assignment())
        self.assertEqual(p["hierarchy"],
                         ["claude-main", "orchestrator", "specialist"])
        self.assertEqual(p["max_preview_depth_below_main"], 2)
        self.assertEqual(p["delegations"][0]["depth_below_main"], 2)

    def test_demo_never_grants_execution_or_inheritance(self):
        p = D.demo()
        self.assertEqual(len(p["delegations"]), 3)
        self.assertTrue(all(x["route"] == "LOCAL_PLAN_ONLY" for x in p["delegations"]))
        for key in ("agent_execution_authorized", "file_operations_authorized",
                    "cloud_call_authorized", "data_transfer_authorized",
                    "orchestrator_installed", "specialist_agents_installed",
                    "human_approvals_verified", "independent_codex_audit_verified",
                    "filesystem_isolation_verified", "real_reservations_verified",
                    "git_worktrees_verified", "budget_ledger_verified"):
            self.assertIs(p[key], False, key)
        for row in p["delegations"]:
            self.assertFalse(row["owner_approval_inherited"])
            self.assertFalse(row["action_authorizations_inherited"])
            self.assertFalse(row["delegation_activated"])

    def test_catalogue_is_copies_not_mutable_global_state(self):
        c = D.describe_catalogue()
        c[0]["supported_roles"].append("root")
        c[0]["domain"] = "fake"
        self.assertEqual(len(D.describe_catalogue()), 12)
        self.assertFalse(any("root" in x["supported_roles"]
                             for x in D.describe_catalogue()))

    def test_planner_readonly_accepted(self):
        row = assignment(role="planner")
        self.assertEqual(run(row)["delegations"][0]["route"], "LOCAL_PLAN_ONLY")

    def test_auditor_readonly_accepted(self):
        self.assertEqual(run(assignment())["delegations"][0]["route"],
                         "LOCAL_PLAN_ONLY")

    def test_allowed_implementer_domain_has_only_advisory_write(self):
        row = assignment(domain="backend", role="implementer",
                         action="write", path="demo/src/a.py")
        out = run(row)
        self.assertEqual(out["delegations"][0]["route"], "LOCAL_PLAN_ONLY")
        self.assertFalse(out["agent_execution_authorized"])
        self.assertFalse(out["file_operations_authorized"])

    def test_all_implementation_domains_allow_symbolic_write_only(self):
        for domain in D.IMPLEMENTATION_DOMAINS:
            row = assignment(domain=domain, role="implementer",
                             action="write", path="demo/src/a.py")
            self.assertEqual(run(row)["delegations"][0]["route"], "LOCAL_PLAN_ONLY")

    def test_all_review_only_domains_block_implementer_even_for_read(self):
        for domain in D.REVIEW_ONLY_DOMAINS:
            row = assignment(domain=domain, role="implementer",
                             action="read", path="demo/docs/a.md")
            out = run(row)["delegations"][0]
            self.assertEqual(out["route"], "BLOCKED")
            self.assertIn("DOMAIN_ROLE_NOT_PERMITTED", out["reasons"])

    def test_all_review_only_domains_accept_planner(self):
        for domain in D.REVIEW_ONLY_DOMAINS:
            row = assignment(domain=domain, role="planner")
            self.assertEqual(run(row)["delegations"][0]["route"], "LOCAL_PLAN_ONLY")

    def test_all_review_only_domains_accept_auditor(self):
        for domain in D.REVIEW_ONLY_DOMAINS:
            row = assignment(domain=domain, role="auditor")
            self.assertEqual(run(row)["delegations"][0]["route"], "LOCAL_PLAN_ONLY")

    def test_blocked_admission_remains_blocked(self):
        out = run(assignment(path="demo/src/secret/key.pem"))["delegations"][0]
        self.assertEqual(out["route"], "BLOCKED")
        self.assertIn("PROTECTED_PATH", out["reasons"])

    def test_cloud_request_still_requires_owner_and_transfer_approval(self):
        row = assignment(provider="cloud", cost=10)
        p = run(row)
        self.assertEqual(p["delegations"][0]["route"],
                         "CLOUD_OWNER_REVIEW_REQUIRED")
        self.assertIn("OWNER_APPROVAL_REQUIRED",
                      p["delegations"][0]["reasons"])
        self.assertIn("SEPARATE_DATA_TRANSFER_APPROVAL_REQUIRED",
                      p["delegations"][0]["reasons"])
        self.assertFalse(p["data_transfer_authorized"])

    def test_local_unavailable_stops_no_cloud_fallback(self):
        row = assignment()
        row["task"]["local_available"] = False
        out = run(row)["delegations"][0]
        self.assertEqual(out["route"], "BLOCKED")
        self.assertIn("LOCAL_UNAVAILABLE_NO_CLOUD_FALLBACK", out["reasons"])

    def test_write_collision_remains_blocked(self):
        a = assignment("TASK-A", domain="backend", role="implementer",
                       action="write", path="demo/src/a.py")
        b = assignment("TASK-B", domain="frontend", role="implementer",
                       action="write", path="demo/src/a.py")
        out = run(a, b)
        self.assertTrue(all(x["route"] == "BLOCKED" for x in out["delegations"]))

    def test_duplicate_context_remains_blocked(self):
        a = assignment("TASK-A", domain="backend", role="implementer",
                       action="write", path="demo/src/a.py")
        b = assignment("TASK-B", domain="frontend", role="implementer",
                       action="write", path="demo/src/b.py")
        b["worktree_tag"] = a["worktree_tag"]
        out = run(a, b)
        self.assertTrue(all("DUPLICATE_WRITE_CONTEXT" in x["reasons"]
                            for x in out["delegations"]))

    def test_readonly_workspace_no_editable_grants_works(self):
        p = policy()
        p["editable"] = []
        out = run(assignment(), configured_policy=p)
        self.assertEqual(out["delegations"][0]["route"], "LOCAL_PLAN_ONLY")

    def test_unknown_domain_general_rejected(self):
        row = assignment(domain="general")
        with self.assertRaisesRegex(D.gate.PolicyDenied, "unknown_specialist_domain"):
            run(row)

    def test_unknown_domain_typo_is_denied_by_batch(self):
        row = assignment(domain="unknown")
        with self.assertRaises(D.gate.PolicyDenied):
            run(row)

    def test_wrong_delegate_cannot_impersonate_other_agent(self):
        row = assignment()
        edge = delegation(row)
        edge["delegated_to"] = "another-agent"
        with self.assertRaisesRegex(D.gate.PolicyDenied, "delegation_assignment_mismatch"):
            run(row, refs=[edge])

    def test_wrong_base_role_cannot_escalate(self):
        row = assignment()
        edge = delegation(row)
        edge["base_role"] = "implementer"
        with self.assertRaisesRegex(D.gate.PolicyDenied, "delegation_assignment_mismatch"):
            run(row, refs=[edge])

    def test_wrong_domain_cannot_escalate(self):
        row = assignment()
        edge = delegation(row)
        edge["domain"] = "backend"
        with self.assertRaisesRegex(D.gate.PolicyDenied, "delegation_assignment_mismatch"):
            run(row, refs=[edge])

    def test_delegation_cannot_skip_orchestrator(self):
        row = assignment()
        edge = delegation(row)
        edge["delegated_by"] = "claude-main"
        with self.assertRaisesRegex(D.gate.PolicyDenied, "invalid_delegation_graph"):
            run(row, refs=[edge])

    def test_subagent_cannot_delegate_another_subagent(self):
        row = assignment()
        edge = delegation(row)
        edge["delegated_by"] = "agent-other"
        with self.assertRaisesRegex(D.gate.PolicyDenied, "invalid_delegation_graph"):
            run(row, refs=[edge])

    def test_parent_task_must_be_fixed_root(self):
        row = assignment()
        edge = delegation(row)
        edge["parent_task"] = "TASK-ELSE"
        with self.assertRaisesRegex(D.gate.PolicyDenied, "invalid_delegation_graph"):
            run(row, refs=[edge])

    def test_root_task_cannot_impersonate_child(self):
        row = assignment()
        with self.assertRaisesRegex(D.gate.PolicyDenied, "root_task_collision"):
            run(row, root="TASK-A")

    def test_reserved_agent_ids_cannot_impersonate_roles(self):
        for name in D.RESERVED_IDS:
            row = assignment(agent_id=name)
            with self.assertRaisesRegex(D.gate.PolicyDenied, "invalid_delegation_graph"):
                run(row)

    def test_duplicate_delegation_is_denied(self):
        a, b = assignment("TASK-A"), assignment("TASK-B")
        with self.assertRaisesRegex(D.gate.PolicyDenied, "invalid_delegation_graph"):
            run(a, b, refs=[delegation(a), delegation(a)])

    def test_missing_edge_is_denied(self):
        a, b = assignment("TASK-A"), assignment("TASK-B")
        with self.assertRaisesRegex(D.gate.PolicyDenied, "invalid_delegation_count"):
            run(a, b, refs=[delegation(a)])

    def test_unknown_edge_is_denied(self):
        row = assignment()
        edge = delegation(row)
        edge["task_id"] = "TASK-UNKNOWN"
        with self.assertRaisesRegex(D.gate.PolicyDenied, "invalid_delegation_graph"):
            run(row, refs=[edge])

    def test_unrecognized_delegation_field_is_denied(self):
        row = assignment()
        edge = delegation(row)
        edge["human_approved"] = True
        with self.assertRaisesRegex(D.gate.PolicyDenied, "invalid_schema"):
            run(row, refs=[edge])

    def test_missing_field_is_denied(self):
        row = assignment()
        edge = delegation(row)
        del edge["parent_task"]
        with self.assertRaisesRegex(D.gate.PolicyDenied, "invalid_schema"):
            run(row, refs=[edge])

    def test_bad_identifiers_are_denied(self):
        for root in ("/etc", "../bad", "", "é-unsafe"):
            with self.assertRaises(D.gate.PolicyDenied):
                run(assignment(), root=root)

    def test_invalid_delegations_container_is_denied(self):
        with self.assertRaisesRegex(D.gate.PolicyDenied, "invalid_delegation_count"):
            run(assignment(), refs={"invalid": True})

    def test_all_inputs_are_unchanged(self):
        p, rows = policy(), [assignment()]
        edges = [delegation(rows[0])]
        before = copy.deepcopy((p, rows, edges))
        D.preview_delegations(p, rows, edges, "TASK-ROOT")
        self.assertEqual((p, rows, edges), before)

    def test_batch_limit_is_not_bypassed(self):
        rows = [assignment(task_id="TASK-" + str(i)) for i in range(17)]
        with self.assertRaises(D.gate.PolicyDenied):
            run(*rows)

    def test_no_shell_or_network_for_preview(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("shell")), \
             mock.patch("socket.socket", side_effect=AssertionError("network")):
            D.demo()

    def test_cli_requires_synthetic_only(self):
        with self.assertRaises(SystemExit):
            D.main([])
        with self.assertRaises(SystemExit):
            D.main(["--workspace", "/home/any"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(D.main(["--synthetic-only", "--json"]), 0)


if __name__ == "__main__":
    unittest.main()
