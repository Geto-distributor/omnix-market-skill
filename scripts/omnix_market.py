#!/usr/bin/env python3
"""OpenAPI-gated client for the unversioned OmniX Company Aggregate API."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


MARKET_ROOT = "/api/market-intelligence"
ALLOWED_OPERATIONS = {
    ("GET", f"{MARKET_ROOT}/companies"),
    ("GET", f"{MARKET_ROOT}/companies/{{companyKey}}"),
    ("GET", f"{MARKET_ROOT}/scoring-criteria"),
    ("POST", f"{MARKET_ROOT}/companies:resolve"),
    ("POST", f"{MARKET_ROOT}/companies"),
    ("PUT", f"{MARKET_ROOT}/companies/{{companyKey}}"),
    ("PATCH", f"{MARKET_ROOT}/companies/{{companyKey}}"),
    ("DELETE", f"{MARKET_ROOT}/companies/{{companyKey}}"),
    ("POST", f"{MARKET_ROOT}/companies/{{companyKey}}:restore"),
}
REQUIRED_OPERATIONS = ALLOWED_OPERATIONS
CONTENT_FIELDS = {
    "company", "aliases", "registrations", "capitalRecords", "websites", "addresses",
    "marketPresence", "socialChannels", "researchClassifications", "companyRoles",
    "productsAndServices", "projects", "relationships", "contacts",
    "licensesAndCertifications", "financialRecords", "newsAndSocialMedia",
    "customsTransactions", "lawsuitsAndCompliance", "inquiries", "risks", "assessment",
    "competitorCustomerPortfolio", "missingInformation", "recommendedActions",
    "additionalInformation", "researchStatus", "lastResearchedOn",
}
LOCAL_ONLY_FIELDS = {"inquiryAssessment", "researchQueries", "reportFiles"}
ENTITY_KINDS = {"legal_entity", "operating_company", "corporate_group"}
SCOPE_CODES = {"construction_formwork"}


class ClientError(ValueError):
    def __init__(self, provider_status: str, message: str) -> None:
        super().__init__(message)
        self.provider_status = provider_status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def config() -> tuple[str, str, str]:
    base = os.environ.get("OMNIX_API_BASE_URL", "").strip().rstrip("/")
    key = os.environ.get("OMNIX_API_KEY", "").strip()
    if not base:
        raise ClientError("not_configured", "OMNIX_API_BASE_URL is not configured")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ClientError("not_configured", "OMNIX_API_BASE_URL must be an absolute HTTP(S) URL")
    if not key:
        raise ClientError("not_configured", "OMNIX_API_KEY is not configured")
    if not (key.startswith("omx_test_") or key.startswith("omx_live_")):
        raise ClientError("not_configured", "OMNIX_API_KEY has an unsupported prefix")
    spec_url = os.environ.get("OMNIX_OPENAPI_URL", "").strip() or f"{base}/swagger/v1/swagger.json"
    spec_parsed = urllib.parse.urlparse(spec_url)
    if (spec_parsed.scheme, spec_parsed.netloc) != (parsed.scheme, parsed.netloc):
        raise ClientError("not_configured", "OMNIX_OPENAPI_URL must use the OmniX API origin")
    return base, key, spec_url


def opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(NoRedirect)


def load_openapi(spec_url: str) -> dict[str, Any]:
    request = urllib.request.Request(spec_url, headers={"Accept": "application/json"})
    with opener().open(request, timeout=20) as response:
        value = json.load(response)
    if not isinstance(value, dict) or not isinstance(value.get("paths"), dict):
        raise ValueError("OpenAPI document does not contain paths")
    return value


def safe_operation(method: str, template: str) -> bool:
    return (method, template) in ALLOWED_OPERATIONS


def available_operations(spec: dict[str, Any]) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    for template, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            upper = method.upper()
            if safe_operation(upper, template) and isinstance(operation, dict):
                values.append({
                    "method": upper,
                    "path": template,
                    "operationId": str(operation.get("operationId") or ""),
                })
    return sorted(values, key=lambda item: (item["path"], item["method"]))


def template_regex(template: str) -> re.Pattern[str]:
    escaped = re.escape(template)
    pattern = re.sub(r"\\\{[^{}]+\\\}", r"[^/:]+", escaped)
    return re.compile(f"^{pattern}$")


def resolve_operation(spec: dict[str, Any], method: str, concrete_path: str) -> str:
    matches = [
        item["path"] for item in available_operations(spec)
        if item["method"] == method and template_regex(item["path"]).match(concrete_path)
    ]
    if len(matches) != 1:
        raise ValueError(f"request does not match exactly one allowed OpenAPI operation: {matches}")
    return matches[0]


def resolve_pointer(document: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise ValueError(f"only local OpenAPI references are supported: {reference}")
    value: Any = document
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            raise ValueError(f"OpenAPI reference does not resolve: {reference}")
        value = value[token]
    return value


def resolve_object(spec: dict[str, Any], value: Any) -> Any:
    seen: set[str] = set()
    while isinstance(value, dict) and isinstance(value.get("$ref"), str):
        reference = value["$ref"]
        if reference in seen:
            raise ValueError(f"cyclic OpenAPI reference: {reference}")
        seen.add(reference)
        value = resolve_pointer(spec, reference)
    return value


def operation_definition(spec: dict[str, Any], template: str, method: str) -> dict[str, Any]:
    path_item = spec["paths"].get(template)
    operation = path_item.get(method.lower()) if isinstance(path_item, dict) else None
    if not isinstance(operation, dict):
        raise ValueError("matched OpenAPI operation has no definition")
    return operation


def request_schema(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any] | None:
    request_body = resolve_object(spec, operation.get("requestBody"))
    if not isinstance(request_body, dict):
        return None
    content = request_body.get("content")
    media = content.get("application/json") if isinstance(content, dict) else None
    schema = media.get("schema") if isinstance(media, dict) else None
    return schema if isinstance(schema, dict) else None


def response_schema(spec: dict[str, Any], operation: dict[str, Any], status: int) -> dict[str, Any] | None:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None
    response = responses.get(str(status), responses.get(f"{status // 100}XX", responses.get("default")))
    response = resolve_object(spec, response)
    content = response.get("content") if isinstance(response, dict) else None
    media = content.get("application/json") if isinstance(content, dict) else None
    schema = media.get("schema") if isinstance(media, dict) else None
    return schema if isinstance(schema, dict) else None


def schema_property(spec: dict[str, Any], schema: Any, name: str) -> dict[str, Any] | None:
    schema = resolve_object(spec, schema)
    properties = schema.get("properties") if isinstance(schema, dict) else None
    child = properties.get(name) if isinstance(properties, dict) else None
    child = resolve_object(spec, child)
    return child if isinstance(child, dict) else None


def array_item_schema(spec: dict[str, Any], schema: Any) -> dict[str, Any] | None:
    schema = resolve_object(spec, schema)
    child = resolve_object(spec, schema.get("items")) if isinstance(schema, dict) else None
    return child if isinstance(child, dict) else None


def aggregate_contract_gaps(spec: dict[str, Any]) -> list[str]:
    try:
        operation = operation_definition(spec, f"{MARKET_ROOT}/companies", "POST")
        root = request_schema(spec, operation)
        content = schema_property(spec, root, "content")
        assessment = schema_property(spec, content, "assessment")
        projects = array_item_schema(spec, schema_property(spec, content, "projects"))
        relationships = array_item_schema(spec, schema_property(spec, content, "relationships"))
        checks = {
            "content.competitorCustomerPortfolio": schema_property(spec, content, "competitorCustomerPortfolio"),
            "content.assessment.capabilityContext": schema_property(spec, assessment, "capabilityContext"),
            "content.projects[].participants": schema_property(spec, projects, "participants"),
            "content.relationships[].exclusivity": schema_property(spec, relationships, "exclusivity"),
        }
    except ValueError:
        return ["Company Aggregate request schema"]
    gaps = [name for name, schema in checks.items() if schema is None]
    schemas = spec.get("components", {}).get("schemas", {})
    for name, schema in (schemas.items() if isinstance(schemas, dict) else []):
        if "evidence" not in str(name).casefold():
            continue
        resolved = resolve_object(spec, schema)
        properties = resolved.get("properties") if isinstance(resolved, dict) else None
        if isinstance(properties, dict) and "relation" in properties:
            gaps.append(f"components.schemas.{name}.relation")
    return sorted(gaps)


def json_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool), "null": value is None,
    }.get(expected, True)


def validate_json_schema(value: Any, schema: dict[str, Any], spec: dict[str, Any], location: str = "$", depth: int = 0) -> list[str]:
    if depth > 32:
        return [f"{location}: OpenAPI schema nesting exceeds 32 levels"]
    schema = resolve_object(spec, schema)
    if not isinstance(schema, dict):
        return []
    if value is None and schema.get("nullable") is True:
        return []
    errors: list[str] = []
    for branch in schema.get("allOf", []) if isinstance(schema.get("allOf"), list) else []:
        if isinstance(branch, dict):
            errors.extend(validate_json_schema(value, branch, spec, location, depth + 1))
    expected = schema.get("type")
    if isinstance(expected, str) and not json_type_matches(value, expected):
        return [f"{location}: expected OpenAPI type {expected}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{location}: value is not in OpenAPI enum {schema['enum']}")
    if isinstance(value, dict):
        properties = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}
        for name in schema.get("required", []) if isinstance(schema.get("required"), list) else []:
            if name not in value:
                errors.append(f"{location}.{name}: required by OpenAPI")
        if schema.get("additionalProperties") is False:
            for name in value.keys() - properties.keys():
                errors.append(f"{location}.{name}: property is not allowed by OpenAPI")
        for name, child in value.items():
            if isinstance(properties.get(name), dict):
                errors.extend(validate_json_schema(child, properties[name], spec, f"{location}.{name}", depth + 1))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, child in enumerate(value):
            errors.extend(validate_json_schema(child, schema["items"], spec, f"{location}[{index}]", depth + 1))
    return errors


def operation_parameters(spec: dict[str, Any], template: str, operation: dict[str, Any]) -> list[dict[str, Any]]:
    path_item = spec["paths"].get(template)
    values: list[Any] = []
    if isinstance(path_item, dict) and isinstance(path_item.get("parameters"), list):
        values.extend(path_item["parameters"])
    if isinstance(operation.get("parameters"), list):
        values.extend(operation["parameters"])
    return [value for item in values if isinstance((value := resolve_object(spec, item)), dict)]


def validate_query(spec: dict[str, Any], template: str, operation: dict[str, Any], query: str) -> list[str]:
    query_values = urllib.parse.parse_qs(query, keep_blank_values=True)
    parameters = {
        item.get("name"): item for item in operation_parameters(spec, template, operation)
        if item.get("in") == "query" and isinstance(item.get("name"), str)
    }
    errors = [f"query parameter is not declared by OpenAPI: {name}" for name in query_values.keys() - parameters.keys()]
    for name, parameter in parameters.items():
        if parameter.get("required") is True and name not in query_values:
            errors.append(f"required OpenAPI query parameter is missing: {name}")
    return errors


def read_body(path: str | None) -> tuple[Any | None, bytes | None]:
    if path is None:
        return None, None
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    value = json.loads(raw)
    return value, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def encoded_body(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def is_lead(content: dict[str, Any]) -> bool:
    return any(
        isinstance(item, dict)
        and str(item.get("classification") or "").casefold() == "lead"
        and str(item.get("status") or "").casefold() != "rejected"
        for item in content.get("researchClassifications", [])
    )


def strong_identity(identity: Any) -> bool:
    if not isinstance(identity, dict) or identity.get("entityKind") not in ENTITY_KINDS:
        return False
    jurisdiction = str(identity.get("jurisdiction") or "").strip()
    return bool(
        str(identity.get("primaryDomain") or "").strip()
        or jurisdiction and str(identity.get("registrationNumber") or "").strip()
        or jurisdiction and str(identity.get("otherLegalId") or "").strip()
    )


def identity_from_company(value: dict[str, Any]) -> dict[str, Any]:
    company = value.get("company")
    if not isinstance(company, dict):
        raise ValueError("company.json requires company")
    if value.get("researchStatus") == "identity_conflict":
        raise ValueError("identity_conflict Company is not uploadable")
    identity: dict[str, Any] = {"entityKind": company.get("entityType")}
    registrations = [item for item in value.get("registrations", []) if isinstance(item, dict)]
    verified = [item for item in registrations if item.get("verificationStatus") in {"verified", "confirmed"}]
    candidates = verified or [item for item in registrations if item.get("status") == "active"]
    for item in candidates:
        number = str(item.get("registrationNumber") or "").strip()
        jurisdiction = str(item.get("jurisdiction") or company.get("countryCode") or "").strip()
        if number and jurisdiction:
            identity["jurisdiction"] = jurisdiction.upper()
            identity["registrationNumber"] = number
            break
    websites = [item for item in value.get("websites", []) if isinstance(item, dict)]
    for item in websites:
        if item.get("websiteType") != "official" or item.get("verificationStatus") not in {"verified", "confirmed"}:
            continue
        url = str(item.get("url") or "").strip()
        parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
        if parsed.hostname:
            identity["primaryDomain"] = parsed.hostname.removeprefix("www.").lower()
            break
    if not strong_identity(identity):
        raise ValueError("a verified registration identity or official primary domain is required for upload")
    return identity


def latest_verified_on(value: Any) -> str | None:
    dates: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "lastVerifiedOn" and isinstance(child, str):
                try:
                    datetime.strptime(child, "%Y-%m-%d")
                    dates.append(child)
                except ValueError:
                    pass
            else:
                nested = latest_verified_on(child)
                if nested:
                    dates.append(nested)
    elif isinstance(value, list):
        for child in value:
            nested = latest_verified_on(child)
            if nested:
                dates.append(nested)
    return max(dates) if dates else None


def project_company(value: dict[str, Any], visibility: str, as_of: str | None,
                    market_code: str | None, scope_code: str) -> dict[str, Any]:
    if visibility not in {"private", "public"}:
        raise ValueError("visibility must be private or public")
    company = value.get("company")
    if not isinstance(company, dict):
        raise ValueError("company.json requires company")
    code = str(market_code or company.get("countryCode") or "").upper()
    if not re.fullmatch(r"[A-Z]{2}", code):
        raise ValueError("marketCode must be an ISO 3166-1 alpha-2 code")
    if scope_code not in SCOPE_CODES:
        raise ValueError(f"scopeCode must be one of {sorted(SCOPE_CODES)}")
    snapshot = as_of or value.get("lastResearchedOn")
    try:
        datetime.strptime(str(snapshot), "%Y-%m-%d")
    except ValueError as error:
        raise ValueError("asOf must use YYYY-MM-DD") from error
    unexpected = sorted(set(value) - CONTENT_FIELDS - LOCAL_ONLY_FIELDS)
    if unexpected:
        raise ValueError("company.json has unsupported top-level fields: " + ", ".join(unexpected))
    content = {field: value[field] for field in CONTENT_FIELDS if field in value}
    for field in ("company", "assessment", "competitorCustomerPortfolio", "researchStatus", "lastResearchedOn"):
        if field not in content:
            raise ValueError(f"company.json requires {field}")
    return {
        "identity": identity_from_company(value),
        "visibility": visibility,
        "marketCode": code,
        "scopeCode": scope_code,
        "asOf": snapshot,
        "lastVerifiedOn": latest_verified_on(value),
        "content": content,
    }


def fetch_scoring_hash(base: str, key: str, spec: dict[str, Any], timeout: float) -> str:
    path = f"{MARKET_ROOT}/scoring-criteria"
    template = resolve_operation(spec, "GET", path)
    operation = operation_definition(spec, template, "GET")
    request = urllib.request.Request(f"{base}{path}", headers={"Accept": "application/json", "X-API-KEY": key})
    with opener().open(request, timeout=timeout) as response:
        body = parse_body(response.read().decode("utf-8", errors="replace"))
        errors = validate_json_schema(body, response_schema(spec, operation, response.status), spec) \
            if response_schema(spec, operation, response.status) is not None else []
    if errors:
        raise ValueError("scoring criteria response violates OpenAPI schema: " + "; ".join(errors))
    value = nested_value(body, "hash")
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("scoring criteria response requires a SHA-256 hash")
    return value.lower()


def inject_scoring_hash(body: Any, base: str, key: str, spec: dict[str, Any], timeout: float) -> Any:
    if not isinstance(body, dict) or not isinstance(body.get("content"), dict):
        raise ValueError("Company Aggregate request requires content")
    if not strong_identity(body.get("identity")):
        raise ValueError("Company Aggregate upload requires a strong identity")
    if is_lead(body["content"]):
        body["scoringCriteriaHash"] = fetch_scoring_hash(base, key, spec, timeout)
    else:
        body.pop("scoringCriteriaHash", None)
    return body


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def nested_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = nested_value(child, key)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = nested_value(child, key)
            if found is not None:
                return found
    return None


def parse_body(raw: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def is_public_duplicate(body: Any) -> bool:
    text = json.dumps(body, ensure_ascii=False).casefold() if not isinstance(body, str) else body.casefold()
    return "public" in text and any(term in text for term in ("duplicate", "identity", "unique", "already exists"))


def command_capabilities(_: argparse.Namespace) -> int:
    _, _, spec_url = config()
    spec = load_openapi(spec_url)
    operations = available_operations(spec)
    actual = {(item["method"], item["path"]) for item in operations}
    missing = sorted([f"{method} {path}" for method, path in REQUIRED_OPERATIONS - actual])
    contract_gaps = aggregate_contract_gaps(spec) if not missing else []
    status = "available" if not missing and not contract_gaps else ("partial" if operations else "upstream_unavailable")
    print(json.dumps({
        "provider": "omnix-market", "status": status, "operations": operations,
        "missingRequiredOperations": missing, "missingAggregateContractFields": contract_gaps,
    }, ensure_ascii=False, indent=2))
    return 0 if status == "available" else 1


def command_prepare_upload(args: argparse.Namespace) -> int:
    base, key, spec_url = config()
    spec = load_openapi(spec_url)
    value = json.loads(Path(args.company_json).expanduser().resolve().read_text(encoding="utf-8"))
    body = project_company(value, args.visibility, args.as_of, args.market_code, args.scope_code)
    body = inject_scoring_hash(body, base, key, spec, args.timeout)
    operation = operation_definition(spec, f"{MARKET_ROOT}/companies", "POST")
    schema = request_schema(spec, operation)
    errors = validate_json_schema(body, schema, spec) if schema is not None else []
    if errors:
        raise ValueError("Company Aggregate projection violates OpenAPI schema: " + "; ".join(errors))
    output = Path(args.output).expanduser().resolve()
    atomic_write_json(output, body)
    print(json.dumps({
        "provider": "omnix-market", "status": "prepared", "output": str(output),
        "visibility": body["visibility"], "marketCode": body["marketCode"],
        "scopeCode": body["scopeCode"], "hasScoringCriteriaHash": "scoringCriteriaHash" in body,
    }, ensure_ascii=False, indent=2))
    return 0


def command_request(args: argparse.Namespace) -> int:
    base, key, spec_url = config()
    method = args.method.upper()
    parsed_path = urllib.parse.urlsplit(args.path)
    if parsed_path.scheme or parsed_path.netloc or not parsed_path.path.startswith("/"):
        raise ValueError("path must be an absolute-path reference, not a URL")
    spec = load_openapi(spec_url)
    template = resolve_operation(spec, method, parsed_path.path)
    operation = operation_definition(spec, template, method)
    query_errors = validate_query(spec, template, operation, parsed_path.query)
    if query_errors:
        raise ValueError("; ".join(query_errors))
    is_create = method == "POST" and template == f"{MARKET_ROOT}/companies"
    is_replace = method == "PUT" and template == f"{MARKET_ROOT}/companies/{{companyKey}}"
    is_restore = method == "POST" and template.endswith(":restore")
    if is_create and not args.idempotency_key:
        raise ValueError("Company create requires --idempotency-key")
    if method == "DELETE" and not args.confirm_delete:
        raise ValueError("DELETE requires --confirm-delete after explicit user intent")
    if is_restore and not args.confirm_restore:
        raise ValueError("restore requires --confirm-restore after explicit user intent")
    body, data = read_body(args.body)
    if method in {"POST", "PUT", "PATCH"} and data is None:
        raise ValueError(f"{method} requires --body")
    if is_create or is_replace:
        body = inject_scoring_hash(body, base, key, spec, args.timeout)
        data = encoded_body(body)
    schema = request_schema(spec, operation)
    if body is not None and schema is not None:
        schema_errors = validate_json_schema(body, schema, spec)
        if schema_errors:
            raise ValueError("request body violates OpenAPI schema: " + "; ".join(schema_errors))
    headers = {"Accept": "application/json", "X-API-KEY": key}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if args.idempotency_key:
        headers["Idempotency-Key"] = args.idempotency_key
    request = urllib.request.Request(f"{base}{args.path}", data=data, headers=headers, method=method)
    try:
        response = opener().open(request, timeout=args.timeout)
    except urllib.error.HTTPError as error:
        response_body = parse_body(error.read().decode("utf-8", errors="replace"))
        upload_status = "blocked_public_duplicate" if error.code == 409 and is_public_duplicate(response_body) else "failed"
        print(json.dumps({"provider": "omnix-market", "providerStatus": http_provider_status(error.code), "uploadStatus": upload_status, "httpStatus": error.code, "body": response_body}, ensure_ascii=False, indent=2))
        return 1
    with response:
        raw = response.read().decode("utf-8", errors="replace")
        response_body = parse_body(raw)
        response_errors = validate_json_schema(response_body, response_schema(spec, operation, response.status), spec) if response_schema(spec, operation, response.status) is not None else []
        requested_visibility = nested_value(body, "visibility")
        returned_visibility = nested_value(response_body, "visibility") or requested_visibility
        upload_status = None
        if method in {"POST", "PUT", "PATCH"} and template != f"{MARKET_ROOT}/companies:resolve" and not is_restore:
            upload_status = "uploaded_public" if returned_visibility == "public" else "uploaded_private"
        result = {
            "provider": "omnix-market",
            "providerStatus": "failed" if response_errors else "available",
            "uploadStatus": upload_status,
            "httpStatus": response.status,
            "companyKey": nested_value(response_body, "companyKey"),
            "visibility": returned_visibility,
            "detailRoute": nested_value(response_body, "detailRoute"),
            "body": response_body,
            "responseValidationErrors": response_errors,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if response_errors else 0


def http_provider_status(status: int) -> str:
    return {401: "unauthenticated", 403: "forbidden", 429: "rate_limited"}.get(status, "upstream_unavailable" if status >= 500 else "failed")


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    capabilities = sub.add_parser("capabilities")
    capabilities.set_defaults(func=command_capabilities)
    prepare = sub.add_parser("prepare-upload")
    prepare.add_argument("company_json")
    prepare.add_argument("--visibility", choices=("private", "public"), required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--as-of")
    prepare.add_argument("--market-code")
    prepare.add_argument("--scope-code", choices=tuple(sorted(SCOPE_CODES)), default="construction_formwork")
    prepare.add_argument("--timeout", type=float, default=30)
    prepare.set_defaults(func=command_prepare_upload)
    request = sub.add_parser("request")
    request.add_argument("method", choices=("GET", "POST", "PUT", "PATCH", "DELETE"))
    request.add_argument("path")
    request.add_argument("--body", help="JSON file path, or - for stdin")
    request.add_argument("--idempotency-key")
    request.add_argument("--confirm-delete", action="store_true")
    request.add_argument("--confirm-restore", action="store_true")
    request.add_argument("--timeout", type=float, default=30)
    request.set_defaults(func=command_request)
    return root


if __name__ == "__main__":
    try:
        parsed = build_parser().parse_args()
        raise SystemExit(parsed.func(parsed))
    except ClientError as error:
        print(json.dumps({"provider": "omnix-market", "status": error.provider_status, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
    except urllib.error.HTTPError as error:
        print(json.dumps({"provider": "omnix-market", "status": http_provider_status(error.code), "httpStatus": error.code}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
    except urllib.error.URLError as error:
        print(json.dumps({"provider": "omnix-market", "status": "upstream_unavailable", "error": str(error.reason)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"provider": "omnix-market", "status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
