#!/usr/bin/env python3
"""Validate the neutral A0-only UI skill contract without loading the skill.

The contract.yaml deliberately uses the JSON subset of YAML 1.2 so the
validator can use Python's standard library. This checks a fixed frontmatter
subset, not arbitrary YAML syntax, Claude discovery, or runtime isolation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "ui-design-review-readonly"
SKILL = SKILL_DIR / "SKILL.md"
CONTRACT = SKILL_DIR / "contract.yaml"
META = frozenset({
    "toolkit_contract_version", "toolkit_version",
    "toolkit_responsibility", "toolkit_contract_file",
})
PATHS = frozenset({"docs/references/", "docs/security/", "docs/CHECKSUMS.sha256"})
REQUIRED_TESTS = frozenset({
    "positive_readonly_review", "negative_refuses_write",
    "negative_refuses_network", "negative_refuses_subprocess",
    "permission_conflict", "negative_refuses_untrusted_instructions",
})
REQUIRED_CONSTRAINTS = frozenset({
    "no_writes", "no_network", "no_subprocess", "no_external_skills",
    "no_downloads", "no_hooks", "no_mcp", "no_secrets",
    "no_other_repositories", "no_unverified_claims",
    "no_automatic_activation", "external_content_untrusted",
})
OPS = frozenset({"read_repository", "analyze_diff", "report_findings"})
KEYS = frozenset({
    "contract_version", "skill", "status", "inputs", "outputs",
    "permissions", "tools", "constraints", "tests", "protected_paths",
    "changelog",
})


class SkillContractError(ValueError):
    """Malformed or permissive skill definition."""


def parse_frontmatter(src: str) -> tuple[dict, str]:
    if not src.startswith("---\n"):
        raise SkillContractError("YAML frontmatter required")
    sections = src.split("\n---\n", 1)
    if len(sections) != 2 or not sections[1].strip():
        raise SkillContractError("missing frontmatter terminator or instructions")
    header = sections[0][4:].splitlines()
    parsed: dict = {}
    in_metadata = False
    metadata: dict = {}
    for line in header:
        if not line.strip() or line.lstrip().startswith("#"):
            raise SkillContractError("blank lines and comments forbidden in checked subset")
        if line == "metadata:":
            if in_metadata or "metadata" in parsed:
                raise SkillContractError("duplicate metadata")
            in_metadata = True
            parsed["metadata"] = metadata
            continue
        if line.startswith("  "):
            if not in_metadata:
                raise SkillContractError("unexpected indentation")
            m = re.fullmatch(r'  (toolkit_[a-z_]+): (".*")', line)
            if not m or m[1] not in META or m[1] in metadata:
                raise SkillContractError("invalid metadata field")
            try:
                val = json.loads(m[2])
            except json.JSONDecodeError as exc:
                raise SkillContractError("invalid quoted metadata") from exc
            if not isinstance(val, str):
                raise SkillContractError("metadata must be string")
            metadata[m[1]] = val
            continue
        if in_metadata:
            raise SkillContractError("metadata must be last in this restricted subset")
        m = re.fullmatch(r"([a-z-]+): (.+)", line)
        if not m or m[1] not in {"name", "description"} or m[1] in parsed:
            raise SkillContractError("unsupported, duplicate or unsafe frontmatter key")
        if m[1] == "name":
            parsed["name"] = m[2]
        else:
            try:
                parsed["description"] = json.loads(m[2])
            except json.JSONDecodeError as exc:
                raise SkillContractError("description must be JSON-quoted YAML scalar") from exc
    if set(parsed) != {"name", "description", "metadata"} or set(metadata) != META:
        raise SkillContractError("missing required frontmatter fields")
    return parsed, sections[1]


def _string_list(item: object, name: str) -> list[str]:
    if (not isinstance(item, list) or not item
            or any(not isinstance(x, str) or not x for x in item)
            or len(item) != len(set(item))):
        raise SkillContractError(f"{name} must contain unique nonempty strings")
    return item


def validate(skill: str, contract: object, directory: str = "ui-design-review-readonly") -> dict:
    if not isinstance(skill, str) or not isinstance(contract, dict):
        raise SkillContractError("missing skill or contract")
    front, body = parse_frontmatter(skill)
    name = front["name"]
    if (not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
            or len(name) > 64 or name != directory or contract.get("skill") != name):
        raise SkillContractError("name must equal skill folder")
    description = front["description"]
    if not isinstance(description, str) or not 1 <= len(description) <= 1024:
        raise SkillContractError("description invalid")
    if not body.strip() or len(body.splitlines()) >= 500:
        raise SkillContractError("instruction body missing or too long")
    meta = front["metadata"]
    if meta["toolkit_contract_version"] != "0.1.0" or meta["toolkit_version"] != "0.1.0":
        raise SkillContractError("unrecognized contract or skill version")
    if meta["toolkit_contract_file"] != "contract.yaml" or not meta["toolkit_responsibility"]:
        raise SkillContractError("contract link or responsibility missing")
    if set(contract) != KEYS or contract["contract_version"] != "0.1.0":
        raise SkillContractError("contract schema invalid")
    if contract["status"] != "SOURCE_ONLY_NOT_MATERIALIZED":
        raise SkillContractError("activation must remain disabled")
    for key in ("inputs", "outputs", "tools", "constraints", "tests", "protected_paths"):
        _string_list(contract.get(key), key)
    if contract["tools"] != ["T-01"]:
        raise SkillContractError("only inventoried Git read operations allowed as tools")
    if not REQUIRED_TESTS <= set(contract["tests"]) or not REQUIRED_CONSTRAINTS <= set(contract["constraints"]):
        raise SkillContractError("mandatory negative tests and constraints missing")
    if set(contract["protected_paths"]) != PATHS:
        raise SkillContractError("protected paths altered")
    permissions = contract["permissions"]
    if (not isinstance(permissions, list) or len(permissions) != len(OPS)
            or any(not isinstance(p, dict) or set(p) != {"op", "level"}
                   or p["op"] not in OPS or p["level"] != "A0" for p in permissions)
            or {p["op"] for p in permissions} != OPS):
        raise SkillContractError("only three declared A0 operations allowed")
    changes = contract["changelog"]
    if (not isinstance(changes, list) or len(changes) != 1 or not isinstance(changes[0], dict)
            or set(changes[0]) != {"version", "date", "reason"}
            or changes[0]["version"] != "0.1.0"
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(changes[0]["date"]))
            or not isinstance(changes[0]["reason"], str) or not changes[0]["reason"]):
        raise SkillContractError("changelog invalid")
    return {
        "status": "VALID", "skill": name, "source_only": True,
        "permissions": ["A0"], "materialized": False,
        "external_code_executed": False, "runtime_isolation_tested": False,
        "parser": "restricted-frontmatter-and-json-subset-yaml-1.2",
    }


def main() -> int:
    try:
        skill = SKILL.read_text(encoding="utf-8")
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        result = validate(skill, contract)
        code = 0
    except (OSError, json.JSONDecodeError, SkillContractError, TypeError, KeyError, AttributeError) as exc:
        result = {"status": "INVALID", "error": str(exc), "permissions_granted": False}
        code = 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
