#!/usr/bin/env python3
"""Generate a complete synthetic Company Aggregate request reference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import omnix_market


def empty_paths(value: Any, path: str = "$") -> list[str]:
    if value is None or value == "" or value == [] or value == {}:
        return [path]
    if isinstance(value, dict):
        return [item for key, child in value.items() for item in empty_paths(child, f"{path}.{key}")]
    if isinstance(value, list):
        return [item for index, child in enumerate(value) for item in empty_paths(child, f"{path}[{index}]")]
    return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("company_json", type=Path)
    parser.add_argument("--openapi", type=Path, required=True)
    parser.add_argument("--scoring-criteria-hash", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = json.loads(args.company_json.expanduser().resolve().read_text(encoding="utf-8"))
    body = omnix_market.project_company(source, "public", None, None, "construction_formwork")
    body["scoringCriteriaHash"] = args.scoring_criteria_hash

    spec = json.loads(args.openapi.expanduser().resolve().read_text(encoding="utf-8"))
    operation = omnix_market.operation_definition(
        spec, f"{omnix_market.MARKET_ROOT}/companies", "POST"
    )
    schema = omnix_market.request_schema(spec, operation)
    errors = omnix_market.validate_json_schema(body, schema, spec)
    if errors:
        raise SystemExit("schema errors: " + "; ".join(errors))
    empty = empty_paths(body)
    if empty:
        raise SystemExit("empty aggregate values: " + ", ".join(empty))
    omnix_market.atomic_write_json(args.output.expanduser().resolve(), body)


if __name__ == "__main__":
    main()
