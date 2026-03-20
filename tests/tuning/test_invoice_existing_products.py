"""Tuning tests for invoice creation with existing products.

Based on production failure (2026-03-20): agent tried to POST products that already
existed (3x "number in use" errors) instead of GETting them by number. Also tests
bank account setup efficiency.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_invoice_mock() -> MockTripletexClient:
    """Set up mock with customer and existing products for invoice tasks."""
    mock = MockTripletexClient()

    mock.register_entity("customer", {
        "id": 100,
        "name": "Fjelltopp AS",
        "organizationNumber": "862382900",
    })

    # Existing products with VAT types already set
    mock.register_entity("product", {
        "id": 200,
        "name": "Analyserapport",
        "number": "3271",
        "priceExcludingVatCurrency": 1950,
        "vatType": {"id": 3, "percentage": 25.0},
    })
    mock.register_entity("product", {
        "id": 201,
        "name": "Skylagring",
        "number": "8738",
        "priceExcludingVatCurrency": 6850,
        "vatType": {"id": 31, "percentage": 15.0},
    })
    mock.register_entity("product", {
        "id": 202,
        "name": "Nettverksteneste",
        "number": "3354",
        "priceExcludingVatCurrency": 12800,
        "vatType": {"id": 5, "percentage": 0.0},
    })

    # Bank account
    mock.register_entity("ledger/account", {
        "id": 300,
        "number": 1920,
        "name": "Bankinnskudd",
        "isBankAccount": True,
    })

    return mock


@skip_no_vertex
class TestInvoiceExistingProducts:
    """Agent should GET existing products by number, never POST when numbers are given."""

    def test_three_products_nynorsk(self, run_agent):
        """Exact production prompt: 3 existing products with different VAT rates."""
        mock = _make_invoice_mock()

        prompt = (
            "Opprett ein faktura til kunden Fjelltopp AS (org.nr 862382900) med tre "
            "produktlinjer: Analyserapport (3271) til 1950 kr med 25 % MVA, Skylagring "
            "(8738) til 6850 kr med 15 % MVA (næringsmiddel), og Nettverksteneste (3354) "
            "til 12800 kr med 0 % MVA (avgiftsfri)."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        # Must GET products, NOT POST
        product_posts = result.find_calls("POST", "/v2/product")
        assert len(product_posts) == 0, \
            f"Should NOT create products (they exist). Got {len(product_posts)} POSTs"

        product_gets = result.find_calls("GET", "/v2/product")
        assert len(product_gets) >= 3, f"Should GET 3 products, got {len(product_gets)}"

        # Must create order and invoice
        result.assert_endpoint_called("POST", "/v2/order")
        result.assert_endpoint_called("PUT", "/:invoice")

        result.assert_no_errors()
        # Optimal: GET customer + GET prod×3 + GET bank + PUT bank + POST order + PUT invoice = 8
        result.assert_max_calls(10)

    def test_single_product_invoice_portuguese(self, run_agent):
        """Production prompt: create invoice for single product."""
        mock = MockTripletexClient()
        mock.register_entity("customer", {
            "id": 100,
            "name": "Luz do Sol Lda",
            "organizationNumber": "861434575",
        })
        mock.register_entity("ledger/account", {
            "id": 300,
            "number": 1920,
            "name": "Bankinnskudd",
            "isBankAccount": True,
        })

        prompt = (
            "Crie e envie uma fatura ao cliente Luz do Sol Lda (org. nº 861434575) "
            "por 48800 NOK sem IVA. A fatura refere-se a Design web."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("POST", "/v2/order")
        result.assert_endpoint_called("PUT", "/:invoice")

        result.assert_no_errors()
        result.assert_max_calls(8)
