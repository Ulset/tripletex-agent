"""Mock Tripletex client for agent tuning tests.

Provides a drop-in replacement for TripletexClient that:
- Auto-generates realistic responses (POST returns {value: {id: auto, ...body}})
- Stores created entities so subsequent GETs can find them
- Records every API call for assertion
- Supports custom response overrides per endpoint
"""

import re
from dataclasses import dataclass, field

from src.tripletex_client import TripletexAPIError


@dataclass
class RecordedCall:
    method: str
    endpoint: str
    body: dict | None
    params: dict | None
    response: dict | None
    error: TripletexAPIError | None


@dataclass
class AgentTestResult:
    calls: list[RecordedCall] = field(default_factory=list)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def error_count(self) -> int:
        return sum(1 for c in self.calls if c.error is not None)

    @property
    def errors(self) -> list[RecordedCall]:
        return [c for c in self.calls if c.error is not None]

    @property
    def successful_calls(self) -> list[RecordedCall]:
        return [c for c in self.calls if c.error is None]

    def find_calls(self, method: str, endpoint: str) -> list[RecordedCall]:
        """Find all calls matching method and endpoint (substring match)."""
        return [
            c for c in self.calls
            if c.method.upper() == method.upper() and endpoint in c.endpoint
        ]

    def assert_no_errors(self):
        if self.error_count > 0:
            lines = [f"  {c.method} {c.endpoint}: {c.error}" for c in self.errors]
            raise AssertionError(f"Expected 0 errors, got {self.error_count}:\n" + "\n".join(lines))

    def assert_max_calls(self, n: int):
        if self.call_count > n:
            lines = [f"  {c.method} {c.endpoint}" for c in self.calls]
            raise AssertionError(f"Expected <= {n} calls, got {self.call_count}:\n" + "\n".join(lines))

    def assert_endpoint_called(self, method: str, endpoint: str) -> RecordedCall:
        """Assert endpoint was called and return the first matching call."""
        matches = self.find_calls(method, endpoint)
        if matches:
            return matches[0]
        lines = [f"  {c.method} {c.endpoint}" for c in self.calls]
        raise AssertionError(f"{method} {endpoint} was not called. Actual calls:\n" + "\n".join(lines))

    def assert_body_contains(self, method: str, endpoint: str, expected: dict) -> RecordedCall:
        """Assert the first matching call's body contains all expected key-value pairs."""
        call = self.assert_endpoint_called(method, endpoint)
        if call.body is None:
            raise AssertionError(f"{method} {endpoint} had no body")
        for key, value in expected.items():
            if key not in call.body:
                raise AssertionError(
                    f"Body missing field '{key}'. Body keys: {list(call.body.keys())}"
                )
            if isinstance(value, dict):
                # For nested objects, check that the expected keys are present
                actual = call.body[key]
                if not isinstance(actual, dict):
                    raise AssertionError(
                        f"Body field '{key}' expected dict, got {type(actual).__name__}: {actual!r}"
                    )
                for k, v in value.items():
                    if k not in actual:
                        raise AssertionError(
                            f"Body['{key}'] missing nested field '{k}'. Keys: {list(actual.keys())}"
                        )
                    if actual[k] != v:
                        raise AssertionError(
                            f"Body['{key}']['{k}'] = {actual[k]!r}, expected {v!r}"
                        )
            elif call.body[key] != value:
                raise AssertionError(
                    f"Body field '{key}' = {call.body[key]!r}, expected {value!r}"
                )
        return call

    def print_summary(self):
        """Print a human-readable summary for debugging."""
        print(f"\n{'='*60}")
        print(f"Agent made {self.call_count} API calls ({self.error_count} errors)")
        print(f"{'='*60}")
        for i, c in enumerate(self.calls, 1):
            status = "ERROR" if c.error else "OK"
            print(f"  {i}. [{status}] {c.method} {c.endpoint}")
            if c.body:
                print(f"     body keys: {list(c.body.keys())}")
            if c.params:
                print(f"     params: {c.params}")
            if c.error:
                print(f"     error: {c.error}")
        print()


def _normalize_endpoint(endpoint: str) -> str:
    """Strip /v2 prefix and leading slash."""
    ep = endpoint.lstrip("/")
    if ep.startswith("v2/"):
        ep = ep[3:]
    return ep


def _endpoint_matches(pattern: str, endpoint: str) -> bool:
    """Check if a normalized endpoint matches a pattern (supports {id} wildcards)."""
    regex = re.escape(pattern).replace(r"\{id\}", r"\d+").replace(r"\{[^}]+\}", r"[^/]+")
    return bool(re.fullmatch(regex, endpoint))


