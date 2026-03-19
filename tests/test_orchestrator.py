import json
from unittest.mock import MagicMock, patch

import responses

from src.config import Settings
from src.models import SolveRequest, FileAttachment, TripletexCredentials


TRIPLETEX_BASE = "https://api.tripletex.io/v2"


def _make_settings():
    return Settings(
        openai_api_key="test-key",
        openai_model="gpt-4o",
        port=8000,
        api_key="",
    )


def _make_request(prompt="Create an employee named Ola Nordmann", files=None):
    return SolveRequest(
        prompt=prompt,
        files=files or [],
        tripletex_credentials=TripletexCredentials(
            base_url=TRIPLETEX_BASE,
            session_token="test-session",
        ),
    )


def _mock_openai_plan(steps):
    """Create a mock OpenAI client that returns a plan with given steps."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({"steps": steps})
    mock_client.return_value.chat.completions.create.return_value = mock_response
    return mock_client


class TestTaskOrchestrator:
    @responses.activate
    @patch("src.plan_generator.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_full_flow_create_employee(self, mock_file_openai, mock_plan_openai):
        """Full flow: prompt -> plan -> execute -> completed."""
        from src.orchestrator import TaskOrchestrator

        # Mock OpenAI to return a single-step plan
        plan_steps = [
            {
                "step_number": 1,
                "action": "POST",
                "endpoint": "/v2/employee",
                "payload": {"firstName": "Ola", "lastName": "Nordmann"},
                "params": None,
                "description": "Create employee Ola Nordmann",
            }
        ]
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({"steps": plan_steps})
        mock_plan_openai.return_value.chat.completions.create.return_value = mock_response

        # Mock Tripletex API
        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/employee",
            json={"value": {"id": 1, "firstName": "Ola", "lastName": "Nordmann"}},
            status=201,
        )

        orchestrator = TaskOrchestrator(_make_settings())
        result = orchestrator.solve(_make_request())

        assert result.status == "completed"
        assert len(responses.calls) == 1
        assert responses.calls[0].request.url == f"{TRIPLETEX_BASE}/employee"

    @responses.activate
    @patch("src.plan_generator.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_full_flow_multi_step_with_placeholders(self, mock_file_openai, mock_plan_openai):
        """Multi-step flow: create customer -> create order -> create invoice."""
        from src.orchestrator import TaskOrchestrator

        plan_steps = [
            {
                "step_number": 1,
                "action": "POST",
                "endpoint": "/v2/customer",
                "payload": {"name": "Acme AS"},
                "params": None,
                "description": "Create customer",
            },
            {
                "step_number": 2,
                "action": "POST",
                "endpoint": "/v2/order",
                "payload": {"customer": {"id": "$step1.value.id"}, "orderDate": "2026-01-01"},
                "params": None,
                "description": "Create order for customer",
            },
            {
                "step_number": 3,
                "action": "POST",
                "endpoint": "/v2/invoice",
                "payload": {"orderId": "$step2.value.id"},
                "params": None,
                "description": "Create invoice from order",
            },
        ]
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({"steps": plan_steps})
        mock_plan_openai.return_value.chat.completions.create.return_value = mock_response

        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/customer",
            json={"value": {"id": 100, "name": "Acme AS"}},
            status=201,
        )
        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/order",
            json={"value": {"id": 200, "customer": {"id": 100}, "orderDate": "2026-01-01"}},
            status=201,
        )
        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/invoice",
            json={"value": {"id": 300, "orderId": 200}},
            status=201,
        )

        orchestrator = TaskOrchestrator(_make_settings())
        result = orchestrator.solve(_make_request("Create invoice for Acme AS"))

        assert result.status == "completed"
        assert len(responses.calls) == 3

        # Verify placeholder resolution: order payload should have customer.id = 100
        order_body = json.loads(responses.calls[1].request.body)
        assert order_body["customer"]["id"] == 100

        # Verify invoice payload should have orderId = 200
        invoice_body = json.loads(responses.calls[2].request.body)
        assert invoice_body["orderId"] == 200

    @patch("src.plan_generator.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_returns_completed_on_exception(self, mock_file_openai, mock_plan_openai):
        """Orchestrator must always return status=completed even if everything fails."""
        from src.orchestrator import TaskOrchestrator

        mock_plan_openai.return_value.chat.completions.create.side_effect = Exception("LLM down")

        orchestrator = TaskOrchestrator(_make_settings())
        result = orchestrator.solve(_make_request())

        assert result.status == "completed"

    @responses.activate
    @patch("src.plan_generator.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_replan_on_api_failure(self, mock_file_openai, mock_plan_openai):
        """On API error, orchestrator re-plans and retries."""
        from src.orchestrator import TaskOrchestrator

        # First plan: one step that will fail
        first_plan = [
            {
                "step_number": 1,
                "action": "POST",
                "endpoint": "/v2/employee",
                "payload": {"firstName": "Ola"},
                "params": None,
                "description": "Create employee (missing lastName)",
            }
        ]
        # Re-plan: corrected step
        second_plan = [
            {
                "step_number": 1,
                "action": "POST",
                "endpoint": "/v2/employee",
                "payload": {"firstName": "Ola", "lastName": "Nordmann"},
                "params": None,
                "description": "Create employee with lastName",
            }
        ]

        mock_openai_instance = mock_plan_openai.return_value
        first_response = MagicMock()
        first_response.choices = [MagicMock()]
        first_response.choices[0].message.content = json.dumps({"steps": first_plan})

        second_response = MagicMock()
        second_response.choices = [MagicMock()]
        second_response.choices[0].message.content = json.dumps({"steps": second_plan})

        mock_openai_instance.chat.completions.create.side_effect = [
            first_response,   # generate_plan
            second_response,  # replan
        ]

        # First call fails with 422, second succeeds
        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/employee",
            json={"message": "lastName is required"},
            status=422,
        )
        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/employee",
            json={"value": {"id": 1, "firstName": "Ola", "lastName": "Nordmann"}},
            status=201,
        )

        orchestrator = TaskOrchestrator(_make_settings())
        result = orchestrator.solve(_make_request())

        assert result.status == "completed"
        # 2 Tripletex API calls: first failed, second succeeded
        assert len(responses.calls) == 2

    @responses.activate
    @patch("src.plan_generator.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_efficiency_summary_logged(self, mock_file_openai, mock_plan_openai):
        """Orchestrator logs efficiency summary with total_api_calls, error_count, replan_count."""
        from src.orchestrator import TaskOrchestrator

        plan_steps = [
            {
                "step_number": 1,
                "action": "POST",
                "endpoint": "/v2/employee",
                "payload": {"firstName": "Ola", "lastName": "Nordmann"},
                "params": None,
                "description": "Create employee",
            }
        ]
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({"steps": plan_steps})
        mock_plan_openai.return_value.chat.completions.create.return_value = mock_response

        responses.add(
            responses.POST,
            f"{TRIPLETEX_BASE}/employee",
            json={"value": {"id": 1, "firstName": "Ola", "lastName": "Nordmann"}},
            status=201,
        )

        orchestrator = TaskOrchestrator(_make_settings())
        with patch("src.orchestrator.logger") as mock_logger:
            result = orchestrator.solve(_make_request())

        assert result.status == "completed"
        # Find the efficiency summary log call
        efficiency_calls = [
            call for call in mock_logger.info.call_args_list
            if "Efficiency summary" in str(call)
        ]
        assert len(efficiency_calls) == 1
        call_args = efficiency_calls[0]
        assert "total_api_calls=" in call_args[0][0]
        assert "error_count=" in call_args[0][0]
        assert "replan_count=" in call_args[0][0]

    @responses.activate
    @patch("src.plan_generator.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_orchestrator_creates_client_from_credentials(self, mock_file_openai, mock_plan_openai):
        """Verify TripletexClient is created from request credentials."""
        from src.orchestrator import TaskOrchestrator

        plan_steps = [
            {
                "step_number": 1,
                "action": "GET",
                "endpoint": "/v2/employee",
                "payload": None,
                "params": None,
                "description": "List employees",
            }
        ]
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({"steps": plan_steps})
        mock_plan_openai.return_value.chat.completions.create.return_value = mock_response

        responses.add(
            responses.GET,
            f"{TRIPLETEX_BASE}/employee",
            json={"fullResultSize": 0, "values": []},
            status=200,
        )

        request = _make_request()
        orchestrator = TaskOrchestrator(_make_settings())
        orchestrator.solve(request)

        # Verify Basic Auth was used with session_token
        import base64
        auth_header = responses.calls[0].request.headers["Authorization"]
        decoded = base64.b64decode(auth_header.split(" ")[1]).decode()
        assert decoded == "0:test-session"
