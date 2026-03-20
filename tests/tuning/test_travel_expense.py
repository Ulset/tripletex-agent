"""Tuning tests for travel expense workflows.

Based on production failure: agent hit max iterations (15) with 7/10 API errors
because it didn't know to create the parent travelExpense first, then add costs.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_travel_expense_mock() -> MockTripletexClient:
    """Set up mock with pre-existing entities a travel expense task would need."""
    mock = MockTripletexClient()

    # Employee exists in the system
    mock.register_entity("employee", {
        "id": 100,
        "firstName": "Astrid",
        "lastName": "Larsen",
        "email": "astrid.larsen@example.org",
    })

    # Payment types available
    mock.register_entity("travelExpense/paymentType", {
        "id": 200,
        "description": "Kontant",
        "displayName": "Kontant",
    })
    mock.register_entity("travelExpense/paymentType", {
        "id": 201,
        "description": "Bankinnskudd",
        "displayName": "Bankinnskudd",
    })

    # Cost categories available
    mock.register_entity("travelExpense/costCategory", {
        "id": 300,
        "description": "Flyreise",
        "showOnTravelExpenses": True,
    })
    mock.register_entity("travelExpense/costCategory", {
        "id": 301,
        "description": "Overnatting",
        "showOnTravelExpenses": True,
    })
    mock.register_entity("travelExpense/costCategory", {
        "id": 302,
        "description": "Taxi",
        "showOnTravelExpenses": True,
    })

    return mock


@skip_no_vertex
class TestTravelExpenseRegistration:
    """Agent should create parent travel expense first, then add costs/allowances."""

    def test_register_travel_expense_norwegian(self, run_agent):
        """Real production prompt (Norwegian): conference trip with flight and accommodation."""
        mock = _make_travel_expense_mock()

        prompt = (
            "Registrer en reiseutgift for ansatt Astrid Larsen (astrid.larsen@example.org). "
            "Reisen er til en konferanse i Ålesund fra 26. oktober 2023 til 29. oktober 2023. "
            "Tittel: Konferanse Ålesund. "
            "Utgifter: Flybillett 6750 kr (betalt av ansatt)."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        # Must create parent travel expense
        result.assert_endpoint_called("POST", "/v2/travelExpense")

        # Must add the flight cost
        cost_calls = result.find_calls("POST", "/v2/travelExpense/cost")
        assert len(cost_calls) >= 1, "Expected at least one cost to be created"

        # Efficiency: should complete in ~6 calls or fewer
        result.assert_max_calls(8)

        # Zero errors is the goal for efficiency bonus
        result.assert_no_errors()

    def test_register_travel_expense_english(self, run_agent):
        """English version of the same task."""
        mock = _make_travel_expense_mock()

        prompt = (
            "Register a travel expense for employee Astrid Larsen (astrid.larsen@example.org). "
            "The trip is to a conference in Ålesund from October 26, 2023 to October 29, 2023. "
            "Title: Ålesund Conference. "
            "Expenses: Flight ticket 6750 NOK (paid by employee)."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("POST", "/v2/travelExpense")
        result.assert_endpoint_called("POST", "/v2/travelExpense/cost")
        result.assert_max_calls(8)
        result.assert_no_errors()

    def test_travel_expense_with_accommodation_allowance(self, run_agent):
        """Travel expense that includes both costs and accommodation allowance."""
        mock = _make_travel_expense_mock()

        prompt = (
            "Registrer en reiseutgift for Astrid Larsen (astrid.larsen@example.org). "
            "Tittel: Konferanse Ålesund. "
            "Reise fra 26. oktober 2023 til 29. oktober 2023 til Ålesund. "
            "Utgifter: Flybillett 6750 kr (betalt av ansatt). "
            "Overnatting: 4 netter i Ålesund, 800 kr per natt."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("POST", "/v2/travelExpense")
        result.assert_endpoint_called("POST", "/v2/travelExpense/cost")

        # Should create accommodation allowance
        acc_calls = result.find_calls("POST", "/v2/travelExpense/accommodationAllowance")
        assert len(acc_calls) >= 1, "Expected accommodation allowance to be created"

        result.assert_max_calls(10)
        result.assert_no_errors()


@skip_no_vertex
class TestDeleteTravelExpense:
    """Agent should find and delete a travel expense."""

    def test_delete_travel_expense(self, run_agent):
        mock = MockTripletexClient()

        mock.register_entity("employee", {
            "id": 100,
            "firstName": "Astrid",
            "lastName": "Larsen",
            "email": "astrid.larsen@example.org",
        })

        # Existing travel expense to delete
        mock.register_entity("travelExpense", {
            "id": 500,
            "title": "Konferanse Bergen",
            "employee": {"id": 100},
        })

        prompt = (
            "Slett reiseutgiften 'Konferanse Bergen' for ansatt Astrid Larsen "
            "(astrid.larsen@example.org)."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("DELETE", "/v2/travelExpense")
        result.assert_max_calls(5)
        result.assert_no_errors()
