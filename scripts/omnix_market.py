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
            "content.relationships[].customerQualificationStatus": schema_property(
                spec, relationships, "customerQualificationStatus"
            ),
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


def is_confirmed_competitor(content: dict[str, Any]) -> bool:
    return any(
        isinstance(item, dict)
        and str(item.get("classification") or "").casefold() == "competitor"
        and str(item.get("status") or "").casefold() == "confirmed"
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
    for item in registrations:
        if item.get("verificationStatus") not in {"verified", "confirmed"}:
            continue
        number = str(item.get("registrationNumber") or "").strip()
        jurisdiction = str(item.get("jurisdiction") or company.get("countryCode") or "").strip()
        if number and jurisdiction:
            identity["jurisdiction"] = jurisdiction.upper()
            identity["registrationNumber"] = number
            break
    websites = [item for item in value.get("websites", []) if isinstance(item, dict)]
    accepted_website_statuses = {
        "verified", "confirmed", "verified_by_legal_notice", "domain_confirmed",
        "official_company_disclosure",
    }
    for item in websites:
        if not str(item.get("websiteType") or "").casefold().startswith("official") or item.get("verificationStatus") not in accepted_website_statuses:
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


def first(item: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in item:
            return item[name]
    return default


def evidence_of(item: dict[str, Any]) -> list[dict[str, Any]]:
    fields = (
        "sourceTitle", "sourceUrl", "publisher", "sourceType", "publishedOn",
        "retrievedOn", "locator", "excerpt", "note",
    )
    return [
        {field: source.get(field) for field in fields if field in source}
        for source in item.get("evidence", []) if isinstance(source, dict)
    ]


def backed(item: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {**fields, "evidence": evidence_of(item)}


def current_flag(item: dict[str, Any]) -> bool | None:
    if isinstance(item.get("current"), bool):
        return item["current"]
    status = str(item.get("status") or "").casefold()
    if status in {"active", "current", "confirmed", "verified"}:
        return True
    if status in {"inactive", "historical", "ended"}:
        return False
    return None


def map_company_core(item: dict[str, Any]) -> dict[str, Any]:
    return backed(item,
        companyName=item.get("companyName", ""), entityType=item.get("entityType", "operating_company"),
        country=item.get("country", ""), status=item.get("status", "unknown"), summary=item.get("summary"),
        researchConclusion=item.get("researchConclusion"), foundedOn=item.get("foundedOn"),
        companyScale=item.get("companyScale"), headcount=item.get("headcount"), listingStatus=item.get("listingStatus", "unknown"),
        listingDetails=item.get("listingDetails"), marketPosition=item.get("marketPosition"),
        priority=item.get("priority"), procurementBoundary=item.get("procurementBoundary"),
    )


def map_alias(item: dict[str, Any]) -> dict[str, Any]:
    return backed(item, name=item.get("name", ""), type=first(item, "type", "aliasType", default="trading_name"),
                  language=item.get("language"), current=current_flag(item))


def map_registration(item: dict[str, Any]) -> dict[str, Any]:
    return backed(item, registrationType=item.get("registrationType"), registrationNumber=item.get("registrationNumber"),
                  registeredName=first(item, "registeredName", "legalName"),
                  registeredBusinessScope=first(item, "registeredBusinessScope", "businessScope", default=[]),
                  jurisdiction=item.get("jurisdiction"), status=item.get("status", "unknown"),
                  registeredOn=item.get("registeredOn"), expiresOn=item.get("expiresOn"))


def map_capital(item: dict[str, Any]) -> dict[str, Any]:
    return backed(item, capitalType=item.get("capitalType", "registered_capital"), amount=item.get("amount"),
                  currency=item.get("currency"), asOf=item.get("asOf"), status=item.get("status", "reported"),
                  note=first(item, "note", "description"))


def map_website(item: dict[str, Any]) -> dict[str, Any]:
    url = str(item.get("url") or "")
    parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
    return backed(item, url=url, domain=item.get("domain") or parsed.hostname,
                  type=first(item, "type", "websiteType", default="official"), status=item.get("status", "active"))


def map_address(item: dict[str, Any]) -> dict[str, Any]:
    return backed(item, fullAddress=first(item, "fullAddress", "addressLine", default=""),
                  type=first(item, "type", "addressType", default="other"), country=item.get("country"),
                  region=first(item, "region", "state", "province"), city=item.get("city"),
                  postalCode=item.get("postalCode"), current=current_flag(item))


def map_media(item: dict[str, Any]) -> dict[str, Any]:
    return backed(item, url=item.get("url", ""), mediaType=item.get("mediaType", "image"),
                  caption=item.get("caption"), lastVerifiedOn=item.get("lastVerifiedOn"))


def map_product(item: dict[str, Any]) -> dict[str, Any]:
    return backed(item, name=item.get("name", ""), systemName=item.get("systemName"), type=item.get("type", "product"),
                  category=item.get("category"), description=item.get("description"),
                  technologyTerms=item.get("technologyTerms", []), applications=item.get("applications", []),
                  targetCustomers=item.get("targetCustomers", []), markets=item.get("markets", []),
                  commercialRoles=item.get("commercialRoles", []), manufacturingStatus=item.get("manufacturingStatus", "unknown"),
                  manufacturingDescription=item.get("manufacturingDescription"), factoryLocations=item.get("factoryLocations", []),
                  media=[map_media(child) for child in item.get("media", []) if isinstance(child, dict)],
                  representativeProject=item.get("representativeProject"), status=item.get("status", "claimed"),
                  getoRelevance=item.get("getoRelevance", "unknown"))


def map_identity(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {name: item.get(name) for name in ("jurisdiction", "registrationNumber", "primaryDomain", "otherLegalId")}


def map_participant(item: dict[str, Any]) -> dict[str, Any]:
    return backed(item, name=item.get("name", ""), role=item.get("role", ""), identity=map_identity(item.get("identity")),
                  status=item.get("status", "possible"), lastVerifiedOn=item.get("lastVerifiedOn"))


def map_potential_product(item: dict[str, Any]) -> dict[str, Any]:
    return backed(item, productName=item.get("productName", ""), usageSummary=item.get("usageSummary"))


def map_project(item: dict[str, Any]) -> dict[str, Any]:
    history = item.get("currentOrHistorical")
    kind = item.get("projectKind") or ("historical_case" if history == "historical" else "opportunity" if history in {"current", "future"} else "unknown")
    scale = item.get("scale") if isinstance(item.get("scale"), dict) else {
        "floors": item.get("storeys"), "units": item.get("units"), "area": item.get("buildingArea"),
        "areaUnit": item.get("areaUnit"), "value": item.get("contractValue"), "currency": item.get("currency"),
        "description": item.get("scale"),
    }
    return backed(item, projectName=item.get("projectName", ""), country=item.get("country"), region=item.get("region"),
                  city=first(item, "city", "location"), address=item.get("address"), projectType=item.get("projectType"),
                  projectKind=kind, stage=first(item, "stage", "procurementStage"), status=item.get("status", "unknown"),
                  startOn=first(item, "startOn", "startedOn"), expectedCompletionOn=item.get("expectedCompletionOn"),
                  completedOn=first(item, "completedOn", "endedOn"), scale=scale,
                  companyRole=first(item, "companyRole", "targetCompanyRole"),
                  participants=[map_participant(child) for child in item.get("participants", []) if isinstance(child, dict)],
                  productsOrTechnologies=item.get("productsOrTechnologies", []),
                  potentialProducts=[map_potential_product(child) for child in item.get("potentialProducts", []) if isinstance(child, dict)],
                  demandJudgement=item.get("demandJudgement"), entryWindow=item.get("entryWindow"),
                  opportunity=first(item, "opportunity", "getoOpportunity"), procurementBoundary=item.get("procurementBoundary"),
                  knownRelationship=item.get("knownRelationship"), getoRelevance=item.get("getoRelevance"),
                  verificationStatus=first(item, "verificationStatus", "roleVerificationStatus", default="claimed"),
                  lastVerifiedOn=item.get("lastVerifiedOn"), importantNotes=first(item, "importantNotes", "description"))


def map_exclusivity(item: Any) -> dict[str, Any]:
    value = item if isinstance(item, dict) else {"status": "unknown", "evidence": []}
    return backed(value, status=value.get("status", "unknown"), scope=value.get("scope"),
                  description=value.get("description"), lastVerifiedOn=value.get("lastVerifiedOn"))


def map_compact_assessment(item: Any, entry: bool = False) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    fields = {"score": item.get("score"), "maxScore": item.get("maxScore", 5),
              "rationale": item.get("rationale"), "assessedOn": item.get("assessedOn")} if entry else {
        "overallScore": item.get("overallScore"), "grade": item.get("grade"), "assessedOn": item.get("assessedOn")
    }
    return backed(item, **fields)


def map_relationship(item: dict[str, Any]) -> dict[str, Any]:
    qualification = first(item, "customerQualificationStatus", "reviewDecision", default="pending")
    return backed(item, relatedPartyName=first(item, "relatedPartyName", "counterpartyName", default=""),
                  relatedPartyIdentity=map_identity(item.get("relatedPartyIdentity")),
                  relatedPartyType=first(item, "relatedPartyType", default="company"),
                  relationshipType=item.get("relationshipType", "other"), direction=item.get("direction", "mutual"),
                  projectName=item.get("projectName"), productName=first(item, "productName", "productOrService"),
                  country=item.get("country"), description=item.get("description"),
                  cooperationMode=first(item, "cooperationMode", "cooperationModeCode"),
                  cooperationDepth=first(item, "cooperationDepth", "cooperationDepthCode"),
                  customerQualificationStatus=qualification, buyer=item.get("buyer"), actualUser=item.get("actualUser"),
                  customerValueAssessment=map_compact_assessment(item.get("customerValueAssessment")),
                  entryAssessment=map_compact_assessment(item.get("entryAssessment"), entry=True),
                  entryPoint=item.get("entryPoint"), limitations=item.get("limitations", []),
                  exclusivity=map_exclusivity(item.get("exclusivity")), status=item.get("status", "possible"),
                  startedOn=item.get("startedOn"), endedOn=item.get("endedOn"), lastVerifiedOn=item.get("lastVerifiedOn"))


def map_capability_context(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {name: item.get(name) for name in (
        "foundationKey", "foundationVersion", "asOf", "status", "contentHash", "productCodes",
        "scenarioCodes", "roleCodes", "caseKeys", "gapCodes",
    )}


def map_assessment(item: Any) -> dict[str, Any]:
    value = item if isinstance(item, dict) else {}
    completed = value.get("status") == "completed"
    dimensions = [] if not completed else [
        backed(child, name=child.get("name", ""), score=first(child, "score", "finalDimensionScore"),
               maxScore=child.get("maxScore"), level=child.get("level"), rationale=child.get("rationale"))
        for child in value.get("dimensions", []) if isinstance(child, dict)
    ]
    result = backed(value, grade=value.get("grade") if completed else None,
                    overallScore=value.get("overallScore") if completed else None,
                    overallConclusion=value.get("overallConclusion"), assessedOn=value.get("assessedOn"),
                    informationConfirmationRate=first(value, "informationConfirmationRate", "informationCompleteness"),
                    dimensions=dimensions, capabilityContext=map_capability_context(value.get("capabilityContext")))
    if result["capabilityContext"] is None:
        result.pop("capabilityContext")
    return result


def map_portfolio(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict) or item.get("status") == "not_requested":
        return None
    customers = [backed(child, companyName=child.get("companyName", ""), country=child.get("country"),
                        relationshipCount=child.get("relationshipCount", 0),
                        customerAssessmentStatus=child.get("customerAssessmentStatus", "not_scored"),
                        customerValueScore=child.get("customerValueScore"),
                        customerValueModelVersion=child.get("customerValueModelVersion"),
                        cohortBaselineVersion=child.get("cohortBaselineVersion"), assessedOn=child.get("assessedOn"))
                 for child in item.get("customers", []) if isinstance(child, dict)]
    return {
        "assessmentType": item.get("assessmentType"), "status": item.get("status"), "modelCode": item.get("modelCode"),
        "modelVersion": item.get("modelVersion"), "customerValueModelCode": item.get("customerValueModelCode"),
        "asOf": item.get("asOf"), "verifiedCustomerCount": item.get("verifiedCustomerCount", 0),
        "scoredCustomerCount": item.get("scoredCustomerCount", 0), "customerScoreCoverage": item.get("customerScoreCoverage", 0),
        "averageCustomerValueScore": item.get("averageCustomerValueScore"), "customers": customers,
    }


def map_content(value: dict[str, Any]) -> dict[str, Any]:
    company = value.get("company") if isinstance(value.get("company"), dict) else {}
    content = {
        "company": map_company_core(company),
        "aliases": [map_alias(item) for item in value.get("aliases", []) if isinstance(item, dict)],
        "registrations": [map_registration(item) for item in value.get("registrations", []) if isinstance(item, dict)],
        "capitalRecords": [map_capital(item) for item in value.get("capitalRecords", []) if isinstance(item, dict)],
        "websites": [map_website(item) for item in value.get("websites", []) if isinstance(item, dict)],
        "addresses": [map_address(item) for item in value.get("addresses", []) if isinstance(item, dict)],
        "marketPresence": [backed(item, country=item.get("country"), region=item.get("region"),
            presenceType=item.get("presenceType", "claimed_only"), status=item.get("status", "possible"),
            description=item.get("description")) for item in value.get("marketPresence", []) if isinstance(item, dict)],
        "socialChannels": [backed(item, platform=item.get("platform", ""), url=item.get("url", ""),
            handle=item.get("handle"), officialStatus=first(item, "officialStatus", "status", default="unconfirmed"),
            lastActivityOn=item.get("lastActivityOn")) for item in value.get("socialChannels", []) if isinstance(item, dict)],
        "researchClassifications": [backed(item, classification=item.get("classification", ""),
            status=item.get("status", "possible"), country=item.get("country"), productScope=item.get("productScope", []),
            reason=item.get("reason", "")) for item in value.get("researchClassifications", []) if isinstance(item, dict)],
        "companyRoles": [backed(item, role=item.get("role", ""), scope=item.get("scope"), country=item.get("country"),
            projectName=item.get("projectName"), status=item.get("status", "possible"), rationale=item.get("rationale"))
            for item in value.get("companyRoles", []) if isinstance(item, dict)],
        "productsAndServices": [map_product(item) for item in value.get("productsAndServices", []) if isinstance(item, dict)],
        "projects": [map_project(item) for item in value.get("projects", []) if isinstance(item, dict)],
        "relationships": [map_relationship(item) for item in value.get("relationships", []) if isinstance(item, dict)],
        "contacts": [backed(item, **{key: item.get(key) for key in (
            "contactType", "name", "jobTitle", "department", "seniority", "responsibilities", "buyingRole", "location",
            "workEmail", "workPhone", "linkedinUrl", "otherProfileUrl", "verificationStatus", "lastVerifiedOn")})
            for item in value.get("contacts", []) if isinstance(item, dict)],
        "financialRecords": [backed(item, **{key: item.get(key) for key in (
            "recordType", "subjectEntity", "financialScope", "scope", "accountingScope",
            "relationshipToTarget", "period", "value", "currency", "unit", "valueStatus", "description")})
            for item in value.get("financialRecords", []) if isinstance(item, dict)],
        "assessment": map_assessment(value.get("assessment")), "competitorCustomerPortfolio": map_portfolio(value.get("competitorCustomerPortfolio")),
        "researchStatus": value.get("researchStatus"), "lastResearchedOn": value.get("lastResearchedOn"),
    }
    content["licensesAndCertifications"] = [backed(item, name=first(item, "name", "licenseName", default=""),
        type=first(item, "type", "licenseType", default="other"), number=first(item, "number", "licenseNumber"),
        holderName=item.get("holderName"), issuer=first(item, "issuer", "authority"), jurisdiction=item.get("jurisdiction"),
        scope=item.get("scope"), status=item.get("status", "unknown"), validFrom=first(item, "validFrom", "issuedOn"),
        validUntil=first(item, "validUntil", "expiresOn")) for item in value.get("licensesAndCertifications", []) if isinstance(item, dict)]
    content["newsAndSocialMedia"] = [backed(item, title=item.get("title", ""), type=first(item, "type", "itemType", default="other"),
        publisherOrPlatform=first(item, "publisherOrPlatform", "publisher", "platform"), publishedOn=item.get("publishedOn"),
        url=item.get("url"), summary=item.get("summary"), sentiment=item.get("sentiment", "neutral"),
        relatedProject=item.get("relatedProject"), businessMeaning=item.get("businessMeaning"))
        for item in value.get("newsAndSocialMedia", []) if isinstance(item, dict)]
    content["customsTransactions"] = [backed(item, **{key: item.get(key) for key in (
        "resultType", "direction", "importer", "exporter", "partnerCountry", "transactionOn", "dateRange", "hsCode",
        "productDescription", "quantity", "quantityUnit", "value", "currency", "recordCount", "provider", "queryScope",
        "verificationStatus", "notes")}, originPort=first(item, "originPort", default=(item.get("ports") or [None])[0]),
        destinationPort=first(item, "destinationPort", default=(item.get("ports") or [None, None])[-1]))
        for item in value.get("customsTransactions", []) if isinstance(item, dict)]
    content["lawsuitsAndCompliance"] = [backed(item, type=first(item, "type", "recordType", default="other"),
        title=item.get("title") or item.get("description") or "Compliance record", caseNumber=item.get("caseNumber"),
        authorityOrCourt=first(item, "authorityOrCourt", "authority"), jurisdiction=item.get("jurisdiction"),
        parties=item.get("parties", []), filedOn=first(item, "filedOn", "recordOn"), status=item.get("status", "unknown"),
        outcome=item.get("outcome"), amount=item.get("amount"), currency=item.get("currency"),
        relatedProject=item.get("relatedProject"), riskImpact=first(item, "riskImpact", "description"))
        for item in value.get("lawsuitsAndCompliance", []) if isinstance(item, dict)]
    content["inquiries"] = [backed(item, **{key: item.get(key) for key in (
        "receivedOn", "buyerName", "buyerContact", "buyerRole", "requestedProduct", "quantity", "quantityUnit",
        "technicalRequirements", "projectName", "projectCountry", "deliveryDestination", "deliveryPort", "signingEntity",
        "payer", "paymentTerms", "requestedDocuments", "attachments", "verificationStatus", "openQuestions")})
        for item in value.get("inquiries", []) if isinstance(item, dict)]
    content["risks"] = [backed(item, category=first(item, "category", "riskType", default="other"),
        level=first(item, "level", "severity", default="unknown"), finding=first(item, "finding", "description", default=""),
        impact=item.get("impact"), blocking=item.get("blocking"), mitigation=item.get("mitigation"))
        for item in value.get("risks", []) if isinstance(item, dict)]
    content["missingInformation"] = [backed(item, topic=item.get("topic", ""), status=item.get("status", "not_found"),
        description=item.get("description"), whyItMatters=first(item, "whyItMatters", "impact"),
        checkedScope=item.get("checkedScope"), recommendedAction=item.get("recommendedAction"))
        for item in value.get("missingInformation", []) if isinstance(item, dict)]
    content["recommendedActions"] = [backed(item, action=item.get("action", ""), priority=item.get("priority", "medium"),
        owner=item.get("owner", "research"), timing=item.get("timing"), reason=first(item, "reason", "rationale"))
        for item in value.get("recommendedActions", []) if isinstance(item, dict)]
    content["additionalInformation"] = [backed(item, topic=item.get("topic", ""), title=item.get("title", ""),
        details=item.get("details")) for item in value.get("additionalInformation", []) if isinstance(item, dict)]
    return content


def project_company(value: dict[str, Any], visibility: str, as_of: str | None,
                    market_code: str | None, scope_code: str) -> dict[str, Any]:
    if visibility not in {"private", "public"}:
        raise ValueError("visibility must be private or public")
    company = value.get("company")
    if not isinstance(company, dict):
        raise ValueError("company.json requires company")
    code = str(market_code or company.get("countryCode") or "").upper()
    if code != "GLOBAL" and not re.fullmatch(r"[A-Z]{2}", code):
        raise ValueError("marketCode must be an uppercase ISO 3166-1 alpha-2 code or GLOBAL")
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
    content = map_content(value)
    if content.get("competitorCustomerPortfolio") is None:
        content.pop("competitorCustomerPortfolio", None)
    lead_items = [item for item in content.get("researchClassifications", [])
                  if isinstance(item, dict)
                  and str(item.get("classification") or "").casefold() == "lead"
                  and str(item.get("status") or "").casefold() != "rejected"]
    competitor_items = [item for item in content.get("researchClassifications", [])
                        if isinstance(item, dict)
                        and str(item.get("classification") or "").casefold() == "competitor"
                        and str(item.get("status") or "").casefold() == "confirmed"]
    assessment = content.get("assessment", {})
    lead_ready = bool(assessment.get("overallScore") is not None
                      and assessment.get("grade")
                      and assessment.get("dimensions"))
    if competitor_items and lead_items and not lead_ready:
        content["researchClassifications"] = [item for item in content.get("researchClassifications", [])
                                               if not (isinstance(item, dict)
                                                       and str(item.get("classification") or "").casefold() == "lead")]
        content.pop("assessment", None)
    if is_lead(content):
        assessment = content.get("assessment", {})
        if assessment.get("overallScore") is None or not assessment.get("grade") or not assessment.get("dimensions"):
            raise ValueError("lead upload requires a completed six-dimension cohort assessment")
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
            action = "uploaded" if is_create else "updated"
            upload_status = f"{action}_{'public' if returned_visibility == 'public' else 'private'}"
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
