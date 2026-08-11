#!/usr/bin/env python3
"""OpenAPI-gated client for OmniX Market read and private-draft APIs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


MARKET_PREFIX = "/api/market-intelligence/v1/"
DENIED_MARKERS = ("/approvals", ":approve", ":reject")


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
        raise ClientError("not_configured", "OMNIX_OPENAPI_URL must use the same origin as OMNIX_API_BASE_URL")
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
    lower = template.lower()
    if not template.startswith(MARKET_PREFIX) or any(marker in lower for marker in DENIED_MARKERS):
        return False
    if method == "GET":
        return "/drafts" not in lower
    if method == "POST" and template.endswith(":resolve"):
        return True
    return method in {"POST", "PUT", "DELETE"} and "/drafts" in lower


def available_operations(spec: dict[str, Any]) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    for template, path_item in spec["paths"].items():
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
    pattern = re.sub(r"\\\{[^{}]+\\\}", r"[^/]+", escaped)
    return re.compile(f"^{pattern}$")


def resolve_operation(spec: dict[str, Any], method: str, concrete_path: str) -> str:
    matches = [
        item["path"]
        for item in available_operations(spec)
        if item["method"] == method and template_regex(item["path"]).match(concrete_path)
    ]
    if len(matches) != 1:
        raise ValueError(f"request does not match exactly one allowed OpenAPI operation: {matches}")
    return matches[0]


def read_body(path: str | None) -> bytes | None:
    if path is None:
        return None
    if path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8")
    value = json.loads(raw)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def command_capabilities(_: argparse.Namespace) -> int:
    _, _, spec_url = config()
    spec = load_openapi(spec_url)
    operations = available_operations(spec)
    status = "available" if operations else "upstream_unavailable"
    print(json.dumps({"provider": "omnix-market", "status": status, "operations": operations}, ensure_ascii=False, indent=2))
    return 0 if operations else 1


def command_request(args: argparse.Namespace) -> int:
    base, key, spec_url = config()
    method = args.method.upper()
    parsed_path = urllib.parse.urlsplit(args.path)
    if parsed_path.scheme or parsed_path.netloc or not parsed_path.path.startswith("/"):
        raise ValueError("path must be an absolute-path reference, not a URL")
    spec = load_openapi(spec_url)
    template = resolve_operation(spec, method, parsed_path.path)
    is_submit = template.endswith("drafts:submit")
    is_resolve = template.endswith(":resolve")
    if method == "POST" and not is_submit and not is_resolve and not args.idempotency_key:
        raise ValueError("draft create POST requires --idempotency-key")
    if method in {"PUT", "DELETE"} and not args.if_match:
        raise ValueError(f"{method} requires --if-match with the current owner draft ETag")
    if method == "DELETE" and not args.confirm_delete:
        raise ValueError("DELETE requires --confirm-delete after explicit user intent")
    if is_submit and not args.confirm_submit:
        raise ValueError("draft submit requires --confirm-submit after explicit user intent")
    data = read_body(args.body)
    if method in {"POST", "PUT"} and data is None:
        raise ValueError(f"{method} requires --body")
    headers = {"Accept": "application/json", "X-API-KEY": key}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if args.idempotency_key:
        headers["Idempotency-Key"] = args.idempotency_key
    if args.if_match:
        headers["If-Match"] = args.if_match
    url = f"{base}{args.path}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        response = opener().open(request, timeout=args.timeout)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(json.dumps({"provider": "omnix-market", "providerStatus": http_provider_status(error.code), "httpStatus": error.code, "body": parse_body(body)}, ensure_ascii=False, indent=2))
        return 1
    with response:
        raw = response.read().decode("utf-8", errors="replace")
        result = {
            "provider": "omnix-market",
            "providerStatus": "available",
            "httpStatus": response.status,
            "etag": response.headers.get("ETag"),
            "retryAfter": response.headers.get("Retry-After"),
            "body": parse_body(raw),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def parse_body(raw: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def http_provider_status(status: int) -> str:
    return {
        401: "unauthenticated",
        403: "forbidden",
        429: "rate_limited",
    }.get(status, "upstream_unavailable" if status >= 500 else "failed")


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    capabilities = sub.add_parser("capabilities")
    capabilities.set_defaults(func=command_capabilities)
    request = sub.add_parser("request")
    request.add_argument("method", choices=("GET", "POST", "PUT", "DELETE"))
    request.add_argument("path")
    request.add_argument("--body", help="JSON file path, or - for stdin")
    request.add_argument("--idempotency-key")
    request.add_argument("--if-match")
    request.add_argument("--confirm-delete", action="store_true")
    request.add_argument("--confirm-submit", action="store_true")
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
