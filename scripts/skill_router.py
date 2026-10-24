#!/usr/bin/env python3
"""Read-only skill catalog validation and advisory routing (GH-F2.0).

Reads the checked-in JSON catalog. Never installs, imports, executes or activates
third-party skills, agents, hooks, MCP or any other tools.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CATALOG = Path(__file__).resolve().parent.parent / "skills" / "catalog.json"
ROLES = frozenset({
    "ui-ux", "frontend", "backend", "database", "devops", "security", "qa",
    "architecture", "api", "performance", "documentation", "management",
})
KINDS = frozenset({"skill", "plugin"})
STATES = frozenset({"candidate", "reported-global", "disabled"})
RISKS = frozenset({"low", "medium", "high"})


class CatalogError(ValueError):
    """Invalid or unsafe catalog input."""


def _validate_list(items: object, field: str, allowed: frozenset[str] | None = None) -> list[str]:
    if not isinstance(items, list) or not items or any(not isinstance(v, str) or not v for v in items):
        raise CatalogError(f"{field}: expected nonempty list of strings")
    if len(items) != len(set(items)):
        raise CatalogError(f"{field}: duplicates")
    if allowed is not None and not set(items) <= allowed:
        raise CatalogError(f"{field}: unknown values {sorted(set(items) - allowed)}")
    return items


def validate(data: object) -> dict:
    if not isinstance(data, dict) or set(data) != {"schema_version", "mode", "roles", "skills", "external_integrations"}:
        raise CatalogError("wrong top-level schema")
    if data["schema_version"] != 1 or type(data["schema_version"]) is not int:
        raise CatalogError("unsupported catalog schema")
    if data["mode"] != "advisory-only":
        raise CatalogError("activation mode must be advisory-only")
    roles = _validate_list(data["roles"], "roles", ROLES)
    if set(roles) != ROLES:
        raise CatalogError("roles must match the 12 proposed GH-F1.7 specialists")
    if not isinstance(data["skills"], list) or not data["skills"]:
        raise CatalogError("missing skills")
    ids = set()
    for item in data["skills"]:
        expected = {"id", "kind", "source", "license_reported", "state", "risk", "roles", "tags", "priority", "approved_for_use", "toolkit_installed"}
        if not isinstance(item, dict) or set(item) != expected:
            raise CatalogError("skill entry has missing/unknown fields")
        name = item["id"]
        if (not isinstance(name, str) or not name or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in name)
                or name.startswith("-") or name.endswith("-") or "--" in name or name in ids):
            raise CatalogError(f"invalid or duplicate skill id: {name!r}")
        ids.add(name)
        if item["kind"] not in KINDS or item["state"] not in STATES or item["risk"] not in RISKS:
            raise CatalogError(f"invalid kind/state/risk: {name}")
        if (not isinstance(item["source"], str) or not item["source"].startswith("https://")
                or any(ch.isspace() for ch in item["source"])):
            raise CatalogError(f"source must be a nonempty HTTPS URL: {name}")
        if not isinstance(item["license_reported"], str) or not item["license_reported"]:
            raise CatalogError(f"license_reported missing: {name}")
        if type(item["priority"]) is not int or not (0 <= item["priority"] <= 100):
            raise CatalogError(f"priority invalid: {name}")
        if item["approved_for_use"] is not False or item["toolkit_installed"] is not False:
            raise CatalogError(f"unapproved or installed skill in advisory catalog: {name}")
        _validate_list(item["roles"], f"{name}.roles", ROLES)
        for tag in _validate_list(item["tags"], f"{name}.tags"):
            if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_" for ch in tag):
                raise CatalogError(f"invalid tag {tag!r}: {name}")
    if not isinstance(data["external_integrations"], list):
        raise CatalogError("external_integrations must be a list")
    for item in data["external_integrations"]:
        if (not isinstance(item, dict) or set(item) != {"id", "kind", "source", "status"}
                or item["kind"] not in {"framework", "service", "reference"}
                or item["status"] != "research-only" or not isinstance(item["source"], str)
                or not item["source"].startswith("https://") or item["id"] in ids):
            raise CatalogError("invalid external integration candidate")
        ids.add(item["id"])
    return data


def load_catalog(path: Path = CATALOG) -> dict:
    try:
        return validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"catalog unavailable/invalid: {type(exc).__name__}") from exc


def recommend(data: dict, role: str, tag: str, limit: int = 2) -> dict:
    validate(data)
    if role not in ROLES:
        raise CatalogError("unknown specialty")
    if not isinstance(tag, str) or not tag or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in tag):
        raise CatalogError("invalid task tag")
    if type(limit) is not int or not 1 <= limit <= 3:
        raise CatalogError("max recommendations must be between 1 and 3")
    candidates = [item for item in data["skills"] if role in item["roles"] and tag in item["tags"]
                  and item["state"] != "disabled"]
    candidates.sort(key=lambda item: (-item["priority"], item["id"]))
    return {
        "mode": "advisory-only", "role": role, "task_tag": tag,
        "proposals": [{"id": i["id"], "state": i["state"], "risk": i["risk"],
                       "approved_for_use": False, "toolkit_installed": False}
                      for i in candidates[:limit]],
        "agents_executed": False, "skills_loaded": False,
        "authorization_granted": False,
        "notice": "Suggestions only. Human review of source, license, version, scope and installation required.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and suggest skills WITHOUT executing anything")
    parser.add_argument("action", choices=["validate", "suggest"])
    parser.add_argument("--agent", default=None, help="Proposed GH-F1.7 specialty")
    parser.add_argument("--tag", default=None, help="Explicit task category; no prompt scanning")
    parser.add_argument("--max", type=int, default=2, dest="limit")
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog()
        if args.action == "suggest":
            if args.agent is None or args.tag is None:
                raise CatalogError("suggest requires --agent and --tag")
            output = recommend(catalog, args.agent, args.tag, args.limit)
        else:
            output = {"status": "VALID", "mode": "advisory-only", "skills": len(catalog["skills"]),
                      "integrations_not_skills": len(catalog["external_integrations"]),
                      "agents_executed": False, "skills_loaded": False}
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0
    except CatalogError as exc:
        print(json.dumps({"status": "INVALID", "error": str(exc), "activation_authorized": False}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
