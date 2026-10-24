"""Tests for static GH-F1.5 agent preflight, using only disposable fixtures."""
import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "preflight_readonly_agents", ROOT / "scripts" / "preflight_readonly_agents.py"
)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)

NAMES = ("planner", "auditor")
TOOLS = "Read, Grep, Glob"
DENIALS = "Bash, Write, Edit, NotebookEdit, Agent, WebFetch, WebSearch"


def materialized(name):
    return (
        "---\n"
        f"name: {name}\n"
        f"description: Neutral read-only {name} for synthetic testing.\n"
        f"tools: {TOOLS}\n"
        f"disallowedTools: {DENIALS}\n"
        "model: sonnet\n"
        "effort: medium\n"
        "---\n"
        "# Read-only agent\n"
        "No execution, writing, or network.\n"
    )


def source(name):
    return (
        "---\n"
        f"name: {name}\n"
        "mode: read-only\n"
        "forbidden_actions:\n"
        "  - write_files\n"
        "allowed_actions:\n"
        "  - {op: read_repository, level: A0}\n"
        "---\n"
        "Read-only synthetic source.\n"
    )


class ReadonlyPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pilot-static-preflight-")
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        for name in NAMES:
            self.write(f".claude/agents/{name}.md", materialized(name))
            self.write(f"agents/{name}/AGENT.md", source(name))

    def write(self, rel, data):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding="utf-8")

    def blocked(self):
        with self.assertRaises(preflight.PreflightError):
            preflight.validate(self.root)

    def test_passes_structural_preflight_without_approving_pilot(self):
        result = preflight.validate(self.root)
        self.assertEqual(result["status"], "CONFIG_OK")
        self.assertEqual(len(result["agents"]), 2)
        for key in ("agent_execution_authorized", "tool_access_effectively_verified",
                    "filesystem_isolation_verified", "network_isolation_verified",
                    "sandbox_fixture_verified"):
            self.assertIs(result[key], False)
        self.assertEqual(result["pilot_acceptance"], "PENDING")

    def test_unexpected_implementer_is_blocked(self):
        self.write(".claude/agents/implementer.md", materialized("implementer"))
        self.blocked()

    def test_unexpected_agent_name_is_blocked(self):
        self.write(".claude/agents/rogue.md", "a")
        self.blocked()

    def test_missing_agent_file_blocked(self):
        (self.root / ".claude/agents/planner.md").unlink()
        self.blocked()

    def test_missing_neutral_source_blocked(self):
        (self.root / "agents/planner/AGENT.md").unlink()
        self.blocked()

    def test_materialized_symlink_blocked(self):
        (self.root / ".claude/agents/planner.md").unlink()
        (self.root / ".claude/agents/planner.md").symlink_to(self.root / "agents/planner/AGENT.md")
        self.blocked()

    def test_source_symlink_blocked(self):
        (self.root / "agents/planner/AGENT.md").unlink()
        (self.root / "agents/planner/AGENT.md").symlink_to(self.root / ".claude/agents/planner.md")
        self.blocked()

    def test_symlinked_agents_dir_blocked(self):
        d = self.root / ".claude/agents"
        moved = self.root / "fake"
        d.rename(moved)
        d.symlink_to(moved, target_is_directory=True)
        self.blocked()

    def test_write_tool_in_allowlist_blocked(self):
        s = materialized("auditor").replace(f"tools: {TOOLS}", f"tools: {TOOLS}, Write")
        self.write(".claude/agents/auditor.md", s)
        self.blocked()

    def test_bash_tool_in_allowlist_blocked(self):
        s = materialized("planner").replace(f"tools: {TOOLS}", "tools: Read, Bash")
        self.write(".claude/agents/planner.md", s)
        self.blocked()

    def test_missing_webfetch_denial_blocked(self):
        s = materialized("planner").replace(", WebFetch, WebSearch", ", WebSearch")
        self.write(".claude/agents/planner.md", s)
        self.blocked()

    def test_missing_bash_denial_blocked(self):
        s = materialized("auditor").replace("Bash, ", "")
        self.write(".claude/agents/auditor.md", s)
        self.blocked()

    def test_duplicate_frontmatter_key_blocked(self):
        s = materialized("planner").replace("model: sonnet\n", "model: sonnet\nmodel: opus\n")
        self.write(".claude/agents/planner.md", s)
        self.blocked()

    def test_permission_mode_in_frontmatter_blocked(self):
        s = materialized("planner").replace("model: sonnet\n", "permissionMode: bypassPermissions\nmodel: sonnet\n")
        self.write(".claude/agents/planner.md", s)
        self.blocked()

    def test_wrong_agent_name_blocked(self):
        self.write(".claude/agents/planner.md", materialized("auditor"))
        self.blocked()

    def test_empty_materialized_body_blocked(self):
        self.write(".claude/agents/planner.md", materialized("planner").rsplit("---\n", 1)[0] + "---\n")
        self.blocked()

    def test_neutral_source_escalation_blocked(self):
        self.write("agents/planner/AGENT.md", source("planner").replace("level: A0", "level: A2"))
        self.blocked()

    def test_neutral_source_write_mode_blocked(self):
        self.write("agents/auditor/AGENT.md", source("auditor").replace("mode: read-only", "mode: write-scoped"))
        self.blocked()

    def test_neutral_forbidden_write_required(self):
        self.write("agents/planner/AGENT.md", source("planner").replace("  - write_files\n", ""))
        self.blocked()

    def test_bad_model_blocked(self):
        self.write(".claude/agents/planner.md", materialized("planner").replace("model: sonnet", "model: opus"))
        self.blocked()


if __name__ == "__main__":
    unittest.main()
