"""Tuning tests for fixed-price project + partial invoicing workflows.

Based on production failure (2026-03-20 11:46 AM): agent used wrong field name
"fixedPriceAmount" (422 error), then invoice creation failed because company had
no bank account number registered. Agent gave up instead of fixing the bank account.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_project_invoice_mock() -> MockTripletexClient:
    """Set up mock with pre-existing entities for project + invoice tasks."""
    mock = MockTripletexClient()

    # Employee (project manager)
    mock.register_entity("employee", {
        "id": 100,
        "firstName": "Ricardo",
        "lastName": "López",
        "email": "ricardo.lopez@example.org",
    })

    # Customer
    mock.register_entity("customer", {
        "id": 200,
        "name": "Montaña SL",
        "organizationNumber": "950971622",
    })

    # Bank account (ledger account 1920) — needs bankAccountNumber set
    mock.register_entity("ledger/account", {
        "id": 300,
        "number": 1920,
        "name": "Bankinnskudd",
        "isBankAccount": True,
        "bankAccountNumber": None,
    })

    # VAT types
    mock.register_entity("ledger/vatType", {
        "id": 3,
        "name": "Utgående mva, høy sats",
        "number": "3",
        "percentage": 25.0,
    })

    return mock


@skip_no_vertex
class TestFixedPriceProject:
    """Agent should create fixed-price project with correct field names."""

    def test_create_fixed_price_project_spanish(self, run_agent):
        """Exact production prompt (Spanish): fixed-price project + 33% partial invoice."""
        mock = _make_project_invoice_mock()

        prompt = (
            'Establezca un precio fijo de 419850 NOK en el proyecto "Implementación ERP" '
            "para Montaña SL (org. nº 950971622). El director del proyecto es Ricardo López "
            "(ricardo.lopez@example.org). Facture al cliente el 33 % del precio fijo como "
            "pago parcial."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        # Must create the project with correct fixed price fields
        result.assert_endpoint_called("POST", "/v2/project")
        project_call = result.find_calls("POST", "/v2/project")[0]
        assert project_call.body is not None
        # Must use "fixedprice" (lowercase), NOT "fixedPriceAmount"
        assert "fixedprice" in project_call.body or "fixedprice" in str(project_call.body).lower(), \
            f"Expected 'fixedprice' field. Body keys: {list(project_call.body.keys())}"
        assert project_call.body.get("isFixedPrice") is True, \
            f"Expected isFixedPrice=true. Body: {project_call.body}"

        # Must create order and invoice
        result.assert_endpoint_called("POST", "/v2/order")
        result.assert_endpoint_called("PUT", "/:invoice")

        result.assert_no_errors()
        result.assert_max_calls(10)

    def test_create_fixed_price_project_norwegian(self, run_agent):
        """Norwegian variant: fixed-price project + partial invoice."""
        mock = _make_project_invoice_mock()

        prompt = (
            'Sett en fastpris på 500000 NOK på prosjektet "ERP-implementering" '
            "for kunde Montaña SL (org.nr 950971622). Prosjektleder er Ricardo López "
            "(ricardo.lopez@example.org). Fakturer kunden 25 % av fastprisen som "
            "delbetaling."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        # Must create project with fixed price
        result.assert_endpoint_called("POST", "/v2/project")
        project_call = result.find_calls("POST", "/v2/project")[0]
        assert project_call.body is not None
        assert project_call.body.get("isFixedPrice") is True

        # Must create order and invoice for 25% = 125000
        result.assert_endpoint_called("POST", "/v2/order")
        result.assert_endpoint_called("PUT", "/:invoice")

        result.assert_no_errors()
        result.assert_max_calls(10)
