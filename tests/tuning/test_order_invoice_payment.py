"""Tuning tests for order + invoice + payment workflow efficiency.

Based on production data: agent sometimes filters paymentType by description
(returns empty), wasting a call. Also tests overall call efficiency.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_order_invoice_payment_mock() -> MockTripletexClient:
    """Set up mock with customer, products, and payment types."""
    mock = MockTripletexClient()

    mock.register_entity("customer", {
        "id": 100,
        "name": "Nordhav AS",
        "organizationNumber": "904923915",
    })
    mock.register_entity("product", {
        "id": 200,
        "name": "Konsulenttimer",
        "number": "7493",
        "priceExcludingVatCurrency": 8200,
    })
    mock.register_entity("product", {
        "id": 201,
        "name": "Webdesign",
        "number": "5668",
        "priceExcludingVatCurrency": 24500,
    })
    mock.register_entity("ledger/account", {
        "id": 300,
        "number": 1920,
        "name": "Bankinnskudd",
        "isBankAccount": True,
    })
    mock.register_entity("invoice/paymentType", {
        "id": 400,
        "description": "Kontant",
    })
    mock.register_entity("invoice/paymentType", {
        "id": 401,
        "description": "Bankinnskudd",
    })

    return mock


@skip_no_vertex
class TestOrderInvoicePayment:
    """Agent should complete order+invoice+payment efficiently."""

    def test_full_flow_norwegian(self, run_agent):
        """Production prompt: order with 2 existing products + invoice + payment."""
        mock = _make_order_invoice_payment_mock()

        prompt = (
            "Opprett en ordre for kunden Nordhav AS (org.nr 904923915) med produktene "
            "Konsulenttimer (7493) til 8200 kr og Webdesign (5668) til 24400 kr. "
            "Konverter ordren til faktura og registrer full betaling."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("GET", "/v2/customer")
        result.assert_endpoint_called("GET", "/v2/product")
        result.assert_endpoint_called("POST", "/v2/order")
        result.assert_endpoint_called("PUT", "/:invoice")
        result.assert_endpoint_called("GET", "/v2/invoice/paymentType")
        result.assert_endpoint_called("PUT", "/:payment")

        # PaymentType GET should be exactly 1 (no filter retry)
        pt_gets = result.find_calls("GET", "/v2/invoice/paymentType")
        assert len(pt_gets) == 1, f"Should GET paymentType once without filter, got {len(pt_gets)}"

        result.assert_no_errors()
        result.assert_max_calls(12)

    def test_full_flow_german(self, run_agent):
        """German variant of order + invoice + payment."""
        mock = _make_order_invoice_payment_mock()

        prompt = (
            "Erstellen Sie einen Auftrag für den Kunden Nordhav AS (Org.-Nr. 904923915) "
            "mit den Produkten Konsulenttimer (7493) zu 8200 NOK und Webdesign (5668) zu "
            "24400 NOK. Wandeln Sie den Auftrag in eine Rechnung um und registrieren Sie "
            "die vollständige Zahlung."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("POST", "/v2/order")
        result.assert_endpoint_called("PUT", "/:invoice")
        result.assert_endpoint_called("PUT", "/:payment")

        result.assert_no_errors()
        result.assert_max_calls(12)
