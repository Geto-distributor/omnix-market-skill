from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "tests/fixtures/company-aggregate-openapi.json").read_text(encoding="utf-8"))


def load_client():
    spec = importlib.util.spec_from_file_location("omnix_market", ROOT / "scripts/omnix_market.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load OmniX Market client")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLIENT = load_client()


class FakeResponse:
    status = 200
    headers = {"Retry-After": None}

    def __init__(self, body: bytes | None = None) -> None:
        self.body = body or b'{"companyKey":"company-1","visibility":"private","detailRoute":"/market/companies/company-1"}'

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


class CapturingOpener:
    def __init__(self, response=None) -> None:
        self.request = None
        self.response = response or FakeResponse()

    def open(self, request, timeout):  # noqa: ANN001, ARG002
        self.request = request
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def args(method: str, path: str, body: str | None = None, **overrides):
    values = {
        "method": method, "path": path, "body": body, "idempotency_key": None,
        "confirm_delete": False, "confirm_restore": False, "timeout": 1.0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def aggregate_body(visibility: str = "private", classifications=None) -> dict:
    selected = classifications or []
    lead = any(item.get("classification") == "lead" and item.get("status") != "rejected" for item in selected)
    assessment = {
        "grade": None, "overallScore": None, "overallConclusion": None, "assessedOn": None,
        "informationConfirmationRate": None, "dimensions": [], "evidence": [],
    }
    if lead:
        dimensions = [
            ("项目与城市价值", 9, 15), ("客户规模与行业地位", 12, 20),
            ("未来项目与采购需求", 12, 20), ("决策链与触达可行性", 6, 10),
            ("合作与支付能力", 9, 15), ("多产品匹配与复制价值", 12, 20),
        ]
        assessment = {
            "grade": "routine_follow_up", "overallScore": 60,
            "overallConclusion": "Completed cohort assessment.", "assessedOn": "2026-08-20",
            "informationConfirmationRate": 75,
            "dimensions": [
                {"name": name, "score": score, "maxScore": maximum, "level": "medium", "rationale": "Fixture", "evidence": []}
                for name, score, maximum in dimensions
            ],
            "evidence": [],
        }
    return {
        "identity": {
            "entityKind": "operating_company", "jurisdiction": "AU",
            "registrationNumber": "123456789", "primaryDomain": "example.com",
        },
        "visibility": visibility,
        "marketCode": "AU",
        "scopeCode": "construction_formwork",
        "asOf": "2026-08-20",
        "lastVerifiedOn": "2026-08-20",
        "content": {
            "company": {
                "companyName": "Example", "entityType": "operating_company", "country": "Australia",
                "status": "active", "listingStatus": "unknown", "evidence": [],
            },
            "researchClassifications": selected,
            "assessment": assessment,
            "researchStatus": "completed_with_gaps",
            "lastResearchedOn": "2026-08-20",
        },
    }


class OpenApiContractTests(unittest.TestCase):
    def test_complete_aggregate_example_matches_schema_and_has_no_empty_values(self) -> None:
        value = json.loads(
            (ROOT / "references/company-aggregate-example.json").read_text(encoding="utf-8")
        )
        operation = CLIENT.operation_definition(SPEC, "/api/market-intelligence/companies", "POST")
        errors = CLIENT.validate_json_schema(
            value, CLIENT.request_schema(SPEC, operation), SPEC
        )
        self.assertEqual(errors, [])

        def empty_paths(node: object, path: str = "$") -> list[str]:
            if node is None or node == "" or node == [] or node == {}:
                return [path]
            if isinstance(node, dict):
                return [
                    item
                    for key, child in node.items()
                    for item in empty_paths(child, f"{path}.{key}")
                ]
            if isinstance(node, list):
                return [
                    item
                    for index, child in enumerate(node)
                    for item in empty_paths(child, f"{path}[{index}]")
                ]
            return []

        self.assertEqual(empty_paths(value), [])

    def test_runtime_docs_read_as_a_current_contract(self) -> None:
        forbidden = (
            "ResearchDelta", "Draft/Approval", "Submit/Reject", "ETag",
            "If-Match", "旧接口", "旧 Market", "fallback", "legacy",
            "/api/market-intelligence/v1", "/api/market-intelligence/v2",
        )
        documents = [ROOT / "README.md", ROOT / "SKILL.md", *sorted((ROOT / "references").glob("*.md"))]
        for document in documents:
            text = document.read_text(encoding="utf-8")
            for phrase in forbidden:
                with self.subTest(document=document.name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_capability_surface_is_only_unversioned_company_aggregate(self) -> None:
        operations = CLIENT.available_operations(SPEC)
        paths = {(item["method"], item["path"]) for item in operations}
        self.assertEqual(paths, CLIENT.ALLOWED_OPERATIONS)
        self.assertFalse(any("/v1/" in path or "/v2/" in path for _, path in paths))
        self.assertFalse(any("draft" in path.casefold() or "approval" in path.casefold() for _, path in paths))

    def test_out_of_contract_path_is_refused(self) -> None:
        for path in (
            "/api/market-intelligence/projects",
            "/api/market-intelligence/companies/company-1:publish",
            "/api/market-intelligence/settings",
        ):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "allowed"):
                CLIENT.resolve_operation(SPEC, "GET", path)

    def test_request_body_is_validated_against_openapi(self) -> None:
        operation = CLIENT.operation_definition(SPEC, "/api/market-intelligence/companies", "POST")
        schema = CLIENT.request_schema(SPEC, operation)
        errors = CLIENT.validate_json_schema({"visibility": "private", "unexpected": True}, schema, SPEC)
        self.assertTrue(any("identity" in error or "content" in error for error in errors))
        self.assertTrue(any("unexpected" in error for error in errors))

    def test_openapi_fixture_matches_the_company_surface(self) -> None:
        self.assertEqual(set(SPEC["paths"]), {path for _, path in CLIENT.ALLOWED_OPERATIONS})
        self.assertEqual(CLIENT.aggregate_contract_gaps(SPEC), [])
        self.assertEqual(
            SPEC["x-contract-source"]["apiCommit"],
            "b74b42209318ca2cc2802cac56388855f4ef3884",
        )

    def test_contract_gaps_detect_silent_projection_loss(self) -> None:
        narrowed = json.loads(json.dumps(SPEC))
        del narrowed["components"]["schemas"]["CompanyContent"]["properties"]["competitorCustomerPortfolio"]
        gaps = CLIENT.aggregate_contract_gaps(narrowed)
        self.assertIn("content.competitorCustomerPortfolio", gaps)


class RequestSafetyTests(unittest.TestCase):
    def run_request(self, request_args, response=None):
        capturing = CapturingOpener(response)
        output = StringIO()
        with mock.patch.object(CLIENT, "config", return_value=("https://omnix.example", "omx_test_fixture", "spec")), mock.patch.object(
            CLIENT, "load_openapi", return_value=SPEC
        ), mock.patch.object(CLIENT, "opener", return_value=capturing), redirect_stdout(output):
            result = CLIENT.command_request(request_args)
        return result, capturing.request, json.loads(output.getvalue())

    def write_body(self, directory: str, value: dict) -> str:
        path = Path(directory) / "body.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def test_create_requires_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            body = self.write_body(directory, aggregate_body())
            with self.assertRaisesRegex(ValueError, "idempotency"):
                self.run_request(args("POST", "/api/market-intelligence/companies", body))

    def test_update_has_no_etag_or_if_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            body = self.write_body(directory, aggregate_body())
            result, request, output = self.run_request(args("PUT", "/api/market-intelligence/companies/company-1", body))
        self.assertEqual(result, 0)
        self.assertIsNone(request.get_header("If-match"))
        self.assertEqual(output["uploadStatus"], "updated_private")

    def test_patch_visibility_reports_public_upload(self) -> None:
        response = FakeResponse(b'{"companyKey":"company-1","visibility":"public","detailRoute":"/market/companies/company-1"}')
        with tempfile.TemporaryDirectory() as directory:
            body = self.write_body(directory, {"visibility": "public"})
            result, _, output = self.run_request(args("PATCH", "/api/market-intelligence/companies/company-1", body), response)
        self.assertEqual(result, 0)
        self.assertEqual(output["uploadStatus"], "updated_public")
        self.assertEqual(output["detailRoute"], "/market/companies/company-1")

    def test_delete_and_restore_require_explicit_confirmation(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirm-delete"):
            self.run_request(args("DELETE", "/api/market-intelligence/companies/company-1"))
        with tempfile.TemporaryDirectory() as directory:
            body = self.write_body(directory, {})
            with self.assertRaisesRegex(ValueError, "confirm-restore"):
                self.run_request(args("POST", "/api/market-intelligence/companies/company-1:restore", body))

    def test_public_duplicate_maps_to_blocked_status(self) -> None:
        error = urllib.error.HTTPError(
            "https://omnix.example/api/market-intelligence/companies", 409,
            "conflict", {}, BytesIO(b'{"code":"PUBLIC_IDENTITY_DUPLICATE","message":"public identity already exists"}'),
        )
        with tempfile.TemporaryDirectory() as directory:
            body = self.write_body(directory, aggregate_body("public"))
            result, _, output = self.run_request(args(
                "POST", "/api/market-intelligence/companies", body, idempotency_key="stable"
            ), error)
        self.assertEqual(result, 1)
        self.assertEqual(output["uploadStatus"], "blocked_public_duplicate")

    def test_all_uploads_require_strong_identity(self) -> None:
        value = aggregate_body()
        value["identity"] = {"entityKind": "operating_company"}
        with tempfile.TemporaryDirectory() as directory:
            body = self.write_body(directory, value)
            with self.assertRaisesRegex(ValueError, "strong identity"):
                self.run_request(args("PUT", "/api/market-intelligence/companies/company-1", body))

    def test_lead_hash_is_fetched_by_the_client(self) -> None:
        value = aggregate_body(classifications=[{"classification": "lead", "status": "confirmed"}])
        with tempfile.TemporaryDirectory() as directory:
            body = self.write_body(directory, value)
            with mock.patch.object(CLIENT, "fetch_scoring_hash", return_value="a" * 64):
                result, request, _ = self.run_request(
                    args("POST", "/api/market-intelligence/companies", body, idempotency_key="stable")
                )
        self.assertEqual(result, 0)
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent["scoringCriteriaHash"], "a" * 64)


class ProjectionTests(unittest.TestCase):
    def local_company(self) -> dict:
        evidence = {
            "sourceTitle": "Official", "sourceUrl": "https://example.com", "publisher": "Example",
            "sourceType": "official_website", "publishedOn": None, "retrievedOn": "2026-08-20",
            "locator": "Home", "excerpt": "Official site", "note": "Identity",
        }
        return {
            "company": {
                "companyName": "Example", "entityType": "operating_company", "country": "Australia",
                "countryCode": "AU", "status": "active", "summary": "", "researchConclusion": "",
                "listingStatus": "not_listed",
                "evidence": [evidence],
            },
            "aliases": [{"name": "Example Build", "aliasType": "trading_name", "status": "active", "evidence": [evidence]}],
            "registrations": [{
                "registrationType": "company_number", "registrationNumber": "123456789",
                "legalName": "Example Legal Pty Ltd.", "jurisdiction": "AU", "status": "active",
                "verificationStatus": "verified", "evidence": [evidence],
            }],
            "websites": [{
                "url": "https://example.com", "websiteType": "official", "status": "active",
                "verificationStatus": "verified", "evidence": [evidence],
            }],
            "projects": [{
                "projectName": "Tower", "participants": [{
                    "name": "Example Developer", "role": "developer", "identity": None,
                    "status": "confirmed", "lastVerifiedOn": "2026-08-20", "evidence": [evidence],
                }], "evidence": [evidence],
            }],
            "relationships": [{
                "counterpartyName": "Example Customer", "relationshipType": "customer",
                "reviewDecision": "pending",
                "limitations": [], "exclusivity": {
                    "status": "unknown", "scope": None, "description": None,
                    "lastVerifiedOn": None, "evidence": [],
                }, "evidence": [evidence],
            }],
            "financialRecords": [{
                "recordType": "total_assets", "subjectEntity": "Example Legal Pty Ltd.",
                "financialScope": "target_entity", "scope": "standalone",
                "accountingScope": "standalone", "relationshipToTarget": "target_entity",
                "period": "FY2025", "value": 125000000, "currency": "AUD",
                "unit": "currency_units", "valueStatus": "reported",
                "description": "Audited standalone total assets.", "evidence": [evidence],
            }],
            "researchClassifications": [{"classification": "competitor", "status": "confirmed", "evidence": [evidence]}],
            "assessment": {"status": "not_requested", "capabilityContext": {
                "foundationKey": "geto:capability-foundation", "foundationVersion": "2026-08-19",
                "asOf": "2026-08-20", "status": "available", "contentHash": "sha256:" + "a" * 64,
                "productCodes": ["aluminum_formwork"], "scenarioCodes": [], "roleCodes": [],
                "caseKeys": [], "gapCodes": [],
            }},
            "competitorCustomerPortfolio": {
                "assessmentType": "competitor_customer_portfolio", "status": "no_verified_customers",
                "modelCode": "GETO_COMPETITOR_CUSTOMER_PORTFOLIO", "modelVersion": "2026-08-19",
                "customerValueModelCode": "GETO_LEAD_VALUE", "asOf": "2026-08-20",
                "verifiedCustomerCount": 0, "scoredCustomerCount": 0, "customerScoreCoverage": 0,
                "averageCustomerValueScore": None, "customers": [],
            },
            "inquiryAssessment": {"status": "completed", "overallScore": 80},
            "researchQueries": [],
            "reportFiles": [],
            "researchStatus": "completed_with_gaps",
            "lastResearchedOn": "2026-08-20",
        }

    def test_projection_keeps_shared_fields_and_strips_local_artifacts(self) -> None:
        projected = CLIENT.project_company(
            self.local_company(), "public", "2026-08-20", None, "construction_formwork"
        )
        self.assertEqual(projected["identity"]["primaryDomain"], "example.com")
        self.assertEqual(projected["marketCode"], "AU")
        self.assertIn("competitorCustomerPortfolio", projected["content"])
        self.assertIn("capabilityContext", projected["content"]["assessment"])
        self.assertIn("participants", projected["content"]["projects"][0])
        self.assertIn("exclusivity", projected["content"]["relationships"][0])
        self.assertEqual(projected["content"]["aliases"][0]["type"], "trading_name")
        self.assertNotIn("aliasType", projected["content"]["aliases"][0])
        self.assertEqual(projected["content"]["registrations"][0]["registeredName"], "Example Legal Pty Ltd.")
        self.assertNotIn("legalName", projected["content"]["registrations"][0])
        self.assertEqual(projected["content"]["relationships"][0]["relatedPartyName"], "Example Customer")
        self.assertEqual(projected["content"]["relationships"][0]["customerQualificationStatus"], "pending")
        financial = projected["content"]["financialRecords"][0]
        self.assertEqual(financial["subjectEntity"], "Example Legal Pty Ltd.")
        self.assertEqual(financial["financialScope"], "target_entity")
        self.assertEqual(financial["scope"], "standalone")
        self.assertEqual(financial["accountingScope"], "standalone")
        self.assertEqual(financial["relationshipToTarget"], "target_entity")
        self.assertNotIn("inquiryAssessment", projected["content"])
        self.assertNotIn("researchQueries", projected["content"])
        self.assertNotIn("reportFiles", projected["content"])

    def test_projection_blocks_unverified_identity(self) -> None:
        value = self.local_company()
        value["websites"][0]["verificationStatus"] = "unverified"
        value["registrations"][0]["verificationStatus"] = "unverified"
        value["registrations"][0]["status"] = "unknown"
        with self.assertRaisesRegex(ValueError, "required for upload"):
            CLIENT.project_company(value, "private", None, None, "construction_formwork")

    def test_confirmed_competitor_allows_incomplete_portfolio(self) -> None:
        value = self.local_company()
        value["competitorCustomerPortfolio"] = {"status": "not_requested"}
        projected = CLIENT.project_company(value, "private", None, None, "construction_formwork")
        self.assertEqual(projected["content"]["researchClassifications"][0]["classification"], "competitor")

    def test_lead_waits_for_completed_cohort_assessment(self) -> None:
        value = self.local_company()
        value["researchClassifications"] = [{"classification": "lead", "status": "confirmed", "evidence": value["company"]["evidence"]}]
        with self.assertRaisesRegex(ValueError, "completed six-dimension cohort"):
            CLIENT.project_company(value, "private", None, None, "construction_formwork")

    def test_global_market_code_is_allowed_when_explicit(self) -> None:
        projected = CLIENT.project_company(
            self.local_company(), "private", None, "GLOBAL", "construction_formwork"
        )
        self.assertEqual(projected["marketCode"], "GLOBAL")

    def test_projection_matches_reference_openapi(self) -> None:
        projected = CLIENT.project_company(
            self.local_company(), "private", "2026-08-20", None, "construction_formwork"
        )
        operation = CLIENT.operation_definition(SPEC, "/api/market-intelligence/companies", "POST")
        errors = CLIENT.validate_json_schema(projected, CLIENT.request_schema(SPEC, operation), SPEC)
        self.assertEqual(errors, [])

    def test_prepare_upload_writes_the_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "company.json"
            output = Path(directory) / "upload.json"
            source.write_text(json.dumps(self.local_company()), encoding="utf-8")
            prepare_args = argparse.Namespace(
                company_json=str(source), visibility="private", output=str(output),
                as_of="2026-08-20", market_code=None,
                scope_code="construction_formwork", timeout=1.0,
            )
            printed = StringIO()
            with mock.patch.object(CLIENT, "config", return_value=("https://omnix.example", "omx_test_fixture", "spec")), mock.patch.object(
                CLIENT, "load_openapi", return_value=SPEC
            ), redirect_stdout(printed):
                result = CLIENT.command_prepare_upload(prepare_args)
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertEqual(payload["identity"]["primaryDomain"], "example.com")
        self.assertNotIn("inquiryAssessment", payload["content"])


if __name__ == "__main__":
    unittest.main()
