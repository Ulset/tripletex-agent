from unittest.mock import MagicMock

import pytest

from src.models import ExecutionPlan, ExecutionResult, PlanStep
from src.plan_executor import PlanExecutor, _resolve_placeholders, _traverse
from src.tripletex_client import TripletexAPIError


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def executor(mock_client):
    return PlanExecutor(mock_client)


class TestSequentialExecution:
    def test_executes_get(self, executor, mock_client):
        mock_client.get.return_value = {"values": [{"id": 1}]}
        plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="GET", endpoint="/v2/employee", params={"name": "Ola"}, description="Get employee"),
        ])
        result = executor.execute(plan)
        assert result.success is True
        assert result.steps_completed == 1
        mock_client.get.assert_called_once_with("/v2/employee", params={"name": "Ola"})

    def test_executes_post(self, executor, mock_client):
        mock_client.post.return_value = {"value": {"id": 42}}
        plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="POST", endpoint="/v2/employee", payload={"firstName": "Ola"}, description="Create employee"),
        ])
        result = executor.execute(plan)
        assert result.success is True
        assert result.results == [{"value": {"id": 42}}]
        mock_client.post.assert_called_once_with("/v2/employee", json={"firstName": "Ola"})

    def test_executes_put(self, executor, mock_client):
        mock_client.put.return_value = {"value": {"id": 1}}
        plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="PUT", endpoint="/v2/employee/1", payload={"firstName": "Kari"}, description="Update employee"),
        ])
        result = executor.execute(plan)
        assert result.success is True
        mock_client.put.assert_called_once_with("/v2/employee/1", json={"firstName": "Kari"})

    def test_executes_delete(self, executor, mock_client):
        mock_client.delete.return_value = {}
        plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="DELETE", endpoint="/v2/employee/1", description="Delete employee"),
        ])
        result = executor.execute(plan)
        assert result.success is True
        mock_client.delete.assert_called_once_with("/v2/employee/1")

    def test_multi_step_sequential(self, executor, mock_client):
        mock_client.post.side_effect = [
            {"value": {"id": 10}},
            {"value": {"id": 20}},
        ]
        plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="POST", endpoint="/v2/customer", payload={"name": "Acme"}, description="Create customer"),
            PlanStep(step_number=2, action="POST", endpoint="/v2/order", payload={"customerId": 10}, description="Create order"),
        ])
        result = executor.execute(plan)
        assert result.success is True
        assert result.steps_completed == 2
        assert len(result.results) == 2


class TestPlaceholderResolution:
    def test_resolves_step_reference(self, executor, mock_client):
        mock_client.post.side_effect = [
            {"value": {"id": 42}},
            {"value": {"id": 100}},
        ]
        plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="POST", endpoint="/v2/customer", payload={"name": "Acme"}, description="Create customer"),
            PlanStep(step_number=2, action="POST", endpoint="/v2/order", payload={"customerId": "$step1.value.id"}, description="Create order"),
        ])
        result = executor.execute(plan)
        assert result.success is True
        # Verify the second call used the resolved ID
        mock_client.post.assert_any_call("/v2/order", json={"customerId": 42})

    def test_resolves_nested_placeholders(self, executor, mock_client):
        mock_client.post.side_effect = [
            {"value": {"id": 1, "details": {"code": "ABC"}}},
            {"value": {"id": 2}},
        ]
        plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="POST", endpoint="/v2/product", payload={"name": "Widget"}, description="Create product"),
            PlanStep(step_number=2, action="POST", endpoint="/v2/order", payload={"productCode": "$step1.value.details.code"}, description="Create order"),
        ])
        result = executor.execute(plan)
        assert result.success is True
        mock_client.post.assert_any_call("/v2/order", json={"productCode": "ABC"})

    def test_resolves_params_placeholders(self, executor, mock_client):
        mock_client.post.return_value = {"value": {"id": 5}}
        mock_client.get.return_value = {"values": []}
        plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="POST", endpoint="/v2/customer", payload={"name": "Test"}, description="Create customer"),
            PlanStep(step_number=2, action="GET", endpoint="/v2/order", params={"customerId": "$step1.value.id"}, description="Get orders"),
        ])
        result = executor.execute(plan)
        assert result.success is True
        mock_client.get.assert_called_once_with("/v2/order", params={"customerId": 5})


