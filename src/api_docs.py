"""Tripletex OpenAPI spec loader and search tool.

Fetches the OpenAPI spec once and provides a search function
that the agent can use to discover endpoints and their schemas.
"""

import json
import logging
from functools import lru_cache

import requests

logger = logging.getLogger(__name__)

OPENAPI_URL = "https://tripletex.no/v2/openapi.json"


@lru_cache(maxsize=1)
def _load_spec() -> dict:
    """Fetch and cache the OpenAPI spec."""
    logger.info("Fetching OpenAPI spec from %s", OPENAPI_URL)
    resp = requests.get(OPENAPI_URL, timeout=30)
    resp.raise_for_status()
    spec = resp.json()
    logger.info("Loaded OpenAPI spec: %d paths", len(spec.get("paths", {})))
    return spec


def _resolve_ref(spec: dict, ref: str) -> dict:
    """Resolve a $ref pointer like '#/definitions/Employee'."""
    parts = ref.lstrip("#/").split("/")
    node = spec
    for part in parts:
        node = node.get(part, {})
    return node


def _extract_schema_fields(spec: dict, schema: dict, depth: int = 0) -> list[str]:
    """Extract field names and types from a schema, resolving refs."""
    if depth > 2:
        return []

    if "$ref" in schema:
        schema = _resolve_ref(spec, schema["$ref"])

    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields = []
    for name, prop in props.items():
        if name in ("id", "version", "url", "changes"):
            continue  # Skip meta fields

        # Resolve nested ref for type info
        actual = prop
        if "$ref" in prop:
            actual = _resolve_ref(spec, prop["$ref"])

        type_str = actual.get("type", "object")
        desc = actual.get("description", "")
        req_marker = " (REQUIRED)" if name in required else ""

        # For nested objects, show their fields too
        if type_str == "object" or "$ref" in prop:
            nested = _extract_schema_fields(spec, prop, depth + 1)
            if nested:
                fields.append(f"  {name}{req_marker}: object with fields: {', '.join(nested)}")
            else:
                fields.append(f"  {name}{req_marker}: object")
        elif type_str == "array":
            items = actual.get("items", {})
            if "$ref" in items:
                item_name = items["$ref"].split("/")[-1]
                fields.append(f"  {name}{req_marker}: array of {item_name}")
            else:
                fields.append(f"  {name}{req_marker}: array")
        else:
            extra = ""
            if desc and len(desc) < 80:
                extra = f" — {desc}"
            fields.append(f"  {name}{req_marker}: {type_str}{extra}")

    return fields


def search_api_docs(query: str) -> str:
    """Search the Tripletex OpenAPI spec for endpoints matching a query.

    Returns a formatted string with matching endpoints, their methods,
    parameters, and request/response schemas.
    """
    spec = _load_spec()
    paths = spec.get("paths", {})
    query_lower = query.lower()

    # Split query into words for flexible matching — match if ANY word hits
    query_words = [w for w in query_lower.split() if len(w) > 2]

    results = []
    for path, methods in paths.items():
        path_lower = path.lower()
        # Match if the full query OR any individual word matches path/summary/tags
        path_match = query_lower in path_lower
        if not path_match:
            path_match = any(w in path_lower for w in query_words)
        if not path_match:
            for method_info in methods.values():
                if isinstance(method_info, dict):
                    summary = method_info.get("summary", "").lower()
                    desc = method_info.get("description", "").lower()
                    tags = " ".join(method_info.get("tags", [])).lower()
                    searchable = f"{summary} {desc} {tags}"
                    if query_lower in searchable or any(w in searchable for w in query_words):
                        path_match = True
                        break

        if not path_match:
            continue

        for method, info in methods.items():
            if not isinstance(info, dict) or method == "parameters":
                continue

            entry = f"\n{method.upper()} /v2{path}"
            summary = info.get("summary", "")
            if summary:
                entry += f"\n  Summary: {summary}"

            # Query parameters
            params = info.get("parameters", [])
            query_params = [p for p in params if p.get("in") == "query"]
            if query_params:
                param_strs = []
                for p in query_params:
                    req = " (REQUIRED)" if p.get("required") else ""
                    param_strs.append(f"{p['name']}{req}")
                entry += f"\n  Query params: {', '.join(param_strs)}"

            # Request body schema
            body_params = [p for p in params if p.get("in") == "body"]
            if body_params:
                body_schema = body_params[0].get("schema", {})
                fields = _extract_schema_fields(spec, body_schema)
                if fields:
                    entry += "\n  Request body fields:"
                    for f in fields[:25]:  # Limit to avoid huge output
                        entry += f"\n    {f}"
                    if len(fields) > 25:
                        entry += f"\n    ... and {len(fields) - 25} more fields"

            # Response schema (200/201)
            responses = info.get("responses", {})
            for code in ["200", "201"]:
                if code in responses:
                    resp_schema = responses[code].get("schema", {})
                    if resp_schema:
                        fields = _extract_schema_fields(spec, resp_schema)
                        if fields:
                            entry += f"\n  Response ({code}) fields:"
                            for f in fields[:15]:
                                entry += f"\n    {f}"
                            if len(fields) > 15:
                                entry += f"\n    ... and {len(fields) - 15} more fields"

            results.append(entry)

        if len(results) >= 10:
            break

    if not results:
        return f"No endpoints found matching '{query}'. Try a different search term like 'employee', 'invoice', 'customer', etc."

    header = f"Found {len(results)} endpoint(s) matching '{query}':\n"
    return header + "\n".join(results)
