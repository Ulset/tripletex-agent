"""Tuning tests for supplier invoice registration workflow.

Based on production failure (2026-03-20 12:47 PM): agent looked up supplier, accounts,
and VAT types but never created the voucher — returned empty response (0 API errors but
task not completed).
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_supplier_invoice_mock() -> MockTripletexClient:
    """Set up mock with supplier and ledger accounts for invoice registration."""
    mock = MockTripletexClient()

    # Supplier
    mock.register_entity("supplier", {
        "id": 100,
        "name": "Elvdal AS",
        "organizationNumber": "889157917",
    })

    # Expense account 6500
    mock.register_entity("ledger/account", {
        "id": 200,
        "number": 6500,
        "name": "Motordrevet verktøy",
    })

    # Supplier debt account 2400
    mock.register_entity("ledger/account", {
        "id": 201,
        "number": 2400,
        "name": "Leverandørgjeld",
    })

    # Incoming VAT account 2710
    mock.register_entity("ledger/account", {
        "id": 202,
        "number": 2710,
        "name": "Inngående merverdiavgift, høy sats",
    })

    # VAT types
    mock.register_entity("ledger/vatType", {
        "id": 1,
        "name": "Fradrag inngående avgift, høy sats",
        "number": "1",
        "percentage": 25.0,
    })

    return mock


@skip_no_vertex
class TestSupplierInvoice:
    """Agent should register supplier invoices as vouchers with correct postings."""

    def test_supplier_invoice_nynorsk(self, run_agent):
        """Exact production prompt (Nynorsk): register supplier invoice with VAT."""
        mock = _make_supplier_invoice_mock()

        prompt = (
            "Me har motteke faktura INV-2026-8662 frå leverandøren Elvdal AS "
            "(org.nr 889157917) på 39750 kr inklusiv MVA. Beløpet gjeld kontortenester "
            "(konto 6500). Registrer leverandørfakturaen med korrekt inngåande MVA (25 %)."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        # Must create a voucher (supplier invoices are registered as vouchers)
        voucher_call = result.assert_endpoint_called("POST", "/v2/ledger/voucher")
        assert voucher_call.body is not None

        # Voucher must have postings
        postings = voucher_call.body.get("postings", [])
        assert len(postings) >= 2, f"Expected at least 2 postings, got {len(postings)}"

        # Postings must use amountGross
        for p in postings:
            assert "amountGross" in p or "amountGrossCurrency" in p, \
                f"Must use amountGross. Keys: {list(p.keys())}"

        # Should reference the invoice number
        body = voucher_call.body
        has_invoice_ref = (
            body.get("vendorInvoiceNumber") or
            "INV-2026-8662" in body.get("description", "")
        )
        assert has_invoice_ref, "Should reference invoice number INV-2026-8662"

        result.assert_no_errors()
        result.assert_max_calls(7)

    def test_supplier_invoice_english(self, run_agent):
        """English variant: register supplier invoice."""
        mock = _make_supplier_invoice_mock()

        prompt = (
            "We have received invoice INV-2026-1234 from supplier Elvdal AS "
            "(org. no. 889157917) for 50000 NOK including VAT. The amount is for "
            "office services (account 6500). Register the supplier invoice with "
            "correct incoming VAT (25%)."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("POST", "/v2/ledger/voucher")
        result.assert_no_errors()
        result.assert_max_calls(7)
