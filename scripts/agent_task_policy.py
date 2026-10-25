#!/usr/bin/env python3
"""GH-F1.10: pure, offline task-policy preview. NOT an authorization boundary.

Neither accesses the filesystem nor launches agents, models, network, Git or SRT.
A matching text path and an apparently affordable quote are NOT authorization.
Only a future trusted enforcer with verified root FDs, reservations, isolation,
human approvals and provider-side cost ledger can execute anything.
"""
import argparse
import json

ROLES = frozenset(("planner", "implementer", "auditor"))
SPECIALTIES = frozenset(("general", "frontend", "backend", "database", "devops",
                         "security", "qa", "architecture", "ui-ux", "apis",
                         "performance", "documentation", "management"))
ACTIONS = frozenset(("read", "write"))
COMPLEXITY = frozenset(("routine", "intermediate", "complex", "critical", "promising"))
PROVIDERS = frozenset(("local", "cloud"))
WORKSPACE_FIELDS = frozenset(("version", "workspace_id", "editable", "read_only",
                              "protected", "cloud_task_cap_cents",
                              "cloud_day_cap_cents", "cloud_project_cap_cents"))
REQUEST_FIELDS = frozenset(("task_id", "role", "specialty", "action", "paths",
                            "provider", "complexity", "local_available",
                            "estimated_cloud_cents", "spent_today_cents",
                            "spent_project_cents"))
SENSITIVE_COMPONENTS = frozenset((".git", ".claude", ".ssh", ".env", "id_rsa", "id_ed25519"))


class PolicyDenied(ValueError):
    """Invalid or ambiguous policy/input, without leaking file content."""


def _record(value, fields):
    if type(value) is not dict or set(value) != fields:
        raise PolicyDenied("invalid_schema")


def _name(value, limit=96):
    if (type(value) is not str or not value or len(value) > limit
            or not all(c.isascii() and (c.isalnum() or c in "-_") for c in value)):
        raise PolicyDenied("invalid_identifier")
    return value


def _path(value):
    """Only textual POSIX-relative path validation; never opens or resolves it."""
    if type(value) is not str or not 1 <= len(value) <= 1024:
        raise PolicyDenied("invalid_path")
    if value.startswith("/") or "\\" in value or "\x00" in value:
        raise PolicyDenied("invalid_path")
    parts = value.split("/")
    if any(not item or item in (".", "..") or len(item) > 255
           or any(ord(ch) < 32 for ch in item) for item in parts):
        raise PolicyDenied("invalid_path")
    try:
        value.encode("utf-8", "strict")
    except UnicodeError:
        raise PolicyDenied("invalid_path") from None
    return value


def _paths(value, *, nonempty=False):
    if (type(value) is not list or len(value) > 32
            or (nonempty and not value)):
        raise PolicyDenied("invalid_paths")
    result = tuple(_path(p) for p in value)
    if len(set(result)) != len(result):
        raise PolicyDenied("duplicate_path")
    return result


def _money(value):
    if type(value) is not int or not 0 <= value <= 100_000_000:
        raise PolicyDenied("invalid_budget")
    return value


def _under(path, prefix):
    return path == prefix or path.startswith(prefix + "/")


def _sensitive(path):
    return any(p in SENSITIVE_COMPONENTS or p.startswith(".env.") or p.endswith(".pem")
               for p in path.split("/"))


def validate_policy(policy):
    _record(policy, WORKSPACE_FIELDS)
    if policy["version"] != 1 or type(policy["version"]) is not int:
        raise PolicyDenied("unsupported_policy")
    _name(policy["workspace_id"])
    editable = _paths(policy["editable"], nonempty=True)
    readonly = _paths(policy["read_only"])
    protected = _paths(policy["protected"])
    for cap in ("cloud_task_cap_cents", "cloud_day_cap_cents", "cloud_project_cap_cents"):
        _money(policy[cap])
    # Overlapping grants can silently increase privileges; reject all ambiguous grants.
    for a in editable:
        if any(_under(a, r) or _under(r, a) for r in readonly):
            raise PolicyDenied("overlapping_grants")
    return editable, readonly, protected


