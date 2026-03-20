import uuid

import pytest

from tests.e2e.conftest import skip_no_credentials


@skip_no_credentials
@pytest.mark.e2e
class TestCreateSupplier:
    """E2E tests for creating suppliers via the Tripletex sandbox API."""

    def test_create_supplier_basic(self, tripletex_client):
        """Create a supplier with minimum fields."""
        unique = uuid.uuid4().hex[:6]
        name = f"Supplier E2E-{unique}"

        data = {"name": name, "isSupplier": True}
        resp = tripletex_client.post("/v2/supplier", json=data)

        assert "value" in resp
        supplier_id = resp["value"]["id"]

        get_resp = tripletex_client.get(f"/v2/supplier/{supplier_id}")
        assert get_resp["value"]["name"] == name

    def test_create_supplier_with_org_number(self, tripletex_client):
        """Create a supplier with organizationNumber and verify."""
        unique = uuid.uuid4().hex[:6]
        name = f"Supplier Org-{unique}"
        import random
        org_number = str(random.randint(900000000, 999999999))  # 9 digits, numeric only

        data = {
            "name": name,
            "isSupplier": True,
            "organizationNumber": org_number,
            "email": f"supplier-{unique}@example.com",
            "phoneNumber": "98765432",
        }
        resp = tripletex_client.post("/v2/supplier", json=data)

        assert "value" in resp
        supplier_id = resp["value"]["id"]

        get_resp = tripletex_client.get(f"/v2/supplier/{supplier_id}")
        assert get_resp["value"]["name"] == name
        assert get_resp["value"]["organizationNumber"] == org_number

    def test_create_supplier_with_address(self, tripletex_client):
        """Create a supplier with postal address as JSON object."""
        unique = uuid.uuid4().hex[:6]
        name = f"Supplier Addr-{unique}"

        data = {
            "name": name,
            "isSupplier": True,
            "postalAddress": {
                "addressLine1": "Storgata 1",
                "postalCode": "0150",
                "city": "Oslo",
            },
        }
        resp = tripletex_client.post("/v2/supplier", json=data)

        assert "value" in resp
        supplier_id = resp["value"]["id"]

        get_resp = tripletex_client.get(f"/v2/supplier/{supplier_id}")
        assert get_resp["value"]["name"] == name
