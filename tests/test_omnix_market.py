from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "tests/fixtures/agent-rest-openapi.json").read_text(encoding="utf-8"))


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

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return b'{"validationStatus":"valid"}'


class CapturingOpener:
    def __init__(self) -> None:
        self.request = None

    def open(self, request, timeout):  # noqa: ANN001, ARG002
        self.request = request
        return FakeResponse()


def args(method: str, path: str, body: str | None = None, **overrides):
    values = {
        "method": method, "path": path, "body": body, "idempotency_key": None,
        "confirm_delete": False, "confirm_submit": False, "timeout": 1.0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class OpenApiContractTests(unittest.TestCase):
    def test_runtime_docs_do_not_embed_release_history(self) -> None:
        forbidden = (
            "未合并 PR", "测试环境尚未", "当前服务端 main", "MCP", "ETag", "If-Match",
            "17 个只读", "59 个", "60 个",
        )
        documents = [ROOT / "SKILL.md", *sorted((ROOT / "references").glob("*.md"))]
        for document in documents:
            text = document.read_text(encoding="utf-8")
            for phrase in forbidden:
                with self.subTest(document=document.name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_capability_surface_excludes_owner_draft_list_and_approvals(self) -> None:
        operations = CLIENT.available_operations(SPEC)
        paths = {(item["method"], item["path"]) for item in operations}
        self.assertIn(
            ("POST", "/api/market-intelligence/v1/markets/{marketCode}/drafts:validate"),
            paths,
        )
        self.assertNotIn(
            ("GET", "/api/market-intelligence/v1/markets/{marketCode}/drafts"),
            paths,
        )
        self.assertFalse(any("approvals" in path for _, path in paths))

    def test_owner_scoped_object_list_accepts_draft_filter(self) -> None:
        template = CLIENT.resolve_operation(
            SPEC, "GET", "/api/market-intelligence/v1/markets/AU/companies"
        )
        operation = CLIENT.operation_definition(SPEC, template, "GET")
        errors = CLIENT.validate_query(
            SPEC, template, operation, "scopeCode=construction_formwork&contentStatus=Draft"
        )
        self.assertEqual(errors, [])

        source_template = CLIENT.resolve_operation(
            SPEC, "GET", "/api/market-intelligence/v1/markets/AU/sources"
        )
        source_operation = CLIENT.operation_definition(SPEC, source_template, "GET")
        source_errors = CLIENT.validate_query(
            SPEC,
            source_template,
            source_operation,
            "scopeCode=construction_formwork&contentStatus=Draft",
        )
        self.assertEqual(source_errors, [])

    def test_unknown_query_parameter_is_rejected(self) -> None:
        template = CLIENT.resolve_operation(
            SPEC, "GET", "/api/market-intelligence/v1/markets/AU/companies"
        )
        operation = CLIENT.operation_definition(SPEC, template, "GET")
        errors = CLIENT.validate_query(
            SPEC, template, operation, "scopeCode=construction_formwork&ownerId=other"
        )
        self.assertTrue(any("ownerId" in error for error in errors))

    def test_request_body_is_validated_against_openapi(self) -> None:
        operation = CLIENT.operation_definition(
            SPEC,
            "/api/market-intelligence/v1/markets/{marketCode}/drafts/companies",
            "POST",
        )
        schema = CLIENT.request_schema(SPEC, operation)
        errors = CLIENT.validate_json_schema(
            {"resourceKey": "company:au:test", "unexpected": True}, schema, SPEC
        )
        self.assertTrue(any("canonicalName" in error for error in errors))
        self.assertTrue(any("unexpected" in error for error in errors))

    def test_draft_discovery_response_without_stable_keys_is_rejected(self) -> None:
        operation = CLIENT.operation_definition(
            SPEC,
            "/api/market-intelligence/v1/markets/{marketCode}/companies",
            "GET",
        )
        schema = CLIENT.response_schema(SPEC, operation, 200)
        errors = CLIENT.validate_json_schema(
            {"items": [{"contentStatus": "Draft", "resourceKey": "company:au:test"}]},
            schema,
            SPEC,
        )
        self.assertTrue(any("draftKey" in error for error in errors))

        source_operation = CLIENT.operation_definition(
            SPEC,
            "/api/market-intelligence/v1/markets/{marketCode}/sources",
            "GET",
        )
        source_schema = CLIENT.response_schema(SPEC, source_operation, 200)
        source_errors = CLIENT.validate_json_schema(
            {"items": [{"contentStatus": "Draft", "draftKey": "draft:source:1"}]},
            source_schema,
            SPEC,
        )
        self.assertTrue(any("sourceKey" in error for error in source_errors))


class RequestSafetyTests(unittest.TestCase):
    def run_request(self, request_args):
        capturing = CapturingOpener()
        with mock.patch.object(
            CLIENT, "config", return_value=("https://omnix.example", "omx_test_fixture", "spec")
        ), mock.patch.object(CLIENT, "load_openapi", return_value=SPEC), mock.patch.object(
            CLIENT, "opener", return_value=capturing
        ), redirect_stdout(StringIO()):
            result = CLIENT.command_request(request_args)
        return result, capturing.request

    def test_validate_is_no_write_and_needs_no_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            body = Path(directory) / "validate.json"
            body.write_text('{"draftKeys":["draft:company:1"]}', encoding="utf-8")
            result, request = self.run_request(args(
                "POST", "/api/market-intelligence/v1/markets/AU/drafts:validate", str(body)
            ))
        self.assertEqual(result, 0)
        self.assertIsNotNone(request)
        self.assertIsNone(request.get_header("Idempotency-key"))
        self.assertIsNone(request.get_header("If-match"))

    def test_create_requires_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            body = Path(directory) / "company.json"
            body.write_text(
                '{"resourceKey":"company:au:test","canonicalName":"Example"}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "idempotency"):
                self.run_request(args(
                    "POST", "/api/market-intelligence/v1/markets/AU/drafts/companies", str(body)
                ))

    def test_update_does_not_require_or_send_if_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            body = Path(directory) / "company.json"
            body.write_text(
                '{"resourceKey":"company:au:test","canonicalName":"Example"}',
                encoding="utf-8",
            )
            result, request = self.run_request(args(
                "PUT",
                "/api/market-intelligence/v1/markets/AU/drafts/companies/company:au:test",
                str(body),
            ))
        self.assertEqual(result, 0)
        self.assertIsNone(request.get_header("If-match"))


if __name__ == "__main__":
    unittest.main()
