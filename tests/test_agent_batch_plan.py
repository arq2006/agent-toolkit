#!/usr/bin/env python3
"""GH-F1.11 adversarial synthetic task-coordination tests, never live agents."""
import copy
import io
import pathlib
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import agent_batch_plan as plan  # noqa: E402


def entry(path, kind="file"):
    return {"path": path, "kind": kind}


def policy():
    return {"version": 2, "workspace_id": "synthetic",
            "editable": [entry("demo/src", "directory")],
            "read_only": [entry("demo/docs", "directory")],
            "protected": [entry("demo/src/secret", "directory")],
            "cloud_task_cap_cents": 50, "cloud_day_cap_cents": 120,
            "cloud_project_cap_cents": 250}


def request(id_, role="implementer", action="write", path="demo/src/a.py",
            provider="local", cost=None):
    return {"task_id": id_, "role": role, "specialty": "backend",
            "action": action, "paths": [entry(path)],
            "provider": provider, "complexity": "routine",
            "local_available": True, "estimated_cloud_cents": cost,
            "spent_today_cents": 0, "spent_project_cents": 0}


def write(id_, path, agent_id=None, branch_tag=None, worktree_tag=None):
    return {"agent_id": agent_id or ("owner-" + id_),
            "branch_tag": branch_tag or ("branch-" + id_),
            "worktree_tag": worktree_tag or ("tree-" + id_),
            "task": request(id_, path=path)}


def read(id_, path, role="planner"):
    return {"agent_id": "reader-" + id_,
            "branch_tag": None, "worktree_tag": None,
            "task": request(id_, role=role, action="read", path=path)}


def routes(result):
    return {x["task_id"]: x["route"] for x in result["assignments"]}


