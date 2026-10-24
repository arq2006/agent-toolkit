#!/usr/bin/env python3
"""GH-F2.1: offline, read-only validation of candidate reviews; never executes skills."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEWS = ROOT / "skills" / "reviews" / "GH-F2-1-candidates.json"
CATALOG = ROOT / "skills" / "catalog.json"
PIN = re.compile(r"[0-9a-f]{40}\Z")
IDS = frozenset({
    "impeccable", "replica-design", "frontend-design",
    "web-design-guidelines", "vercel-react-best-practices", "webapp-testing",
})
PROTECTED = frozenset({"docs/references/", "docs/security/", "docs/CHECKSUMS.sha256"})
RISK = frozenset({"low", "medium", "high"})


class ReviewError(ValueError):
    pass


def validate(reviews: object, catalog: object) -> dict:
    if not isinstance(reviews, dict) or reviews.get("schema_version") != 1 or type(reviews.get("schema_version")) is not int:
        raise ReviewError("unsupported review schema")
    if reviews.get("phase") != "GH-F2.1" or reviews.get("mode") != "review-only":
        raise ReviewError("reviews may not be executable")
    guard = reviews.get("global_policy")
    required = {"permissions_granted", "any_installation_authorized", "any_execution_authorized",
                "materialize_claude_skills", "enable_hooks", "approve_third_party_code"}
    if not isinstance(guard, dict) or set(guard) != required or any(value is not False for value in guard.values()):
        raise ReviewError("global authorization guard must remain false")
    if not isinstance(catalog, dict) or catalog.get("mode") != "advisory-only":
        raise ReviewError("catalog cannot grant execution")
    catalog_entries = catalog.get("skills")
    if not isinstance(catalog_entries, list):
        raise ReviewError("catalog missing skills")
    by_id = {x["id"]: x for x in catalog_entries if isinstance(x, dict) and "id" in x}
    candidates = reviews.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != len(IDS) or reviews.get("candidate_count") != len(IDS):
        raise ReviewError("expected exactly six reviewed candidates")
    if {c.get("id") for c in candidates if isinstance(c, dict)} != IDS:
        raise ReviewError("candidate IDs missing, duplicated or unexpected")
    for c in candidates:
        id_ = c["id"]
        cat = by_id.get(id_)
        if cat is None or cat.get("approved_for_use") is not False or cat.get("toolkit_installed") is not False:
            raise ReviewError(f"catalog status or ID invalid: {id_}")
        src = c.get("source")
        if not isinstance(src, dict) or set(src) != {"repository", "commit_sha", "entry_path", "entry_blob_sha"}:
            raise ReviewError(f"source evidence incomplete: {id_}")
        if src["repository"] != cat.get("source") or not src["repository"].startswith("https://github.com/"):
            raise ReviewError(f"source changed from catalog: {id_}")
        for key in ("commit_sha", "entry_blob_sha"):
            if not isinstance(src[key], str) or not PIN.fullmatch(src[key]):
                raise ReviewError(f"missing immutable pin {key}: {id_}")
        if (not isinstance(src["entry_path"], str) or not src["entry_path"].endswith("/SKILL.md")
                or src["entry_path"].startswith("/") or ".." in Path(src["entry_path"]).parts):
            raise ReviewError(f"invalid upstream skill path: {id_}")
        license_ = c.get("license")
        if (not isinstance(license_, dict) or set(license_) != {"reported", "verification", "evidence"}
                or license_["verification"] not in {"confirmed", "declared-only", "unverified"}
                or not all(isinstance(v, str) and v for v in license_.values())):
            raise ReviewError(f"license evidence incomplete: {id_}")
        if license_["verification"] == "unverified" and license_["reported"] != "UNVERIFIED":
            raise ReviewError(f"unverified license presented as confirmed: {id_}")
        review = c.get("review")
        if (not isinstance(review, dict) or review.get("status") != "PARTIAL"
                or review.get("approval") != "NOT_APPROVED" or review.get("toolkit_installed") is not False
                or review.get("authorized_to_execute") is not False or review.get("risk") not in RISK
                or not isinstance(review.get("observed"), list)
                or not isinstance(review.get("required_before_adoption"), list)
                or not review["required_before_adoption"]):
            raise ReviewError(f"review must remain partial and blocked: {id_}")
        contract = c.get("contract_proposal")
        required_contract = {
            "status", "owner", "eligible_roles", "purpose", "permissions_current",
            "actions_proposed", "actions_requiring_explicit_authorization",
            "forbidden_until_approved", "inputs", "outputs", "protected_paths", "tests", "stop_conditions"
        }
        if not isinstance(contract, dict) or set(contract) != required_contract:
            raise ReviewError(f"draft contract missing fields: {id_}")
        if (contract["status"] != "DRAFT_NOT_SKILL" or contract["permissions_current"] != []
                or contract["owner"] not in contract["eligible_roles"]
                or not set(contract["eligible_roles"]) <= set(cat["roles"])
                or set(contract["protected_paths"]) != PROTECTED
                or len(contract["tests"]) < 3
                or not all(t in contract["tests"] for t in (
                    "positive_readonly_scoped", "negative_refuse_unauthorized_write",
                    "negative_refuse_tool_permission_conflict"
                ))):
            raise ReviewError(f"contract status, scopes or negative tests invalid: {id_}")
        if (not isinstance(contract["purpose"], str) or not contract["purpose"]
                or not isinstance(contract["forbidden_until_approved"], list)
                or not contract["forbidden_until_approved"]
                or any(not isinstance(v, str) or not v.startswith("A0:")
                        for v in contract["actions_proposed"])
                or any(not isinstance(v, str) or not re.match(r"^A[123]:", v)
                        for v in contract["actions_requiring_explicit_authorization"])):
            raise ReviewError(f"scope/permissions malformed: {id_}")
        if id_ == "web-design-guidelines":
            extra = c.get("external_source_pin")
            if (not isinstance(extra, dict) or not PIN.fullmatch(str(extra.get("remote_rules_sha", "")))
                    or extra.get("remote_rules_path") != "command.md"):
                raise ReviewError("live guideline source must be pinned as review evidence")
    return {"status": "VALID", "mode": "review-only", "candidates": len(candidates),
            "permissions_granted": False, "skills_executed": False, "installed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate pinned draft reviews without running skills")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    args = parser.parse_args()
    try:
        reviews = json.loads(REVIEWS.read_text(encoding="utf-8"))
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        out = validate(reviews, catalog)
        code = 0
    except (OSError, json.JSONDecodeError, ReviewError, TypeError, KeyError) as exc:
        out = {"status": "INVALID", "error": str(exc), "permissions_granted": False}
        code = 2
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(f"{out['status']}: {out.get('candidates', 0)} candidates (no execution)")
        if code:
            print(out["error"])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