def _validate_request(req):
    _record(req, REQUEST_FIELDS)
    _name(req["task_id"])
    for key, values in (("role", ROLES), ("specialty", SPECIALTIES),
                        ("action", ACTIONS), ("complexity", COMPLEXITY),
                        ("provider", PROVIDERS)):
        if type(req[key]) is not str or req[key] not in values:
            raise PolicyDenied("invalid_request")
    if type(req["local_available"]) is not bool:
        raise PolicyDenied("invalid_request")
    paths = _paths(req["paths"], nonempty=True)
    for key in ("spent_today_cents", "spent_project_cents"):
        _money(req[key])
    estimate = req["estimated_cloud_cents"]
    if estimate is not None:
        _money(estimate)
    if req["provider"] == "local" and estimate is not None:
        raise PolicyDenied("invalid_request")
    return paths


def evaluate(policy, request):
    """Return conservative task intake advice, NEVER an execution grant."""
    editable, readonly, protected = validate_policy(policy)
    paths = _validate_request(request)
    reasons = []
    for path in paths:
        if _sensitive(path) or any(_under(path, p) or _under(p, path)
                                   for p in protected):
            reasons.append("PROTECTED_PATH")
        elif request["action"] == "write":
            if request["role"] != "implementer":
                reasons.append("ROLE_CANNOT_WRITE")
            elif not any(_under(path, p) for p in editable):
                reasons.append("WRITE_OUTSIDE_SELECTED_SCOPE")
        elif not any(_under(path, p) for p in editable + readonly):
            reasons.append("READ_OUTSIDE_SELECTED_SCOPE")
    reasons = sorted(set(reasons))
    route = "BLOCKED"
    if not reasons:
        if request["provider"] == "local":
            if request["local_available"]:
                route = "LOCAL_PROPOSED"
            else:
                reasons.append("LOCAL_UNAVAILABLE_NO_CLOUD_FALLBACK")
        else:
            estimate = request["estimated_cloud_cents"]
            if estimate is None:
                reasons.append("CLOUD_COST_UNKNOWN")
            elif (estimate > policy["cloud_task_cap_cents"]
                  or estimate + request["spent_today_cents"] > policy["cloud_day_cap_cents"]
                  or estimate + request["spent_project_cents"] > policy["cloud_project_cap_cents"]):
                reasons.append("CLOUD_ESTIMATE_EXCEEDS_CAP")
            else:
                route = "CLOUD_REVIEW_REQUIRED"
                reasons.append("OWNER_APPROVAL_REQUIRED")
                reasons.append("SEPARATE_DATA_TRANSFER_APPROVAL_REQUIRED")
                if request["complexity"] in ("routine", "intermediate"):
                    reasons.append("CLOUD_DISCOURAGED_FOR_ROUTINE_TASK")
    return {
        "mode": "advisory_only", "workspace_id": policy["workspace_id"],
        "task_id": request["task_id"], "route": route,
        "textual_scope_valid": not any(x in reasons for x in
            ("PROTECTED_PATH", "ROLE_CANNOT_WRITE", "WRITE_OUTSIDE_SELECTED_SCOPE",
             "READ_OUTSIDE_SELECTED_SCOPE")),
        "reasons": sorted(set(reasons)),
        "local_first": True, "cloud_default": "DENY",
        "root_fd_verified": False, "filesystem_isolation_verified": False,
        "budget_ledger_verified": False, "reservation_verified": False,
        "cloud_call_authorized": False, "data_transfer_authorized": False,
        "agent_execution_authorized": False, "file_operations_authorized": False,
    }


def demo():
    """Entirely invented workspace and task. No caller-supplied path or model calls."""
    policy = {"version": 1, "workspace_id": "synthetic-demo",
              "editable": ["ExampleProject/src"], "read_only": ["ExampleProject/docs"],
              "protected": ["ExampleProject/src/locked"],
              "cloud_task_cap_cents": 50, "cloud_day_cap_cents": 200,
              "cloud_project_cap_cents": 600}
    task = {"task_id": "TASK-DEMO", "role": "implementer", "specialty": "backend",
            "action": "write", "paths": ["ExampleProject/src/api.py"],
            "provider": "local", "complexity": "routine", "local_available": True,
            "estimated_cloud_cents": None, "spent_today_cents": 0,
            "spent_project_cents": 0}
    return evaluate(policy, task)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline advisory-only task-policy demo")
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = demo()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"{result['route']} — advisory only; agents and cloud remain blocked")
    return 0 if result["route"] == "LOCAL_PROPOSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