class MockTripletexClient:
    """Drop-in replacement for TripletexClient that records calls and returns mock responses.

    Smart defaults:
    - POST: auto-generates {"value": {"id": <auto>, ...body}}
    - GET: returns {"values": [...]} from registered entities
    - PUT: returns {"value": {...body}}
    - DELETE: returns {}

    Override with register_response() for custom behavior.
    """

    def __init__(self):
        self._entities: dict[str, list[dict]] = {}
        self._next_id = 1000
        self._calls: list[RecordedCall] = []
        self._custom_responses: list[tuple[str, str, dict, int]] = []

    def register_entity(self, endpoint_base: str, entity: dict):
        """Pre-register an entity that GET requests will find.

        Args:
            endpoint_base: Endpoint path without /v2 prefix (e.g. "employee", "travelExpense/costCategory")
            entity: Entity dict that will be returned in GET responses
        """
        if endpoint_base not in self._entities:
            self._entities[endpoint_base] = []
        self._entities[endpoint_base].append(entity)

    def register_response(self, method: str, endpoint_pattern: str, response: dict, status: int = 200):
        """Register a custom response for a specific method + endpoint.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint_pattern: Endpoint without /v2 prefix, supports {id} wildcards
            response: Response dict to return
            status: HTTP status code (>= 400 raises TripletexAPIError)
        """
        self._custom_responses.append((method.upper(), endpoint_pattern, response, status))

    @property
    def calls(self) -> list[RecordedCall]:
        return list(self._calls)

    def get_result(self) -> AgentTestResult:
        return AgentTestResult(calls=list(self._calls))

    def _auto_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _find_custom_response(self, method: str, endpoint: str) -> tuple[dict, int] | None:
        ep = _normalize_endpoint(endpoint)
        for m, pattern, response, status in self._custom_responses:
            if m == method.upper() and _endpoint_matches(pattern, ep):
                return response, status
        return None

    def _find_entities(self, endpoint: str, params: dict | None) -> list[dict]:
        ep = _normalize_endpoint(endpoint)
        entities = self._entities.get(ep, [])
        if not params:
            return entities

        filtered = []
        for entity in entities:
            match = True
            for key, value in params.items():
                if key in ("fields", "count", "from", "sorting"):
                    continue
                entity_val = entity.get(key)
                if entity_val is not None and str(entity_val) != str(value):
                    match = False
                    break
            if match:
                filtered.append(entity)
        return filtered

    def _record(self, method, endpoint, body, params, response, error):
        self._calls.append(RecordedCall(method, endpoint, body, params, response, error))

    def _raise_error(self, method, endpoint, body, params, response, status):
        msg = response.get("message", "Error")
        validation = response.get("validationMessages", [])
        if validation:
            field_errors = "; ".join(
                f"{v.get('field', '?')}: {v.get('message', '?')}" for v in validation
            )
            msg = f"{msg} [{field_errors}]"
        error = TripletexAPIError(status, msg)
        self._record(method, endpoint, body, params, None, error)
        raise error

    def get(self, endpoint: str, params: dict | None = None, **kwargs) -> dict:
        # Merge extra kwargs into params (fields, count, from_)
        if any(v is not None for v in kwargs.values()):
            if params is None:
                params = {}
            for k in ("fields", "count"):
                if kwargs.get(k) is not None:
                    params[k] = kwargs[k]
            if kwargs.get("from_") is not None:
                params["from"] = kwargs["from_"]

        custom = self._find_custom_response("GET", endpoint)
        if custom:
            response, status = custom
            if status >= 400:
                self._raise_error("GET", endpoint, None, params, response, status)
            self._record("GET", endpoint, None, params, response, None)
            return response

        entities = self._find_entities(endpoint, params)
        response = {
            "fullResultSize": len(entities),
            "from": 0,
            "count": len(entities),
            "values": entities,
        }
        self._record("GET", endpoint, None, params, response, None)
        return response

    def post(self, endpoint: str, json: dict | None = None) -> dict:
        custom = self._find_custom_response("POST", endpoint)
        if custom:
            response, status = custom
            if status >= 400:
                self._raise_error("POST", endpoint, json, None, response, status)
            self._record("POST", endpoint, json, None, response, None)
            return response

        # Auto-create entity with auto-generated ID
        entity_id = self._auto_id()
        entity = {"id": entity_id}
        if json:
            entity.update(json)

        # Store for future GET lookups
        ep = _normalize_endpoint(endpoint)
        if ep not in self._entities:
            self._entities[ep] = []
        self._entities[ep].append(entity)

        response = {"value": entity}
        self._record("POST", endpoint, json, None, response, None)
        return response

    def put(self, endpoint: str, json: dict | None = None, params: dict | None = None) -> dict:
        custom = self._find_custom_response("PUT", endpoint)
        if custom:
            response, status = custom
            if status >= 400:
                self._raise_error("PUT", endpoint, json, params, response, status)
            self._record("PUT", endpoint, json, params, response, None)
            return response

        entity = {"id": 1}
        if json:
            entity.update(json)
        response = {"value": entity}
        self._record("PUT", endpoint, json, params, response, None)
        return response

    def delete(self, endpoint: str) -> dict:
        custom = self._find_custom_response("DELETE", endpoint)
        if custom:
            response, status = custom
            if status >= 400:
                self._raise_error("DELETE", endpoint, None, None, response, status)
            self._record("DELETE", endpoint, None, None, response, None)
            return response

        self._record("DELETE", endpoint, None, None, {}, None)
        return {}