class BatchTests(unittest.TestCase):
    def test_demo_three_distinct_assignments_are_advisory(self):
        result = plan.demo()
        self.assertEqual([a["route"] for a in result["assignments"]],
                         ["LOCAL_PLAN_ONLY"] * 3)
        self.assertTrue(result["local_first"])
        self.assertEqual(result["cloud_default"], "DENY")
        for gate in ("agent_execution_authorized", "file_operations_authorized",
                     "cloud_call_authorized", "data_transfer_authorized",
                     "filesystem_isolation_verified", "real_reservations_verified",
                     "git_worktrees_verified", "budget_ledger_verified",
                     "human_approvals_verified"):
            self.assertFalse(result[gate], gate)

    def test_disjoint_writers_proposed_with_symbolic_tags_only(self):
        result = plan.plan_batch(policy(), [write("A", "demo/src/a.py"),
                                            write("B", "demo/src/b.py")])
        self.assertEqual(routes(result), {"A": "LOCAL_PLAN_ONLY", "B": "LOCAL_PLAN_ONLY"})
        self.assertFalse(result["assignments"][0]["real_reservation_created"])
        self.assertFalse(result["assignments"][0]["git_state_verified"])

    def test_identical_writer_paths_both_blocked(self):
        result = plan.plan_batch(policy(), [write("A", "demo/src/a.py"),
                                            write("B", "demo/src/a.py")])
        self.assertEqual(routes(result), {"A": "BLOCKED", "B": "BLOCKED"})
        self.assertTrue(all("FILE_OWNERSHIP_CONFLICT" in x["reasons"]
                            for x in result["assignments"]))

    def test_file_ancestor_fake_type_conflict(self):
        result = plan.plan_batch(policy(), [write("A", "demo/src/file.py"),
                                            write("B", "demo/src/file.py/child")])
        self.assertEqual(list(routes(result).values()), ["BLOCKED", "BLOCKED"])

    def test_writer_reader_same_file_blocked(self):
        result = plan.plan_batch(policy(), [write("A", "demo/src/a.py"),
                                            read("B", "demo/src/a.py")])
        self.assertEqual(routes(result), {"A": "BLOCKED", "B": "BLOCKED"})

    def test_two_readers_on_same_file_allowed(self):
        result = plan.plan_batch(policy(), [read("A", "demo/docs/a.md"),
                                            read("B", "demo/docs/a.md", "auditor")])
        self.assertEqual(routes(result), {"A": "LOCAL_PLAN_ONLY", "B": "LOCAL_PLAN_ONLY"})

    def test_writes_on_sibling_prefix_not_a_conflict(self):
        result = plan.plan_batch(policy(), [write("A", "demo/src/a.py"),
                                            write("B", "demo/src/a.py-more")])
        self.assertEqual(list(routes(result).values()), ["LOCAL_PLAN_ONLY"] * 2)

    def test_duplicate_symbolic_branch_blocks_both(self):
        assignments = [write("A", "demo/src/a.py", branch_tag="shared"),
                       write("B", "demo/src/b.py", branch_tag="shared")]
        result = plan.plan_batch(policy(), assignments)
        self.assertTrue(all(x["route"] == "BLOCKED" and
                            "DUPLICATE_WRITE_CONTEXT" in x["reasons"]
                            for x in result["assignments"]))

    def test_duplicate_symbolic_worktree_blocks_both(self):
        assignments = [write("A", "demo/src/a.py", worktree_tag="shared"),
                       write("B", "demo/src/b.py", worktree_tag="shared")]
        result = plan.plan_batch(policy(), assignments)
        self.assertTrue(all(x["route"] == "BLOCKED" and
                            "DUPLICATE_WRITE_CONTEXT" in x["reasons"]
                            for x in result["assignments"]))

    def test_three_way_conflict_is_not_hidden_by_first_collision(self):
        assignments = [write("A", "demo/src/a.py"),
                       write("B", "demo/src/a.py"),
                       write("C", "demo/src/a.py")]
        result = plan.plan_batch(policy(), assignments)
        self.assertEqual(list(routes(result).values()), ["BLOCKED"] * 3)
        result2 = plan.plan_batch(policy(), list(reversed(assignments)))
        self.assertEqual(routes(result), routes(result2))

    def test_same_task_id_refused(self):
        a, b = write("A", "demo/src/a.py"), write("A", "demo/src/b.py")
        b["agent_id"] = "someone-new"
        with self.assertRaisesRegex(plan.gate.PolicyDenied, "duplicate_assignment"):
            plan.plan_batch(policy(), [a, b])

    def test_same_agent_assigned_to_parallel_tasks_refused(self):
        with self.assertRaisesRegex(plan.gate.PolicyDenied, "duplicate_assignment"):
            plan.plan_batch(policy(), [write("A", "demo/src/a.py", agent_id="same"),
                                             write("B", "demo/src/b.py", agent_id="same")])

    def test_invalid_unknown_assignment_fields_refused(self):
        a = write("A", "demo/src/a.py")
        a["approved_by"] = "claimed-owner"
        with self.assertRaises(plan.gate.PolicyDenied):
            plan.plan_batch(policy(), [a])

    def test_null_writer_worktree_refused(self):
        a = write("A", "demo/src/a.py")
        a["worktree_tag"] = None
        with self.assertRaises(plan.gate.PolicyDenied):
            plan.plan_batch(policy(), [a])

    def test_malformed_branch_and_worktree_refused(self):
        for field, value in (("branch_tag", "../../outside"),
                             ("worktree_tag", "/var/secrets"),
                             ("agent_id", "unsafe/agent")):
            a = write("A", "demo/src/a.py")
            a[field] = value
            with self.assertRaises(plan.gate.PolicyDenied):
                plan.plan_batch(policy(), [a])

    def test_read_tasks_cannot_claim_write_context(self):
        for field in ("branch_tag", "worktree_tag"):
            a = read("A", "demo/docs/a.md")
            a[field] = "try"
            with self.assertRaisesRegex(plan.gate.PolicyDenied, "read_task_must_not_reserve_worktree"):
                plan.plan_batch(policy(), [a])

    def test_read_only_workspace_is_accepted(self):
        rule = policy()
        rule["editable"] = []
        result = plan.plan_batch(rule, [read("A", "demo/docs/a.md", "planner")])
        self.assertEqual(result["assignments"][0]["route"], "LOCAL_PLAN_ONLY")

    def test_blocked_policy_scope_cannot_be_upgraded_by_assignment(self):
        result = plan.plan_batch(policy(), [write("A", "outside/private.txt")])
        self.assertEqual(result["assignments"][0]["route"], "BLOCKED")
        self.assertFalse(result["file_operations_authorized"])

    def test_protected_path_remains_blocked(self):
        result = plan.plan_batch(policy(), [write("A", "demo/src/secret/x.py")])
        self.assertEqual(result["assignments"][0]["route"], "BLOCKED")

    def test_not_allowed_writer_role_does_not_get_proposal(self):
        a = write("A", "demo/src/a.py")
        a["task"]["role"] = "planner"
        result = plan.plan_batch(policy(), [a])
        self.assertEqual(result["assignments"][0]["route"], "BLOCKED")

    def test_high_risk_specialties_do_not_receive_write_proposals(self):
        for specialty in ("database", "devops", "performance", "management"):
            a = write("A", "demo/src/a.py")
            a["task"]["specialty"] = specialty
            r = plan.plan_batch(policy(), [a])["assignments"][0]
            self.assertEqual(r["route"], "BLOCKED")
            self.assertIn("SPECIALTY_WRITE_REQUIRES_SEPARATE_PROCEDURE",
                          r["reasons"])

    def test_high_risk_specialties_can_plan_readonly_analysis(self):
        for specialty in ("database", "devops", "performance", "management"):
            a = read("A", "demo/docs/a.md")
            a["task"]["specialty"] = specialty
            r = plan.plan_batch(policy(), [a])["assignments"][0]
            self.assertEqual(r["route"], "LOCAL_PLAN_ONLY")
            self.assertFalse(r["real_reservation_created"])

    def test_local_unavailable_does_not_route_to_cloud(self):
        a = write("A", "demo/src/a.py")
        a["task"]["local_available"] = False
        result = plan.plan_batch(policy(), [a])
        self.assertEqual(result["assignments"][0]["route"], "BLOCKED")
        self.assertIn("LOCAL_UNAVAILABLE_NO_CLOUD_FALLBACK",
                      result["assignments"][0]["reasons"])

    def test_single_cloud_proposal_never_grants_approval(self):
        a = read("A", "demo/docs/a.md")
        a["task"].update(provider="cloud", estimated_cloud_cents=10,
                         complexity="critical")
        result = plan.plan_batch(policy(), [a])
        self.assertEqual(result["assignments"][0]["route"],
                         "CLOUD_OWNER_REVIEW_REQUIRED")
        self.assertIn("OWNER_APPROVAL_REQUIRED", result["assignments"][0]["reasons"])
        self.assertFalse(result["cloud_call_authorized"])
        self.assertFalse(result["data_transfer_authorized"])

    def test_two_cloud_proposals_cannot_claim_joint_budget(self):
        a, b = read("A", "demo/docs/a.md"), read("B", "demo/docs/b.md")
        for task in (a, b):
            task["task"].update(provider="cloud", estimated_cloud_cents=10,
                                complexity="critical")
        result = plan.plan_batch(policy(), [a, b])
        self.assertTrue(all(t["route"] == "BLOCKED" and
                            "CLOUD_BATCH_BUDGET_NOT_VERIFIED" in t["reasons"]
                            for t in result["assignments"]))

    def test_over_budget_cloud_always_blocked(self):
        a = read("A", "demo/docs/a.md")
        a["task"].update(provider="cloud", estimated_cloud_cents=51)
        result = plan.plan_batch(policy(), [a])
        self.assertEqual(result["assignments"][0]["route"], "BLOCKED")

    def test_directory_kind_is_ineligible_for_proposal(self):
        a = read("A", "demo/docs")
        a["task"]["paths"] = [entry("demo/docs", "directory")]
        result = plan.plan_batch(policy(), [a])
        self.assertEqual(result["assignments"][0]["route"], "BLOCKED")

    def test_ambiguous_path_within_one_task_blocked(self):
        a = write("A", "demo/src/a.py")
        a["task"]["paths"].append(entry("demo/src/a.py/child"))
        result = plan.plan_batch(policy(), [a])
        self.assertEqual(result["assignments"][0]["route"], "BLOCKED")
        self.assertIn("AMBIGUOUS_INTRA_TASK_PATHS",
                      result["assignments"][0]["reasons"])

    def test_empty_batch_or_over_limit_is_refused(self):
        with self.assertRaises(plan.gate.PolicyDenied):
            plan.plan_batch(policy(), [])
        with self.assertRaises(plan.gate.PolicyDenied):
            plan.plan_batch(policy(), [read(str(i), "demo/docs/a.md")
                                       for i in range(17)])

    def test_rejects_invalid_policy(self):
        rule = policy()
        rule["editable"] = []
        rule["read_only"] = []
        with self.assertRaises(plan.gate.PolicyDenied):
            plan.plan_batch(rule, [read("A", "demo/docs/a.md")])

    def test_input_is_not_mutated(self):
        p, tasks = policy(), [write("A", "demo/src/a.py")]
        before = copy.deepcopy((p, tasks))
        plan.plan_batch(p, tasks)
        self.assertEqual((p, tasks), before)

    def test_no_shell_or_network_call(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("shell")), \
             mock.patch("socket.socket", side_effect=AssertionError("network")):
            plan.demo()

    def test_cli_synthetic_only(self):
        with self.assertRaises(SystemExit):
            plan.main([])
        with self.assertRaises(SystemExit):
            plan.main(["--repo", "/home/example"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(plan.main(["--synthetic-only", "--json"]), 0)


if __name__ == "__main__":
    unittest.main()
