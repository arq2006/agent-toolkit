"""GH-F2.1 draft skills review validation, no third-party code execution."""
import copy
import importlib.util
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validate_skill_reviews", ROOT / "scripts" / "validate_skill_reviews.py")
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)


class ReviewPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reviews = json.loads((ROOT / "skills" / "reviews" / "GH-F2-1-candidates.json").read_text())
        cls.catalog = json.loads((ROOT / "skills" / "catalog.json").read_text())

    def changed(self):
        return copy.deepcopy(self.reviews)

    def assert_refused(self, d, cat=None):
        with self.assertRaises(V.ReviewError):
            V.validate(d, cat or self.catalog)

    def test_valid_manifest_reports_no_execution(self):
        result = V.validate(self.reviews, self.catalog)
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["candidates"], 6)
        self.assertIs(result["permissions_granted"], False)
        self.assertIs(result["skills_executed"], False)

    def test_inconsistent_mode_refused(self):
        d = self.changed()
        d["mode"] = "auto-execute"
        self.assert_refused(d)

    def test_global_approval_refused(self):
        d = self.changed()
        d["global_policy"]["permissions_granted"] = True
        self.assert_refused(d)

    def test_install_authorization_refused(self):
        d = self.changed()
        d["global_policy"]["any_installation_authorized"] = True
        self.assert_refused(d)

    def test_third_party_execution_refused(self):
        d = self.changed()
        d["candidates"][0]["review"]["authorized_to_execute"] = True
        self.assert_refused(d)

    def test_skills_materialization_refused(self):
        d = self.changed()
        d["global_policy"]["materialize_claude_skills"] = True
        self.assert_refused(d)

    def test_review_draft_cannot_be_approved(self):
        d = self.changed()
        d["candidates"][0]["contract_proposal"]["status"] = "ACTIVE"
        self.assert_refused(d)

    def test_current_permissions_cannot_be_added(self):
        d = self.changed()
        d["candidates"][0]["contract_proposal"]["permissions_current"] = ["A1:write_files"]
        self.assert_refused(d)

    def test_unverified_license_cannot_be_declared_mit(self):
        d = self.changed()
        item = next(x for x in d["candidates"] if x["id"] == "web-design-guidelines")
        item["license"]["reported"] = "MIT"
        self.assert_refused(d)

    def test_remote_guideline_requires_pin(self):
        d = self.changed()
        item = next(x for x in d["candidates"] if x["id"] == "web-design-guidelines")
        item["external_source_pin"]["remote_rules_sha"] = "main"
        self.assert_refused(d)

    def test_missing_source_sha_refused(self):
        d = self.changed()
        d["candidates"][0]["source"]["commit_sha"] = ""
        self.assert_refused(d)

    def test_duplicated_candidate_refused(self):
        d = self.changed()
        d["candidates"][1] = copy.deepcopy(d["candidates"][0])
        self.assert_refused(d)

    def test_extra_role_refused(self):
        d = self.changed()
        d["candidates"][0]["contract_proposal"]["eligible_roles"].append("security")
        self.assert_refused(d)

    def test_protected_paths_mandatory(self):
        d = self.changed()
        d["candidates"][0]["contract_proposal"]["protected_paths"] = []
        self.assert_refused(d)

    def test_negative_permission_test_mandatory(self):
        d = self.changed()
        d["candidates"][0]["contract_proposal"]["tests"].remove("negative_refuse_tool_permission_conflict")
        self.assert_refused(d)

    def test_catalog_cannot_mark_skills_approved(self):
        cat = copy.deepcopy(self.catalog)
        cat["skills"][0]["approved_for_use"] = True
        self.assert_refused(self.reviews, cat)

    def test_unknown_candidate_refused(self):
        d = self.changed()
        d["candidates"][0]["id"] = "unknown-skill"
        self.assert_refused(d)

    def test_proposed_actions_must_be_a0(self):
        d = self.changed()
        d["candidates"][0]["contract_proposal"]["actions_proposed"] = ["A1:write"]
        self.assert_refused(d)

    def test_installation_stays_unverified(self):
        d = self.changed()
        d["candidates"][0]["review"]["toolkit_installed"] = True
        self.assert_refused(d)

    def test_external_source_not_local_path(self):
        d = self.changed()
        d["candidates"][0]["source"]["repository"] = "file:///etc"
        self.assert_refused(d)


if __name__ == "__main__":
    unittest.main()
