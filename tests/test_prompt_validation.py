"""Validation tests: registry entries match the OpenAPI spec, and OpenAPI 3.x parsing works.

These tests fetch the real Tripletex OpenAPI spec and verify that:
1. Every endpoint in ENDPOINT_REGISTRY exists in the spec
2. Every required_field in the registry is a real property in the endpoint's body schema
3. OpenAPI 3.x request body and response parsing works correctly
"""

from unittest.mock import patch

import pytest
import requests

from src.api_docs import (
    ENDPOINT_REGISTRY,
    _get_request_body_schema,
    _get_response_schema,
    _load_spec,
    _resolve_ref,
    generate_endpoint_reference,
    get_endpoint_schema,
    search_api_docs,
)


def _fetch_spec():
    """Fetch the real OpenAPI spec (cached per test session)."""
    try:
        return _load_spec()
    except Exception:
        pytest.skip("Cannot fetch OpenAPI spec")


class TestEndpointRegistryMatchesSpec:
    """Every endpoint in the registry must exist in the OpenAPI spec."""

    def test_all_registry_paths_exist(self):
        spec = _fetch_spec()
        paths = spec.get("paths", {})
        for method, path, _, _ in ENDPOINT_REGISTRY:
            assert path in paths, f"Path {path} not found in spec"
            assert method.lower() in paths[path], (
                f"{method} not found for {path} in spec"
            )

    def test_all_required_fields_exist_in_schema(self):
        spec = _fetch_spec()
        paths = spec.get("paths", {})
        for method, path, required_fields, _ in ENDPOINT_REGISTRY:
            if not required_fields:
                continue
            method_info = paths.get(path, {}).get(method.lower(), {})
            body_schema = _get_request_body_schema(method_info)
            assert body_schema is not None, (
                f"No request body for {method} {path} but registry lists required fields: {required_fields}"
            )
            # Resolve $ref to get properties
            if "$ref" in body_schema:
                body_schema = _resolve_ref(spec, body_schema["$ref"])
            props = body_schema.get("properties", {})
            for field in required_fields:
                assert field in props, (
                    f"Field '{field}' not in schema for {method} {path}. "
                    f"Available: {sorted(props.keys())}"
                )

    def test_generated_prompt_contains_spec_field_names(self):
        spec = _fetch_spec()
        ref_text = generate_endpoint_reference()
        # Spot-check a few known fields that must appear
        assert "firstName" in ref_text
        assert "lastName" in ref_text
        assert "deliveryDate" in ref_text
        assert "orderLines" in ref_text


class TestOpenAPI3xParsing:
    """Verify that OpenAPI 3.x requestBody/content parsing works."""

    def test_get_request_body_schema_3x(self):
        method_info = {
            "requestBody": {
                "content": {
                    "application/json; charset=utf-8": {
                        "schema": {"$ref": "#/components/schemas/Employee"}
                    }
                },
                "required": True,
            }
        }
        schema = _get_request_body_schema(method_info)
        assert schema is not None
        assert schema["$ref"] == "#/components/schemas/Employee"

    def test_get_request_body_schema_2x_fallback(self):
        method_info = {
            "parameters": [
                {"in": "body", "schema": {"$ref": "#/definitions/Employee"}}
            ]
        }
        schema = _get_request_body_schema(method_info)
        assert schema is not None
        assert schema["$ref"] == "#/definitions/Employee"

    def test_get_request_body_schema_none(self):
        method_info = {"parameters": [{"in": "query", "name": "id"}]}
        assert _get_request_body_schema(method_info) is None

    def test_get_response_schema_3x(self):
        response_info = {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ResponseWrapperEmployee"}
                }
            }
        }
        schema = _get_response_schema(response_info)
        assert schema is not None
        assert "ResponseWrapperEmployee" in schema["$ref"]

    def test_get_response_schema_2x_fallback(self):
        response_info = {
            "schema": {"$ref": "#/definitions/ResponseWrapperEmployee"}
        }
        schema = _get_response_schema(response_info)
        assert schema is not None

    def test_get_response_schema_none(self):
        assert _get_response_schema({"description": "No content"}) is None

    def test_get_endpoint_schema_returns_body_fields_for_post(self):
        """get_endpoint_schema for a POST endpoint should return body fields from the real spec."""
        result = get_endpoint_schema("POST", "/v2/employee")
        assert result is not None, "get_endpoint_schema returned None for POST /v2/employee"
        assert "firstName" in result
        assert "lastName" in result

    def test_search_api_docs_shows_body_fields(self):
        """search_api_docs should include body field names from the real spec."""
        result = search_api_docs("employee")
        assert "Request body fields" in result
        assert "firstName" in result


class TestGenerateEndpointReference:
    """Tests for the generated endpoint reference text."""

    def test_contains_all_registry_endpoints(self):
        ref = generate_endpoint_reference()
        for method, path, _, _ in ENDPOINT_REGISTRY:
            assert f"{method} /v2{path}" in ref, (
                f"Missing {method} /v2{path} in generated reference"
            )

    def test_contains_notes(self):
        ref = generate_endpoint_reference()
        assert "QUERY PARAMS only" in ref
        assert "Bankinnskudd" in ref

    def test_marks_required_fields(self):
        ref = generate_endpoint_reference()
        assert "(REQ)" in ref

    def test_schema_hint_not_too_large(self):
        """Schema hints must be concise enough for the LLM to parse."""
        result = get_endpoint_schema("POST", "/v2/order")
        assert result is not None
        assert len(result) < 3000, f"Schema hint too large: {len(result)} chars"

    def test_fallback_without_spec(self):
        """If the spec fails to load, registry-only info is still shown."""
        with patch("src.api_docs._load_spec", side_effect=Exception("no network")):
            ref = generate_endpoint_reference()
            assert "POST /v2/employee" in ref
            assert "firstName" in ref
