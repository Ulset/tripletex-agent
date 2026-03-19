"""Integration tests simulating the full agent flow with mocked external services.

US-014: Tests cover create employee, create customer, create invoice (multi-step),
and error recovery with re-planning.
"""

import json
from unittest.mock import MagicMock, patch

import responses

from src.config import Settings
from src.models import SolveRequest, TripletexCredentials


TRIPLETEX_BASE = "https://api.tripletex.io/v2"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _settings():
    return Settings(
        openai_api_key="test-key",
        openai_model="gpt-4o",
        port=8000,
        api_key="",
    )


def _solve_request(prompt: str):
    return SolveRequest(
        prompt=prompt,
        files=[],
        tripletex_credentials=TripletexCredentials(
            base_url=TRIPLETEX_BASE,
            session_token="test-session",
        ),
    )


def _openai_response(steps):
    """Build a MagicMock that looks like an OpenAI ChatCompletion response."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = json.dumps({"steps": steps})
    return resp


# ---------------------------------------------------------------------------
# Realistic mock plan fixtures
# ---------------------------------------------------------------------------

CREATE_EMPLOYEE_PLAN = [
    {
        "step_number": 1,
        "action": "POST",
        "endpoint": "/v2/employee",
        "payload": {
            "firstName": "Kari",
            "lastName": "Nordmann",
            "email": "kari.nordmann@example.no",
        },
        "params": None,
        "description": "Create employee Kari Nordmann with email",
    }
]

CREATE_CUSTOMER_PLAN = [
    {
        "step_number": 1,
        "action": "POST",
        "endpoint": "/v2/customer",
        "payload": {
            "name": "Bergen Consulting AS",
            "email": "post@bergenconsulting.no",
        },
        "params": None,
        "description": "Create customer Bergen Consulting AS",
    }
]

CREATE_INVOICE_PLAN = [
    {
        "step_number": 1,
        "action": "POST",
        "endpoint": "/v2/customer",
        "payload": {"name": "Fjord Tech AS"},
        "params": None,
        "description": "Create customer Fjord Tech AS",
    },
    {
        "step_number": 2,
        "action": "POST",
        "endpoint": "/v2/order",
        "payload": {
            "customer": {"id": "$step1.value.id"},
            "orderDate": "2026-03-19",
            "deliveryDate": "2026-04-19",
        },
        "params": None,
        "description": "Create order linked to customer",
    },
    {
        "step_number": 3,
        "action": "POST",
        "endpoint": "/v2/invoice",
        "payload": {"orderId": "$step2.value.id", "invoiceDate": "2026-03-19"},
        "params": None,
        "description": "Create invoice from order",
    },
]

# Plan used in the error-recovery scenario — missing required email field
CREATE_EMPLOYEE_BAD_PLAN = [
    {
        "step_number": 1,
        "action": "POST",
        "endpoint": "/v2/employee",
        "payload": {"firstName": "Kari"},
        "params": None,
        "description": "Create employee (missing lastName)",
    }
]

# Corrected plan returned after re-plan
CREATE_EMPLOYEE_FIXED_PLAN = [
    {
        "step_number": 1,
        "action": "POST",
        "endpoint": "/v2/employee",
        "payload": {
            "firstName": "Kari",
            "lastName": "Nordmann",
            "email": "kari.nordmann@example.no",
        },
        "params": None,
        "description": "Create employee with all required fields",
    }
]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestIntegrationCreateEmployee:
    """Full-flow: prompt -> plan -> POST /employee with correct fields."""

    @responses.activate
    @patch("src.plan_generator.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_create_employee_calls_api_with_correct_fields(
        self, mock_file_openai, mock_plan_openai
    ):
        from src.orchestrator import TaskOrchestrator

        mock_plan_openai.return_value.chat.completions.create.return_value = (
            _openai_response(CREATE_EMPLOYEE_PLAN)
        )

        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/employee",
            json={
                "value": {
                    "id": 42,
                    "firstName": "Kari",
                    "lastName": "Nordmann",
                    "email": "kari.nordmann@example.no",
                }
            },
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett ansatt Kari Nordmann med e-post kari.nordmann@example.no")
        )

        assert result.status == "completed"

        # Exactly one API call made
        assert len(responses.calls) == 1
        assert responses.calls[0].request.url == f"{TRIPLETEX_BASE}/employee"

        body = json.loads(responses.calls[0].request.body)
        assert body["firstName"] == "Kari"
        assert body["lastName"] == "Nordmann"
        assert body["email"] == "kari.nordmann@example.no"


class TestIntegrationCreateCustomer:
    """Full-flow: prompt -> plan -> POST /customer."""

    @responses.activate
    @patch("src.plan_generator.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_create_customer_calls_api_with_correct_fields(
        self, mock_file_openai, mock_plan_openai
    ):
        from src.orchestrator import TaskOrchestrator

        mock_plan_openai.return_value.chat.completions.create.return_value = (
            _openai_response(CREATE_CUSTOMER_PLAN)
        )

        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/customer",
            json={
                "value": {
                    "id": 55,
                    "name": "Bergen Consulting AS",
                    "email": "post@bergenconsulting.no",
                }
            },
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Create customer Bergen Consulting AS")
        )

        assert result.status == "completed"
        assert len(responses.calls) == 1

        body = json.loads(responses.calls[0].request.body)
        assert body["name"] == "Bergen Consulting AS"
        assert body["email"] == "post@bergenconsulting.no"


class TestIntegrationCreateInvoice:
    """Multi-step flow: POST /customer -> POST /order -> POST /invoice with ID linking."""

    @responses.activate
    @patch("src.plan_generator.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_create_invoice_correct_call_order_and_id_linking(
        self, mock_file_openai, mock_plan_openai
    ):
        from src.orchestrator import TaskOrchestrator

        mock_plan_openai.return_value.chat.completions.create.return_value = (
            _openai_response(CREATE_INVOICE_PLAN)
        )

        # Step 1 — customer
        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/customer",
            json={"value": {"id": 100, "name": "Fjord Tech AS"}},
            status=201,
        )
        # Step 2 — order
        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/order",
            json={
                "value": {
                    "id": 200,
                    "customer": {"id": 100},
                    "orderDate": "2026-03-19",
                }
            },
            status=201,
        )
        # Step 3 — invoice
        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/invoice",
            json={"value": {"id": 300, "orderId": 200, "invoiceDate": "2026-03-19"}},
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett faktura for Fjord Tech AS")
        )

        assert result.status == "completed"

        # Verify call order: customer, order, invoice
        assert len(responses.calls) == 3
        assert "/v2/customer" in responses.calls[0].request.url
        assert "/v2/order" in responses.calls[1].request.url
        assert "/v2/invoice" in responses.calls[2].request.url

        # Verify placeholder resolution: order.customer.id == 100 (from customer response)
        order_body = json.loads(responses.calls[1].request.body)
        assert order_body["customer"]["id"] == 100

        # Verify placeholder resolution: invoice.orderId == 200 (from order response)
        invoice_body = json.loads(responses.calls[2].request.body)
        assert invoice_body["orderId"] == 200


class TestIntegrationErrorRecovery:
    """Error recovery: first attempt fails with 422, replan produces corrected plan that succeeds."""

    @responses.activate
    @patch("src.plan_generator.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_error_recovery_replans_and_succeeds(
        self, mock_file_openai, mock_plan_openai
    ):
        from src.orchestrator import TaskOrchestrator

        # First call -> bad plan, second call -> fixed plan
        mock_openai_instance = mock_plan_openai.return_value
        mock_openai_instance.chat.completions.create.side_effect = [
            _openai_response(CREATE_EMPLOYEE_BAD_PLAN),  # generate_plan
            _openai_response(CREATE_EMPLOYEE_FIXED_PLAN),  # replan
        ]

        # First Tripletex call fails with 422
        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/employee",
            json={"message": "lastName is required"},
            status=422,
        )
        # Second Tripletex call succeeds
        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/employee",
            json={
                "value": {
                    "id": 42,
                    "firstName": "Kari",
                    "lastName": "Nordmann",
                    "email": "kari.nordmann@example.no",
                }
            },
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett ansatt Kari Nordmann")
        )

        assert result.status == "completed"

        # Two Tripletex calls: first failed, second succeeded
        assert len(responses.calls) == 2

        # Verify replan was called (second OpenAI call)
        assert mock_openai_instance.chat.completions.create.call_count == 2

        # Verify the second (successful) call had all required fields
        success_body = json.loads(responses.calls[1].request.body)
        assert success_body["firstName"] == "Kari"
        assert success_body["lastName"] == "Nordmann"
        assert success_body["email"] == "kari.nordmann@example.no"

    @responses.activate
    @patch("src.plan_generator.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_error_recovery_still_returns_completed_after_exhausted_retries(
        self, mock_file_openai, mock_plan_openai
    ):
        """Even when all replan attempts fail, status is 'completed'."""
        from src.orchestrator import TaskOrchestrator

        bad_plan = _openai_response(CREATE_EMPLOYEE_BAD_PLAN)
        # generate_plan + 2 replans = 3 calls, all return the same bad plan
        mock_plan_openai.return_value.chat.completions.create.side_effect = [
            bad_plan,
            bad_plan,
            bad_plan,
        ]

        # All three Tripletex calls fail
        for _ in range(3):
            responses.add(
                responses.POST,
                f"{TRIPLETEX_BASE}/employee",
                json={"message": "lastName is required"},
                status=422,
            )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett ansatt Kari Nordmann")
        )

        # Must still return completed per competition rules
        assert result.status == "completed"
        # 3 Tripletex calls: initial + 2 replan attempts
        assert len(responses.calls) == 3
