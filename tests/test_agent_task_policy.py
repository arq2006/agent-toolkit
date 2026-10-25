#!/usr/bin/env python3
"""Offline safety regressions: no agent, network, filesystem, cloud or Git calls."""
import copy
import importlib.util
import io
import pathlib
import unittest
from contextlib import redirect_stdout
from unittest import mock

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "agent_task_policy.py"
spec = importlib.util.spec_from_file_location("agent_task_policy", SCRIPT)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


def policy():
    return {"version": 1, "workspace_id": "synthetic-workspace",
            "editable": ["project/src"], "read_only": ["project/docs"],
            "protected": ["project/src/locked", "project/docs/private"],
            "cloud_task_cap_cents": 50, "cloud_day_cap_cents": 200,
            "cloud_project_cap_cents": 600}


def task(**changes):
    value = {"task_id": "TASK-001", "role": "implementer", "specialty": "backend",
             "action": "write", "paths": ["project/src/app.py"],
             "provider": "local", "complexity": "routine", "local_available": True,
             "estimated_cloud_cents": None, "spent_today_cents": 0,
             "spent_project_cents": 0}
    value.update(changes)
    return value


class PolicyTests(unittest.TestCase):
    def evaluate(self, **kwargs):
        return P.evaluate(policy(), task(**kwargs))

    def test_local_default_is_only_a_proposal(self):
        result = self.evaluate()
        self.assertEqual(result["route"], "LOCAL_PROPOSED")
        self.assertTrue(result["textual_scope_valid"])
        self.assertFalse(result["agent_execution_authorized"])
        self.assertFalse(result["file_operations_authorized"])
        self.assertFalse(result["root_fd_verified"])
        self.assertFalse(result["filesystem_isolation_verified"])

    def test_local_unavailable_never_silently_uses_cloud(self):
        result = self.evaluate(local_available=False)
        self.assertEqual(result["route"], "BLOCKED")
        self.assertIn("LOCAL_UNAVAILABLE_NO_CLOUD_FALLBACK", result["reasons"])

    def test_complex_cloud_needs_separate_approvals(self):
        result = self.evaluate(provider="cloud", complexity="critical", estimated_cloud_cents=30)
        self.assertEqual(result["route"], "CLOUD_REVIEW_REQUIRED")
        self.assertIn("OWNER_APPROVAL_REQUIRED", result["reasons"])
        self.assertIn("SEPARATE_DATA_TRANSFER_APPROVAL_REQUIRED", result["reasons"])
        self.assertFalse(result["cloud_call_authorized"])
        self.assertFalse(result["data_transfer_authorized"])
        self.assertFalse(result["budget_ledger_verified"])

    def test_routine_cloud_discouraged_even_if_cheap(self):
        result = self.evaluate(provider="cloud", estimated_cloud_cents=1)
        self.assertIn("CLOUD_DISCOURAGED_FOR_ROUTINE_TASK", result["reasons"])
        self.assertEqual(result["route"], "CLOUD_REVIEW_REQUIRED")

    def test_promising_cloud_still_needs_approval(self):
        result = self.evaluate(provider="cloud", complexity="promising", estimated_cloud_cents=10)
        self.assertEqual(result["route"], "CLOUD_REVIEW_REQUIRED")
        self.assertNotIn("CLOUD_DISCOURAGED_FOR_ROUTINE_TASK", result["reasons"])

    def test_cloud_unknown_quote_fails_closed(self):
        result = self.evaluate(provider="cloud")
        self.assertEqual(result["route"], "BLOCKED")
        self.assertIn("CLOUD_COST_UNKNOWN", result["reasons"])

    def test_over_budget_each_cap_denied(self):
        for kwargs in ({"estimated_cloud_cents": 51},
                       {"estimated_cloud_cents": 20, "spent_today_cents": 181},
                       {"estimated_cloud_cents": 20, "spent_project_cents": 581}):
            result = self.evaluate(provider="cloud", **kwargs)
            self.assertEqual(result["route"], "BLOCKED")
            self.assertIn("CLOUD_ESTIMATE_EXCEEDS_CAP", result["reasons"])

    def test_zero_budget_denies_nonzero_cloud(self):
        rule = policy()
        rule["cloud_task_cap_cents"] = 0
        result = P.evaluate(rule, task(provider="cloud", estimated_cloud_cents=1))
        self.assertEqual(result["route"], "BLOCKED")

    def test_readonly_role_cannot_write(self):
        for role in ("planner", "auditor"):
            result = self.evaluate(role=role)
            self.assertEqual(result["route"], "BLOCKED")
            self.assertIn("ROLE_CANNOT_WRITE", result["reasons"])

    def test_readonly_path_cannot_be_written(self):
        result = self.evaluate(paths=["project/docs/README.md"])
        self.assertIn("WRITE_OUTSIDE_SELECTED_SCOPE", result["reasons"])

    def test_read_permission_can_include_readonly(self):
        result = self.evaluate(role="planner", action="read", paths=["project/docs/README.md"])
        self.assertEqual(result["route"], "LOCAL_PROPOSED")

    def test_path_outside_selected_scope_denied_for_read_and_write(self):
        for action in ("read", "write"):
            result = self.evaluate(action=action, paths=["other-project/file.py"])
            self.assertEqual(result["route"], "BLOCKED")

    def test_protected_overrides_grant(self):
        for p in ("project/src/locked", "project/src/locked/x.py", "project/docs/private/x"):
            result = self.evaluate(paths=[p])
            self.assertIn("PROTECTED_PATH", result["reasons"])

    def test_protected_descendant_blocks_grant_to_parent_directory(self):
        # Reading/listing an ancestor would expose protected children.
        for path in ("project/src", "project/docs"):
            r = self.evaluate(action="read", role="planner", paths=[path])
            self.assertEqual(r["route"], "BLOCKED")
            self.assertIn("PROTECTED_PATH", r["reasons"])

    def test_protected_sensitive_components_in_subfolders(self):
        for p in ("project/src/.env", "project/src/.env.dev", "project/src/.git/config",
                  "project/src/.claude/settings.json", "project/src/private.pem"):
            result = self.evaluate(paths=[p])
            self.assertEqual(result["route"], "BLOCKED")
            self.assertIn("PROTECTED_PATH", result["reasons"])

    def test_prefix_scope_does_not_match_sibling(self):
        result = self.evaluate(paths=["project/src-not-authorized/code.py"])
        self.assertIn("WRITE_OUTSIDE_SELECTED_SCOPE", result["reasons"])

    def test_invalid_paths_no_normalization(self):
        for p in ("../outside", "project/src/../outside", "project//src", "project/./src",
                  "/root/secret", "C:\\secrets", "hello\\x", "project/src/", "\x00", "\ud800"):
            with self.assertRaises(P.PolicyDenied):
                self.evaluate(paths=[p])

    def test_invalid_unknown_field_cannot_approve(self):
        req = task(approved=True)
        with self.assertRaises(P.PolicyDenied):
            P.evaluate(policy(), req)
        req = task(data_transfer_authorized=True)
        with self.assertRaises(P.PolicyDenied):
            P.evaluate(policy(), req)

    def test_invalid_role_or_provider(self):
        for k, value in (("role", "orchestrator"), ("provider", "free_cloud"),
                         ("complexity", "emergency"), ("action", "merge"),
                         ("specialty", "admin")):
            with self.assertRaises(P.PolicyDenied):
                self.evaluate(**{k: value})

    def test_policy_rejects_overlapping_grants(self):
        rule = policy()
        rule["read_only"] = ["project"]
        with self.assertRaises(P.PolicyDenied):
            P.evaluate(rule, task())

    def test_policy_rejects_unknown_fields_or_invalid_root_id(self):
        for change in ({"workspace_root": "/home/user"}, {"version": 2},
                       {"workspace_id": "/tmp/secrets"}):
            p = policy()
            p.update(change)
            with self.assertRaises(P.PolicyDenied):
                P.evaluate(p, task())

    def test_bool_must_not_be_accepted_as_integer_budget(self):
        for field in ("cloud_task_cap_cents", "cloud_day_cap_cents"):
            p = policy()
            p[field] = True
            with self.assertRaises(P.PolicyDenied):
                P.evaluate(p, task())
        with self.assertRaises(P.PolicyDenied):
            self.evaluate(spent_today_cents=True)

    def test_estimate_not_allowed_with_local_provider(self):
        with self.assertRaises(P.PolicyDenied):
            self.evaluate(estimated_cloud_cents=1)

    def test_result_does_not_mutate_inputs(self):
        p, req = policy(), task()
        original = (copy.deepcopy(p), copy.deepcopy(req))
        P.evaluate(p, req)
        self.assertEqual((p, req), original)

    def test_one_denied_path_stops_whole_task(self):
        r = self.evaluate(paths=["project/src/app.py", "project/src/locked/password"])
        self.assertEqual(r["route"], "BLOCKED")

    def test_demo_never_grants_execution(self):
        r = P.demo()
        self.assertEqual(r["workspace_id"], "synthetic-demo")
        self.assertEqual(r["route"], "LOCAL_PROPOSED")
        self.assertFalse(r["agent_execution_authorized"])

    def test_cli_requires_synthetic_only(self):
        with self.assertRaises(SystemExit):
            P.main([])
        with self.assertRaises(SystemExit):
            P.main(["--workspace", "/home/example"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(P.main(["--synthetic-only", "--json"]), 0)

    def test_no_network_or_shell_invocation_from_evaluation(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("spawned")), \
             mock.patch("socket.socket", side_effect=AssertionError("network")):
            self.evaluate()


if __name__ == "__main__":
    unittest.main()
