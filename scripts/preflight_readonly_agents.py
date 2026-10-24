#!/usr/bin/env python3
"""GH-F1.5 preflight of *declared* read-only agents; no agent launch.

Does not execute Claude, Git, scripts, network, or anything outside the supplied
repository tree. Static frontmatter is not an effective-permission proof.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ("planner", "auditor")
REQUIRED_TOOLS = frozenset({"Read", "Grep", "Glob"})
REQUIRED_DENIALS = frozenset({
    "Bash", "Write", "Edit", "NotebookEdit", "Agent", "WebFetch", "WebSearch",
})
HEADER_KEYS = frozenset({"name", "description", "tools", "disallowedTools", "model", "effort"})


class PreflightError(ValueError):
    """A declared read-only pilot prerequisite failed."""


def _read_checked(root: Path, relative: str) -> str:
    path = root
    if path.is_symlink():
        raise PreflightError("repository root is a symlink")
    for name in Path(relative).parts:
        if name in ("", ".", ".."):
            raise PreflightError(f"invalid internal path for {relative}")
        path = path / name
        if path.is_symlink():
            raise PreflightError(f"symlink in configured file: {relative}")
    if not path.is_file():
        raise PreflightError(f"required file unavailable: {relative}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PreflightError(f"cannot read required file: {relative}") from exc


def _parse_header(text: str, name: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise PreflightError(f"{name}: missing frontmatter")
    parts = text.split("\n---\n", 1)
    if len(parts) != 2 or not parts[1].strip():
        raise PreflightError(f"{name}: unterminated frontmatter or empty body")
    fields: dict[str, str] = {}
    for row in parts[0][4:].splitlines():
        match = re.fullmatch(r"([A-Za-z]+): (.+)", row)
        if not match or match[1] not in HEADER_KEYS or match[1] in fields:
            raise PreflightError(f"{name}: unrecognized/duplicate frontmatter")
        fields[match[1]] = match[2].strip()
    if set(fields) != HEADER_KEYS or fields["name"] != name:
        raise PreflightError(f"{name}: wrong name or missing header fields")
    if not fields["description"] or fields["model"] != "sonnet" or fields["effort"] != "medium":
        raise PreflightError(f"{name}: model/effort/description changed")
    def values(k: str) -> frozenset[str]:
        items = [x.strip() for x in fields[k].split(",")]
        if not items or any(not x for x in items) or len(set(items)) != len(items):
            raise PreflightError(f"{name}: duplicate/empty tool name")
        return frozenset(items)
    if values("tools") != REQUIRED_TOOLS:
        raise PreflightError(f"{name}: read-only tools do not match declared allowlist")
    if values("disallowedTools") != REQUIRED_DENIALS:
        raise PreflightError(f"{name}: prohibited tools do not match contract")
    return fields


def validate(root: Path = ROOT) -> dict:
    """Read only the two known agent files and their neutral sources."""
    root = Path(root)
    # The pilot intentionally allows no extra materialized agents in this scope.
    agents_dir = root / ".claude" / "agents"
    if agents_dir.is_symlink() or not agents_dir.is_dir():
        raise PreflightError("agent materialization directory missing or symlinked")
    try:
        entries = sorted(p.name for p in agents_dir.iterdir())
    except OSError as exc:
        raise PreflightError("unable to inspect materialized agent names") from exc
    if entries != ["auditor.md", "planner.md"]:
        raise PreflightError("unexpected or missing materialized agent files")
    details = []
    for name in AGENTS:
        md = _read_checked(root, f".claude/agents/{name}.md")
        header = _parse_header(md, name)
        neutral = _read_checked(root, f"agents/{name}/AGENT.md")
        # Narrow source check, not full YAML semantic validation.
        first = neutral.split("\n---\n", 1)
        if (not neutral.startswith("---\n") or len(first) != 2
                or not re.search(r"(?m)^mode: read-only$", first[0])
                or not re.search(r"(?m)^name: " + re.escape(name) + r"$", first[0])
                or not re.search(r"(?m)^  - write_files$", first[0])
                or re.search(r"(?m)^\s+- \{op: [^}]+level: A[123]\}", first[0])):
            raise PreflightError(f"{name}: neutral contract is not declared read-only")
        details.append({"name": name, "declared_tools": list(sorted(REQUIRED_TOOLS)),
                        "denied_tools": list(sorted(REQUIRED_DENIALS)),
                        "version": "declared-only"})
    return {
        "status": "CONFIG_OK", "agents": details,
        "agent_execution_authorized": False,
        "tool_access_effectively_verified": False,
        "filesystem_isolation_verified": False,
        "network_isolation_verified": False,
        "sandbox_fixture_verified": False,
        "pilot_acceptance": "PENDING",
        "next_gate": "Review PR #9 against ADR-011; prove host boundaries and tool access before real pilot.",
    }


def main() -> int:
    try:
        result = validate()
        exit_code = 0
    except (PreflightError, OSError) as exc:
        result = {"status": "CONFIG_INVALID", "reason": str(exc),
                  "agent_execution_authorized": False, "pilot_acceptance": "BLOCKED"}
        exit_code = 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
