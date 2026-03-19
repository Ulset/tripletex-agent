"""Tripletex OpenAPI spec loader and search tool.

Fetches the OpenAPI spec once and provides a search function
that the agent can use to discover endpoints and their schemas.
Supports OpenAPI 3.x (requestBody/content) with 2.x fallback (parameters[in=body]).
"""

import json
import logging
from functools import lru_cache

import requests

logger = logging.getLogger(__name__)

OPENAPI_URL = "https://tripletex.no/v2/openapi.json"

# Registry of curated endpoints with business-logic notes.
# Field names are validated against the spec at test time.
# (method, spec_path, required_fields, notes)
ENDPOINT_REGISTRY = [
    ("POST", "/employee", ["firstName", "lastName", "userType", "email", "department"],
     'userType must be "STANDARD"'),
    ("POST", "/employee/employment", ["employee", "startDate"], ""),
    ("POST", "/customer", ["name"], ""),
    ("POST", "/supplier", ["name", "isSupplier"], "isSupplier must be true"),
    ("POST", "/product", ["name", "number"], ""),
    ("POST", "/project", ["name", "number", "projectManager", "startDate"], ""),
    ("POST", "/department", ["name", "departmentNumber"], ""),
    ("POST", "/order", ["customer", "deliveryDate", "orderLines"],
     "orderLines use 'count' for quantity"),
    ("PUT", "/order/{id}/:invoice", [], "Create invoice FROM order. invoiceDate REQUIRED query param."),
    ("PUT", "/invoice/{id}/:payment", [], "QUERY PARAMS only, no body."),
    ("GET", "/invoice/paymentType", [], 'Find paymentTypeId for "Bankinnskudd"'),
    ("GET", "/invoice", [], "invoiceDateFrom + invoiceDateTo both REQUIRED"),
    ("GET", "/employee", [], "?email=X to find by email"),
    ("GET", "/customer", [], "?organizationNumber=X to find by org number"),
    ("GET", "/department", [], "?fields=id&count=1 to get a department ID"),
]


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


def _get_request_body_schema(method_info: dict) -> dict | None:
    """Extract request body schema, supporting both OpenAPI 3.x and 2.x."""
    # OpenAPI 3.x: requestBody.content['application/json; charset=utf-8'].schema
    rb = method_info.get("requestBody", {}).get("content", {})
    for content_type, content_val in rb.items():
        if "json" in content_type:
            return content_val.get("schema")
    # OpenAPI 2.x fallback: parameters[in=body].schema
    for p in method_info.get("parameters", []):
        if p.get("in") == "body":
            return p.get("schema")
    return None


def _get_response_schema(response_info: dict) -> dict | None:
    """Extract response schema, supporting both OpenAPI 3.x and 2.x."""
    # OpenAPI 3.x: content['application/json'].schema
    content = response_info.get("content", {})
    for content_type, content_val in content.items():
        if "json" in content_type:
            return content_val.get("schema")
    # OpenAPI 2.x fallback: schema directly on response
    return response_info.get("schema") or None


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


def _match_runtime_path_to_spec(runtime_path: str, spec: dict) -> str | None:
    """Match a runtime path like /v2/invoice/123/:payment to a spec path like /invoice/{id}/:payment."""
    # Strip /v2 prefix — spec paths don't have it
    path = runtime_path
    if path.startswith("/v2"):
        path = path[3:]

    runtime_segments = path.strip("/").split("/")
    paths = spec.get("paths", {})

    best_match = None
    best_literal_count = -1

    for spec_path in paths:
        spec_segments = spec_path.strip("/").split("/")
        if len(spec_segments) != len(runtime_segments):
            continue

        match = True
        literal_count = 0
        for runtime_seg, spec_seg in zip(runtime_segments, spec_segments):
            if spec_seg.startswith("{") and spec_seg.endswith("}"):
                continue  # Param segment matches anything
            if runtime_seg != spec_seg:
                match = False
                break
            literal_count += 1

        if match and literal_count > best_literal_count:
            best_match = spec_path
            best_literal_count = literal_count

    return best_match


