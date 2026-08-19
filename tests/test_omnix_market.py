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


class OpenApiContractTests(unittest.TestCase):
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
        self.assertTrue(any("company" in error for error in errors))
        self.assertTrue(any("unexpected" in error for error in errors))

    def test_openapi_fixture_matches_the_company_surface(self) -> None:
        self.assertEqual(set(SPEC["paths"]), {path for _, path in CLIENT.ALLOWED_OPERATIONS})


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
            body = self.write_body(directory, {"company": {}, "visibility": "private"})
            with self.assertRaisesRegex(ValueError, "idempotency"):
                self.run_request(args("POST", "/api/market-intelligence/companies", body))

    def test_update_has_no_etag_or_if_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            body = self.write_body(directory, {"company": {}, "visibility": "private"})
            result, request, output = self.run_request(args("PUT", "/api/market-intelligence/companies/company-1", body))
        self.assertEqual(result, 0)
        self.assertIsNone(request.get_header("If-match"))
        self.assertEqual(output["uploadStatus"], "uploaded_private")

    def test_patch_visibility_reports_public_upload(self) -> None:
        response = FakeResponse(b'{"companyKey":"company-1","visibility":"public","detailRoute":"/market/companies/company-1"}')
        with tempfile.TemporaryDirectory() as directory:
            body = self.write_body(directory, {"visibility": "public"})
            result, _, output = self.run_request(args("PATCH", "/api/market-intelligence/companies/company-1", body), response)
        self.assertEqual(result, 0)
        self.assertEqual(output["uploadStatus"], "uploaded_public")
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
            body = self.write_body(directory, {"company": {}, "visibility": "public"})
            result, _, output = self.run_request(args(
                "POST", "/api/market-intelligence/companies", body, idempotency_key="stable"
            ), error)
        self.assertEqual(result, 1)
        self.assertEqual(output["uploadStatus"], "blocked_public_duplicate")


if __name__ == "__main__":
    unittest.main()
