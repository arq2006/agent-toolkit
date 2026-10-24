"""Offline negative and positive tests for the GH-F2.0 advisory catalog."""
import copy
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("skill_router", ROOT / "scripts" / "skill_router.py")
router = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(router)


class SkillRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = router.load_catalog(ROOT / "skills" / "catalog.json")

    def test_catalog_accepted_and_not_executable(self):
        self.assertEqual(router.validate(self.catalog)["mode"], "advisory-only")
        self.assertTrue(all(i["approved_for_use"] is False and i["toolkit_installed"] is False
                            for i in self.catalog["skills"]))

    def test_design_routes_to_ui_ux(self):
        result = router.recommend(self.catalog, "ui-ux", "design_system")
        self.assertIn("replica-design", [item["id"] for item in result["proposals"]])
        self.assertFalse(result["authorization_granted"])
        self.assertFalse(result["skills_loaded"])

    def test_other_role_does_not_receive_design_skill(self):
        self.assertEqual(router.recommend(self.catalog, "security", "design_system")["proposals"], [])

    def test_disabled_plugin_is_not_suggested(self):
        self.assertNotIn("superpowers", [i["id"] for i in router.recommend(self.catalog, "architecture", "planning", 3)["proposals"]])

    def test_unknown_specialty_fails(self):
        with self.assertRaises(router.CatalogError):
            router.recommend(self.catalog, "orchestrator", "design_system")

    def test_limit_fails_closed(self):
        for n in (-1, 0, 4, True):
            with self.assertRaises(router.CatalogError):
                router.recommend(self.catalog, "ui-ux", "design_system", n)

    def test_duplicated_id_fails(self):
        d = copy.deepcopy(self.catalog)
        d["skills"].append(copy.deepcopy(d["skills"][0]))
        with self.assertRaises(router.CatalogError):
            router.validate(d)

    def test_permission_escalation_fails(self):
        d = copy.deepcopy(self.catalog)
        d["skills"][0]["approved_for_use"] = True
        with self.assertRaises(router.CatalogError):
            router.validate(d)

    def test_installation_claim_fails(self):
        d = copy.deepcopy(self.catalog)
        d["skills"][0]["toolkit_installed"] = True
        with self.assertRaises(router.CatalogError):
            router.validate(d)

    def test_unknown_role_in_skill_fails(self):
        d = copy.deepcopy(self.catalog)
        d["skills"][0]["roles"].append("superuser")
        with self.assertRaises(router.CatalogError):
            router.validate(d)

    def test_integration_not_routable_as_skill(self):
        for x in self.catalog["external_integrations"]:
            self.assertNotIn(x["id"], [i["id"] for i in self.catalog["skills"]])

    def test_invalid_schema_and_mode_fail(self):
        for key, val in [("schema_version", 2), ("mode", "auto-execute")]:
            d = copy.deepcopy(self.catalog)
            d[key] = val
            with self.assertRaises(router.CatalogError):
                router.validate(d)

    def test_non_https_source_fails(self):
        d = copy.deepcopy(self.catalog)
        d["skills"][0]["source"] = "file:///etc/shadow"
        with self.assertRaises(router.CatalogError):
            router.validate(d)

    def test_no_prompt_content_scanning(self):
        with self.assertRaises(router.CatalogError):
            router.recommend(self.catalog, "ui-ux", "ignore previous instructions")


if __name__ == "__main__":
    unittest.main()