def get_endpoint_schema(method: str, endpoint: str) -> str | None:
    """Get schema fields for an endpoint, used to enrich 422 errors."""
    try:
        spec = _load_spec()
    except Exception:
        return None

    spec_path = _match_runtime_path_to_spec(endpoint, spec)
    if not spec_path:
        return None

    path_info = spec.get("paths", {}).get(spec_path, {})
    method_info = path_info.get(method.lower())
    if not method_info:
        return None

    # Try request body fields (OpenAPI 3.x + 2.x)
    body_schema = _get_request_body_schema(method_info)
    if body_schema:
        fields = _extract_schema_fields(spec, body_schema)
        if fields:
            return f"Valid fields for {method.upper()} /v2{spec_path}:\n" + "\n".join(fields)

    # Fall back to query params
    params = method_info.get("parameters", [])
    query_params = [p for p in params if p.get("in") == "query"]
    if query_params:
        param_strs = []
        for p in query_params:
            req = " (REQUIRED)" if p.get("required") else ""
            param_strs.append(f"  {p['name']}{req}")
        return f"Valid query params for {method.upper()} /v2{spec_path}:\n" + "\n".join(param_strs)

    return None


def _get_schema_field_names(spec: dict, schema: dict, depth: int = 0) -> set[str]:
    """Return a flat set of lowercase field names from a schema, recursing into array items."""
    if depth > 1:
        return set()

    if "$ref" in schema:
        schema = _resolve_ref(spec, schema["$ref"])

    names = set()
    props = schema.get("properties", {})
    for name, prop in props.items():
        names.add(name.lower())
        actual = prop
        if "$ref" in prop:
            actual = _resolve_ref(spec, prop["$ref"])
        # Recurse into array items
        if actual.get("type") == "array":
            items = actual.get("items", {})
            names |= _get_schema_field_names(spec, items, depth + 1)

    return names


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
            # Fallback: check if query words match request body field names (3.x + 2.x)
            for method_info in methods.values():
                if isinstance(method_info, dict):
                    body_schema = _get_request_body_schema(method_info)
                    if body_schema:
                        field_names = _get_schema_field_names(spec, body_schema)
                        if any(w in field_names for w in query_words):
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

            # Request body schema (OpenAPI 3.x + 2.x)
            body_schema = _get_request_body_schema(info)
            if body_schema:
                fields = _extract_schema_fields(spec, body_schema)
                if fields:
                    entry += "\n  Request body fields:"
                    for f in fields[:25]:  # Limit to avoid huge output
                        entry += f"\n    {f}"
                    if len(fields) > 25:
                        entry += f"\n    ... and {len(fields) - 25} more fields"

            # Response schema (200/201) — OpenAPI 3.x + 2.x
            resp_info = info.get("responses", {})
            for code in ["200", "201"]:
                if code in resp_info:
                    resp_schema = _get_response_schema(resp_info[code])
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


def generate_endpoint_reference() -> str:
    """Generate endpoint field reference from the OpenAPI spec and ENDPOINT_REGISTRY.

    Field names come from the spec (source of truth). Required markers and
    business-logic notes come from the curated registry (hand-maintained).
    Falls back to registry-only info if the spec is unavailable.
    """
    try:
        spec = _load_spec()
    except Exception:
        spec = None

    lines = []
    for method, path, required_fields, notes in ENDPOINT_REGISTRY:
        entry = f"- {method} /v2{path}"

        # Try to get field info from spec
        spec_fields_req = []
        spec_fields_other = []
        query_params = []
        if spec:
            path_info = spec.get("paths", {}).get(path, {})
            method_info = path_info.get(method.lower(), {})
            if method_info:
                # Body fields — required fields first
                body_schema = _get_request_body_schema(method_info)
                if body_schema:
                    if "$ref" in body_schema:
                        body_schema = _resolve_ref(spec, body_schema["$ref"])
                    props = body_schema.get("properties", {})
                    for fname in props:
                        if fname in ("id", "version", "url", "changes"):
                            continue
                        if fname in required_fields:
                            spec_fields_req.append(f"{fname} (REQ)")
                        else:
                            spec_fields_other.append(fname)

                # Query params
                for p in method_info.get("parameters", []):
                    if p.get("in") == "query":
                        req = " (REQ)" if p.get("required") else ""
                        query_params.append(f"{p['name']}{req}")

        # Required fields always shown first, then fill up to 15
        spec_fields = spec_fields_req + spec_fields_other
        if spec_fields:
            shown = spec_fields_req + spec_fields_other[:max(0, 15 - len(spec_fields_req))]
            remaining = len(spec_fields) - len(shown)
            entry += f" — fields: {', '.join(shown)}"
            if remaining > 0:
                entry += f" (+{remaining} more)"
        elif required_fields:
            # Fallback: use registry required fields only
            entry += f" — required: {', '.join(required_fields)}"

        if query_params:
            entry += f" | query: {', '.join(query_params[:8])}"
            if len(query_params) > 8:
                entry += f" (+{len(query_params) - 8} more)"

        if notes:
            entry += f". {notes}"

        lines.append(entry)

    return "\n".join(lines)
