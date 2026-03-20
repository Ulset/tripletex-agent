import uuid

import pytest

from tests.e2e.conftest import skip_no_credentials


@skip_no_credentials
@pytest.mark.e2e
class TestEmployeeWithEmployment:
    """E2E tests for creating employees with separate employment records."""

    def _get_department_id(self, client):
        """Get the first available department ID."""
        resp = client.get("/v2/department", fields="id", count=1)
        return resp["values"][0]["id"]

    def test_create_employee_then_employment(self, tripletex_client):
        """Create an employee, then create a separate employment with start date."""
        unique = uuid.uuid4().hex[:6]
        first_name = f"EmpTest-{unique}"
        last_name = f"Employment-{unique}"
        dept_id = self._get_department_id(tripletex_client)

        # Step 1: Create employee (dateOfBirth REQUIRED before creating employment)
        employee_data = {
            "firstName": first_name,
            "lastName": last_name,
            "userType": "STANDARD",
            "email": f"emp-{unique}@example.com",
            "department": {"id": dept_id},
            "dateOfBirth": "1990-03-15",
        }
        emp_resp = tripletex_client.post("/v2/employee", json=employee_data)

        assert "value" in emp_resp
        employee_id = emp_resp["value"]["id"]

        # Step 2: Create employment with start date (SEPARATE call)
        employment_data = {
            "employee": {"id": employee_id},
            "startDate": "2026-01-15",
        }
        employment_resp = tripletex_client.post("/v2/employee/employment", json=employment_data)

        assert "value" in employment_resp
        assert employment_resp["value"]["startDate"] == "2026-01-15"

    def test_create_employee_with_date_of_birth(self, tripletex_client):
        """Create an employee with dateOfBirth field."""
        unique = uuid.uuid4().hex[:6]
        dept_id = self._get_department_id(tripletex_client)

        employee_data = {
            "firstName": f"Birth-{unique}",
            "lastName": f"Date-{unique}",
            "userType": "STANDARD",
            "email": f"dob-{unique}@example.com",
            "department": {"id": dept_id},
            "dateOfBirth": "1990-05-15",
        }
        resp = tripletex_client.post("/v2/employee", json=employee_data)

        assert "value" in resp
        employee_id = resp["value"]["id"]

        get_resp = tripletex_client.get(f"/v2/employee/{employee_id}")
        assert get_resp["value"]["dateOfBirth"] == "1990-05-15"
