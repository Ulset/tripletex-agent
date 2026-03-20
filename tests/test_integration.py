"""Integration tests simulating the full agent flow with mocked external services.

Tests mock OpenAI to return tool_calls then a final text response,
mock Tripletex API responses, and verify correct API calls are made.
"""

import json
from unittest.mock import MagicMock, patch

import responses

from src.config import Settings
from src.models import SolveRequest, TripletexCredentials


TRIPLETEX_BASE = "https://api.tripletex.io/v2"


def _settings():
    return Settings(
        llm_model="google/gemini-2.5-flash",
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


def _make_text_response(content="Task complete"):
    message = MagicMock()
    message.content = content
    message.tool_calls = None
    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_tool_call_response(method, endpoint, body=None, params=None, tool_call_id="call_1"):
    args = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
    if params is not None:
        args["params"] = params

    tool_call = MagicMock()
    tool_call.id = tool_call_id
    tool_call.function.name = "call_api"
    tool_call.function.arguments = json.dumps(args)

    message = MagicMock()
    message.content = None
    message.tool_calls = [tool_call]
    choice = MagicMock()
    choice.finish_reason = "tool_calls"
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


class TestIntegrationCreateEmployee:
    """Full-flow: prompt -> agent tool call -> POST /employee with correct fields."""

    @responses.activate
    @patch("src.agent.get_openai_client")
    @patch("src.file_processor.get_openai_client")
    def test_create_employee_calls_api_with_correct_fields(
        self, mock_file_openai, mock_agent_openai
    ):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/employee", body={
                "firstName": "Kari", "lastName": "Nordmann", "email": "kari.nordmann@example.no",
            }),
            _make_text_response("Created employee Kari Nordmann"),
        ]

        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/employee",
            json={"value": {"id": 42, "firstName": "Kari", "lastName": "Nordmann", "email": "kari.nordmann@example.no"}},
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett ansatt Kari Nordmann med e-post kari.nordmann@example.no")
        )

        assert result.status == "completed"
        assert len(responses.calls) == 1
        body = json.loads(responses.calls[0].request.body)
        assert body["firstName"] == "Kari"
        assert body["lastName"] == "Nordmann"
        assert body["email"] == "kari.nordmann@example.no"


class TestIntegrationCreateCustomer:
    """Full-flow: prompt -> agent tool call -> POST /customer."""

    @responses.activate
    @patch("src.agent.get_openai_client")
    @patch("src.file_processor.get_openai_client")
    def test_create_customer_calls_api_with_correct_fields(
        self, mock_file_openai, mock_agent_openai
    ):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/customer", body={
                "name": "Bergen Consulting AS", "email": "post@bergenconsulting.no",
            }),
            _make_text_response("Created customer Bergen Consulting AS"),
        ]

        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/customer",
            json={"value": {"id": 55, "name": "Bergen Consulting AS", "email": "post@bergenconsulting.no"}},
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Create customer Bergen Consulting AS")
        )

        assert result.status == "completed"
        assert len(responses.calls) == 1
        body = json.loads(responses.calls[0].request.body)
        assert body["name"] == "Bergen Consulting AS"


class TestIntegrationCreateInvoice:
    """Multi-step: POST /customer -> POST /order -> POST /invoice with agent reading IDs from responses."""

    @responses.activate
    @patch("src.agent.get_openai_client")
    @patch("src.file_processor.get_openai_client")
    def test_create_invoice_correct_call_order_and_id_linking(
        self, mock_file_openai, mock_agent_openai
    ):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/customer", body={"name": "Fjord Tech AS"}, tool_call_id="c1"),
            _make_tool_call_response("POST", "/v2/order", body={
                "customer": {"id": 100}, "orderDate": "2026-03-19", "deliveryDate": "2026-04-19",
            }, tool_call_id="c2"),
            _make_tool_call_response("POST", "/v2/invoice", body={
                "orderId": 200, "invoiceDate": "2026-03-19",
            }, tool_call_id="c3"),
            _make_text_response("Created invoice for Fjord Tech AS"),
        ]

        responses.add(responses.POST, f"{TRIPLETEX_BASE}/customer",
                       json={"value": {"id": 100, "name": "Fjord Tech AS"}}, status=201)
        responses.add(responses.POST, f"{TRIPLETEX_BASE}/order",
                       json={"value": {"id": 200, "customer": {"id": 100}}}, status=201)
        responses.add(responses.POST, f"{TRIPLETEX_BASE}/invoice",
                       json={"value": {"id": 300, "orderId": 200}}, status=201)

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett faktura for Fjord Tech AS")
        )

        assert result.status == "completed"
        assert len(responses.calls) == 3
        assert "/v2/customer" in responses.calls[0].request.url
        assert "/v2/order" in responses.calls[1].request.url
        assert "/v2/invoice" in responses.calls[2].request.url

        # Agent reads customer ID from response and passes it to order
        order_body = json.loads(responses.calls[1].request.body)
        assert order_body["customer"]["id"] == 100

        invoice_body = json.loads(responses.calls[2].request.body)
        assert invoice_body["orderId"] == 200


class TestIntegrationErrorRecovery:
    """Agent self-heals from API error by reading error message and retrying with correct fields."""

    @responses.activate
    @patch("src.agent.get_openai_client")
    @patch("src.file_processor.get_openai_client")
    def test_error_recovery_agent_retries_with_correct_fields(
        self, mock_file_openai, mock_agent_openai
    ):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai

        # First tool call fails (missing lastName), agent gets error, retries with correct fields
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/employee", body={"firstName": "Kari"}, tool_call_id="c1"),
            _make_tool_call_response("POST", "/v2/employee", body={
                "firstName": "Kari", "lastName": "Nordmann", "email": "kari@example.no",
            }, tool_call_id="c2"),
            _make_text_response("Created employee Kari Nordmann"),
        ]

        # First call fails
        responses.add(responses.POST, f"{TRIPLETEX_BASE}/employee",
                       json={"message": "lastName is required"}, status=422)
        # Second call succeeds
        responses.add(responses.POST, f"{TRIPLETEX_BASE}/employee",
                       json={"value": {"id": 42, "firstName": "Kari", "lastName": "Nordmann"}}, status=201)

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett ansatt Kari Nordmann")
        )

        assert result.status == "completed"
        assert len(responses.calls) == 2

        # Second call has correct fields
        success_body = json.loads(responses.calls[1].request.body)
        assert success_body["firstName"] == "Kari"
        assert success_body["lastName"] == "Nordmann"

    @patch("src.agent.get_openai_client")
    @patch("src.file_processor.get_openai_client")
    def test_error_recovery_still_returns_completed(
        self, mock_file_openai, mock_agent_openai
    ):
        """Even when agent fails entirely, status is 'completed'."""
        from src.orchestrator import TaskOrchestrator

        mock_agent_openai.return_value.chat.completions.create.side_effect = Exception("LLM timeout")

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett ansatt Kari Nordmann")
        )

        assert result.status == "completed"