class TestFailureHandling:
    def test_failure_stops_execution(self, executor, mock_client):
        mock_client.post.side_effect = TripletexAPIError(422, "Missing required field")
        plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="POST", endpoint="/v2/employee", payload={"firstName": "Ola"}, description="Create employee"),
            PlanStep(step_number=2, action="POST", endpoint="/v2/order", payload={"customerId": 1}, description="Create order"),
        ])
        result = executor.execute(plan)
        assert result.success is False
        assert result.steps_completed == 0
        assert len(result.errors) == 1
        assert "Missing required field" in result.errors[0]
        # Step 2 should not have been called
        assert mock_client.post.call_count == 1

    def test_partial_failure(self, executor, mock_client):
        mock_client.post.side_effect = [
            {"value": {"id": 1}},
            TripletexAPIError(500, "Internal server error"),
        ]
        plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="POST", endpoint="/v2/customer", payload={"name": "Acme"}, description="Create customer"),
            PlanStep(step_number=2, action="POST", endpoint="/v2/order", payload={"customerId": "$step1.value.id"}, description="Create order"),
            PlanStep(step_number=3, action="POST", endpoint="/v2/invoice", payload={"orderId": 99}, description="Create invoice"),
        ])
        result = executor.execute(plan)
        assert result.success is False
        assert result.steps_completed == 1
        assert len(result.results) == 1
        assert len(result.errors) == 1
        # Step 3 should not have been called
        assert mock_client.post.call_count == 2


class TestExecuteWithReplan:
    def test_replan_on_failure_then_succeed(self, executor, mock_client):
        """Test that execute_with_replan calls replan on failure and succeeds on retry."""
        # First execution fails on step 2
        mock_client.post.side_effect = [
            {"value": {"id": 1}},
            TripletexAPIError(422, "Missing field"),
        ]
        initial_plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="POST", endpoint="/v2/customer", payload={"name": "Acme"}, description="Create customer"),
            PlanStep(step_number=2, action="POST", endpoint="/v2/order", payload={"customerId": "$step1.value.id"}, description="Create order"),
        ])

        corrected_plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="POST", endpoint="/v2/order", payload={"customer": {"id": 1}, "deliveryDate": "2024-01-01"}, description="Create order with fix"),
        ])

        mock_generator = MagicMock()
        mock_generator.replan.return_value = corrected_plan

        # Second execution succeeds
        mock_client.post.side_effect = [
            {"value": {"id": 1}},
            TripletexAPIError(422, "Missing field"),
            {"value": {"id": 50}},
        ]

        result = executor.execute_with_replan(
            plan=initial_plan,
            generator=mock_generator,
            original_prompt="Create order for Acme",
        )

        assert result.success is True
        assert mock_generator.replan.call_count == 1

    def test_max_replans_enforced(self, executor, mock_client):
        """Test that re-planning stops after max_replans attempts."""
        mock_client.post.side_effect = TripletexAPIError(500, "Server error")
        plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="POST", endpoint="/v2/employee", payload={"firstName": "Ola"}, description="Create employee"),
        ])
        failing_plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="POST", endpoint="/v2/employee", payload={"firstName": "Ola"}, description="Retry create employee"),
        ])

        mock_generator = MagicMock()
        mock_generator.replan.return_value = failing_plan

        result = executor.execute_with_replan(
            plan=plan,
            generator=mock_generator,
            original_prompt="Create employee Ola",
            max_replans=2,
        )

        assert result.success is False
        assert mock_generator.replan.call_count == 2

    def test_no_replan_on_success(self, executor, mock_client):
        """Test that replan is not called when execution succeeds."""
        mock_client.post.return_value = {"value": {"id": 1}}
        plan = ExecutionPlan(steps=[
            PlanStep(step_number=1, action="POST", endpoint="/v2/employee", payload={"firstName": "Ola"}, description="Create employee"),
        ])

        mock_generator = MagicMock()

        result = executor.execute_with_replan(
            plan=plan,
            generator=mock_generator,
            original_prompt="Create employee",
        )

        assert result.success is True
        mock_generator.replan.assert_not_called()


class TestHelpers:
    def test_traverse_simple(self):
        assert _traverse({"value": {"id": 42}}, "value.id") == 42

    def test_traverse_list(self):
        assert _traverse({"values": [{"id": 1}, {"id": 2}]}, "values.0.id") == 1

    def test_resolve_non_placeholder_string(self):
        assert _resolve_placeholders("hello", {}) == "hello"

    def test_resolve_dict_with_no_placeholders(self):
        data = {"a": 1, "b": "text"}
        assert _resolve_placeholders(data, {}) == {"a": 1, "b": "text"}

    def test_resolve_list(self):
        context = {1: {"value": {"id": 5}}}
        data = ["$step1.value.id", "static"]
        assert _resolve_placeholders(data, context) == [5, "static"]
