import json
from unittest.mock import MagicMock, patch

import pytest

from src.models import ExecutionPlan, ExecutionResult, PlanStep
from src.plan_generator import PlanGenerator


def _make_openai_response(plan_dict: dict) -> MagicMock:
    choice = MagicMock()
    choice.message.content = json.dumps(plan_dict)
    response = MagicMock()
    response.choices = [choice]
    return response


@patch("src.plan_generator.OpenAI")
class TestPlanGenerator:
    def test_generate_valid_plan(self, mock_openai_cls):
        plan_data = {
            "steps": [
                {
                    "step_number": 1,
                    "action": "POST",
                    "endpoint": "/v2/employee",
                    "payload": {"firstName": "Ola", "lastName": "Nordmann"},
                    "params": None,
                    "description": "Create employee Ola Nordmann",
                }
            ]
        }
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(
            plan_data
        )

        generator = PlanGenerator(openai_api_key="test-key", model="gpt-4o")
        plan = generator.generate_plan("Opprett ansatt Ola Nordmann")

        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "POST"
        assert plan.steps[0].endpoint == "/v2/employee"
        assert plan.steps[0].payload["firstName"] == "Ola"

    def test_generate_plan_with_placeholders(self, mock_openai_cls):
        plan_data = {
            "steps": [
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
                    "endpoint": "/v2/product",
                    "payload": {"name": "Widget"},
                    "params": None,
                    "description": "Create product",
                },
                {
                    "step_number": 3,
                    "action": "POST",
                    "endpoint": "/v2/order",
                    "payload": {
                        "customer": {"id": "$step1.value.id"},
                        "deliveryDate": "2024-01-15",
                        "orderLines": [
                            {"product": {"id": "$step2.value.id"}, "count": 1}
                        ],
                    },
                    "params": None,
                    "description": "Create order linking customer and product",
                },
            ]
        }
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(
            plan_data
        )

        generator = PlanGenerator(openai_api_key="test-key")
        plan = generator.generate_plan("Create an order for Acme AS")

        assert len(plan.steps) == 3
        assert plan.steps[2].payload["customer"]["id"] == "$step1.value.id"
        assert (
            plan.steps[2].payload["orderLines"][0]["product"]["id"]
            == "$step2.value.id"
        )

    def test_generate_plan_with_file_contents(self, mock_openai_cls):
        plan_data = {
            "steps": [
                {
                    "step_number": 1,
                    "action": "POST",
                    "endpoint": "/v2/employee",
                    "payload": {"firstName": "Kari", "lastName": "Hansen"},
                    "params": None,
                    "description": "Create employee from file data",
                }
            ]
        }
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(
            plan_data
        )

        generator = PlanGenerator(openai_api_key="test-key")
        file_contents = [
            {"filename": "employees.pdf", "extracted_text": "Kari Hansen, kari@test.no"}
        ]
        plan = generator.generate_plan("Opprett ansatte fra filen", file_contents)

        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "employees.pdf" in user_msg
        assert "Kari Hansen" in user_msg

    def test_generate_plan_with_error_context(self, mock_openai_cls):
        plan_data = {
            "steps": [
                {
                    "step_number": 1,
                    "action": "POST",
                    "endpoint": "/v2/company/modules",
                    "payload": {"departmentAccounting": True},
                    "params": None,
                    "description": "Enable department accounting module",
                },
                {
                    "step_number": 2,
                    "action": "POST",
                    "endpoint": "/v2/department",
                    "payload": {"name": "Salg", "departmentNumber": 1},
                    "params": None,
                    "description": "Create department",
                },
            ]
        }
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(
            plan_data
        )

        generator = PlanGenerator(openai_api_key="test-key")
        plan = generator.generate_plan(
            "Opprett avdeling Salg",
            error_context="403: Department accounting module not enabled",
        )

        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "403" in user_msg
        assert len(plan.steps) == 2

    def test_system_prompt_includes_api_reference(self, mock_openai_cls):
        plan_data = {"steps": []}
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(
            plan_data
        )

        generator = PlanGenerator(openai_api_key="test-key")
        generator.generate_plan("test")

        call_args = mock_client.chat.completions.create.call_args
        system_msg = call_args[1]["messages"][0]["content"]
        assert "Tripletex API Reference" in system_msg
        assert "$stepN.path.to.value" in system_msg

    def test_system_prompt_mentions_languages(self, mock_openai_cls):
        plan_data = {"steps": []}
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(
            plan_data
        )

        generator = PlanGenerator(openai_api_key="test-key")
        generator.generate_plan("test")

        call_args = mock_client.chat.completions.create.call_args
        system_msg = call_args[1]["messages"][0]["content"]
        for lang in ["Norwegian Bokmal", "Norwegian Nynorsk", "English", "Spanish", "Portuguese", "German", "French"]:
            assert lang in system_msg

    def test_uses_json_response_format(self, mock_openai_cls):
        plan_data = {"steps": []}
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(
            plan_data
        )

        generator = PlanGenerator(openai_api_key="test-key")
        generator.generate_plan("test")

        call_args = mock_client.chat.completions.create.call_args
        assert call_args[1]["response_format"] == {"type": "json_object"}


@patch("src.plan_generator.OpenAI")
class TestReplan:
    def test_replan_generates_corrected_plan(self, mock_openai_cls):
        corrected_plan = {
            "steps": [
                {
                    "step_number": 1,
                    "action": "POST",
                    "endpoint": "/v2/company/modules",
                    "payload": {"departmentAccounting": True},
                    "params": None,
                    "description": "Enable department module",
                },
                {
                    "step_number": 2,
                    "action": "POST",
                    "endpoint": "/v2/department",
                    "payload": {"name": "Salg", "departmentNumber": 1},
                    "params": None,
                    "description": "Create department",
                },
            ]
        }
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(
            corrected_plan
        )

        generator = PlanGenerator(openai_api_key="test-key")
        execution_result = ExecutionResult(
            steps_completed=1,
            results=[{"value": {"id": 10}}],
            errors=["Step 2 failed: 403: Department accounting not enabled"],
            success=False,
        )

        plan = generator.replan(
            original_prompt="Opprett avdeling Salg",
            file_contents=None,
            execution_result=execution_result,
            error_context="403: Department accounting not enabled",
        )

        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 2

        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "Opprett avdeling Salg" in user_msg
        assert "1 steps succeeded" in user_msg
        assert "403" in user_msg
        assert "REMAINING work only" in user_msg

    def test_replan_includes_file_contents(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(
            {"steps": []}
        )

        generator = PlanGenerator(openai_api_key="test-key")
        execution_result = ExecutionResult(
            steps_completed=0,
            results=[],
            errors=["Step 1 failed: 422 validation error"],
            success=False,
        )

        generator.replan(
            original_prompt="Create employee from file",
            file_contents=[{"filename": "data.pdf", "extracted_text": "John Doe"}],
            execution_result=execution_result,
            error_context="422 validation error",
        )

        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "data.pdf" in user_msg
        assert "John Doe" in user_msg
