import uuid

import pytest

from tests.e2e.conftest import skip_no_credentials


@skip_no_credentials
@pytest.mark.e2e
class TestCreateProduct:
    """E2E tests for creating products via the Tripletex sandbox API."""

    def test_create_product_basic(self, tripletex_client):
        """Create a product with minimum fields."""
        unique = uuid.uuid4().hex[:6]
        name = f"Product E2E-{unique}"
        number = f"P{unique}"

        data = {"name": name, "number": number}
        resp = tripletex_client.post("/v2/product", json=data)

        assert "value" in resp
        product_id = resp["value"]["id"]

        get_resp = tripletex_client.get(f"/v2/product/{product_id}")
        assert get_resp["value"]["name"] == name
        assert get_resp["value"]["number"] == number

    def test_create_product_with_price(self, tripletex_client):
        """Create a product with price and verify."""
        unique = uuid.uuid4().hex[:6]
        name = f"Product Price-{unique}"
        number = f"PP{unique}"

        data = {
            "name": name,
            "number": number,
            "priceExcludingVatCurrency": 199.50,
        }
        resp = tripletex_client.post("/v2/product", json=data)

        assert "value" in resp
        product_id = resp["value"]["id"]

        get_resp = tripletex_client.get(f"/v2/product/{product_id}")
        assert get_resp["value"]["name"] == name
        assert get_resp["value"]["priceExcludingVatCurrency"] == 199.50

    def test_create_product_with_vat_type(self, tripletex_client):
        """Create a product with a VAT type and verify."""
        unique = uuid.uuid4().hex[:6]

        # First, find an available VAT type
        vat_resp = tripletex_client.get("/v2/ledger/vatType", params={"count": 20})
        assert "values" in vat_resp
        vat_types = vat_resp["values"]
        assert len(vat_types) > 0

        # Use the first VAT type
        vat_type_id = vat_types[0]["id"]

        name = f"Product VAT-{unique}"
        number = f"PV{unique}"

        data = {
            "name": name,
            "number": number,
            "priceExcludingVatCurrency": 100.0,
            "vatType": {"id": vat_type_id},
        }
        resp = tripletex_client.post("/v2/product", json=data)

        assert "value" in resp
        product_id = resp["value"]["id"]

        get_resp = tripletex_client.get(f"/v2/product/{product_id}")
        assert get_resp["value"]["name"] == name
