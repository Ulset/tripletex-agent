import uuid

import pytest

from tests.e2e.conftest import skip_no_credentials


@skip_no_credentials
@pytest.mark.e2e
class TestCreateDepartment:
    """E2E tests for creating departments via the Tripletex sandbox API."""

    def test_create_single_department(self, tripletex_client):
        """Create a department and verify it exists."""
        unique = uuid.uuid4().hex[:6]
        name = f"Dept E2E-{unique}"
        dept_number = f"D{unique[:4]}"

        data = {"name": name, "departmentNumber": dept_number}
        resp = tripletex_client.post("/v2/department", json=data)

        assert "value" in resp
        dept_id = resp["value"]["id"]

        get_resp = tripletex_client.get(f"/v2/department/{dept_id}")
        assert get_resp["value"]["name"] == name
        assert get_resp["value"]["departmentNumber"] == dept_number

    def test_create_multiple_departments(self, tripletex_client):
        """Create multiple departments and verify all exist."""
        unique = uuid.uuid4().hex[:6]
        departments = []
        for i in range(3):
            name = f"MultiDept-{i}-{unique}"
            number = f"M{unique[:3]}{i}"
            data = {"name": name, "departmentNumber": number}
            resp = tripletex_client.post("/v2/department", json=data)
            assert "value" in resp
            departments.append((resp["value"]["id"], name))

        # Verify all departments exist
        for dept_id, expected_name in departments:
            get_resp = tripletex_client.get(f"/v2/department/{dept_id}")
            assert get_resp["value"]["name"] == expected_name
