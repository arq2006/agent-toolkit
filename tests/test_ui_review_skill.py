"""Offline policy and negative-case tests for the first neutral UI review skill."""
import copy
import importlib.util
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MOD = ROOT / "scripts" / "validate_ui_review_skill.py"
SPEC = importlib.util.spec_from_file_location("ui_skill_validator", MOD)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
SOURCE = ROOT / "skills" / "ui-design-review-readonly" / "SKILL.md"
CONTRACT = ROOT / "skills" / "ui-design-review-readonly" / "contract.yaml"


class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def assert_blocked(self, source=None, contract=None, directory="ui-design-review-readonly"):
        with self.assertRaises(VALIDATOR.SkillContractError):
            VALIDATOR.validate(source if source is not None else self.source,
                               contract if contract is not None else self.contract,
                               directory=directory)

    def edited(self):
        return copy.deepcopy(self.contract)

    def test_valid_a0_skill_contract(self):
        result = VALIDATOR.validate(self.source, self.contract)
        self.assertEqual(result["status"], "VALID")
        self.assertTrue(result["source_only"])
        self.assertFalse(result["materialized"])
        self.assertFalse(result["runtime_isolation_tested"])

    def test_status_cannot_activate(self):
        d = self.edited()
        d["status"] = "ACTIVE"
        self.assert_blocked(contract=d)

    def test_permissions_cannot_add_write(self):
        d = self.edited()
        d["permissions"][0]["level"] = "A1"
        self.assert_blocked(contract=d)

    def test_permissions_cannot_add_unknown_operation(self):
        d = self.edited()
        d["permissions"].append({"op": "execute_shell", "level": "A0"})
        self.assert_blocked(contract=d)

    def test_tools_cannot_include_external_runtime(self):
        d = self.edited()
        d["tools"].append("T-10")
        self.assert_blocked(contract=d)

    def test_protected_paths_cannot_be_deleted(self):
        d = self.edited()
        d["protected_paths"].remove("docs/security/")
        self.assert_blocked(contract=d)

    def test_no_network_is_mandatory(self):
        d = self.edited()
        d["constraints"].remove("no_network")
        self.assert_blocked(contract=d)

    def test_no_subprocess_is_mandatory(self):
        d = self.edited()
        d["constraints"].remove("no_subprocess")
        self.assert_blocked(contract=d)

    def test_no_auto_activation_is_mandatory(self):
        d = self.edited()
        d["constraints"].remove("no_automatic_activation")
        self.assert_blocked(contract=d)

    def test_permission_conflict_case_required(self):
        d = self.edited()
        d["tests"].remove("permission_conflict")
        self.assert_blocked(contract=d)

    def test_negative_write_case_required(self):
        d = self.edited()
        d["tests"].remove("negative_refuses_write")
        self.assert_blocked(contract=d)

    def test_duplicate_test_cases_fail(self):
        d = self.edited()
        d["tests"].append("positive_readonly_review")
        self.assert_blocked(contract=d)

    def test_skill_name_must_match_directory(self):
        self.assert_blocked(directory="ui-design-review-other")

    def test_no_allowed_tools_in_frontmatter(self):
        changed = self.source.replace("metadata:\n", "allowed-tools: Bash(*)\nmetadata:\n", 1)
        self.assert_blocked(source=changed)

    def test_unrecognized_metadata_fails(self):
        changed = self.source.replace('  toolkit_contract_file: "contract.yaml"',
                                      '  toolkit_contract_file: "contract.yaml"\n  toolkit_grant: "yes"', 1)
        self.assert_blocked(source=changed)

    def test_non_string_metadata_fails(self):
        changed = self.source.replace('toolkit_version: "0.1.0"', "toolkit_version: 1", 1)
        self.assert_blocked(source=changed)

    def test_unquoted_description_fails(self):
        changed = self.source.replace('description: "', 'description: ', 1)
        self.assert_blocked(source=changed)

    def test_contract_link_cannot_escape_folder(self):
        changed = self.source.replace('toolkit_contract_file: "contract.yaml"',
                                      'toolkit_contract_file: "../../elsewhere"', 1)
        self.assert_blocked(source=changed)

    def test_contract_does_not_add_unreviewed_fields(self):
        d = self.edited()
        d["install_command"] = "curl ... | sh"
        self.assert_blocked(contract=d)

    def test_no_registered_runtime_installation(self):
        catalog = json.loads((ROOT / "skills" / "catalog.json").read_text(encoding="utf-8"))
        self.assertNotIn("ui-design-review-readonly", {s["id"] for s in catalog["skills"]})
        self.assertFalse((ROOT / ".claude" / "skills" / "ui-design-review-readonly").exists())

    def test_changelog_matches_skill_version(self):
        d = self.edited()
        d["changelog"][0]["version"] = "2.0.0"
        self.assert_blocked(contract=d)

    def test_body_cannot_be_empty(self):
        self.assert_blocked(source=self.source.split("\n---\n", 1)[0] + "\n---\n")


if __name__ == "__main__":
    unittest.main()
