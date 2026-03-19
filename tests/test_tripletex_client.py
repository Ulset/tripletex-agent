import responses

from src.tripletex_client import TripletexAPIError, TripletexClient

BASE_URL = "https://api.tripletex.io/v2"
TOKEN = "test-session-token"


def make_client() -> TripletexClient:
    return TripletexClient(BASE_URL, TOKEN)


class TestTripletexClientGet:
    @responses.activate
    def test_get_success(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/employee",
            json={"fullResultSize": 1, "values": [{"id": 1, "name": "Ola"}]},
            status=200,
        )
        result = make_client().get("/employee")
        assert result["values"][0]["name"] == "Ola"

    @responses.activate
    def test_get_with_fields_and_pagination(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/employee",
            json={"fullResultSize": 50, "values": []},
            status=200,
        )
        make_client().get("/employee", fields="id,name", count=10, from_=20)
        assert responses.calls[0].request.params == {
            "fields": "id,name",
            "count": "10",
            "from": "20",
        }

    @responses.activate
    def test_get_with_extra_params(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/employee",
            json={"fullResultSize": 0, "values": []},
            status=200,
        )
        make_client().get("/employee", params={"name": "Ola"})
        assert responses.calls[0].request.params["name"] == "Ola"


class TestTripletexClientPost:
    @responses.activate
    def test_post_success(self):
        responses.add(
            responses.POST,
            f"{BASE_URL}/employee",
            json={"value": {"id": 42, "firstName": "Ola"}},
            status=201,
        )
        result = make_client().post("/employee", json={"firstName": "Ola"})
        assert result["value"]["id"] == 42

    @responses.activate
    def test_post_sends_json_body(self):
        responses.add(
            responses.POST,
            f"{BASE_URL}/customer",
            json={"value": {"id": 1}},
            status=201,
        )
        make_client().post("/customer", json={"name": "Bedrift AS"})
        assert b'"name": "Bedrift AS"' in responses.calls[0].request.body


class TestTripletexClientPut:
    @responses.activate
    def test_put_success(self):
        responses.add(
            responses.PUT,
            f"{BASE_URL}/employee/42",
            json={"value": {"id": 42, "firstName": "Kari"}},
            status=200,
        )
        result = make_client().put("/employee/42", json={"firstName": "Kari"})
        assert result["value"]["firstName"] == "Kari"


class TestTripletexClientDelete:
    @responses.activate
    def test_delete_success(self):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}/travelExpense/5",
            json={},
            status=200,
        )
        result = make_client().delete("/travelExpense/5")
        assert result == {}


class TestTripletexClientErrors:
    @responses.activate
    def test_4xx_raises_error(self):
        responses.add(
            responses.POST,
            f"{BASE_URL}/employee",
            json={"message": "Validation failed: firstName is required"},
            status=422,
        )
        try:
            make_client().post("/employee", json={})
            assert False, "Should have raised TripletexAPIError"
        except TripletexAPIError as e:
            assert e.status_code == 422
            assert "firstName is required" in e.message

    @responses.activate
    def test_5xx_raises_error(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/employee",
            json={"message": "Internal server error"},
            status=500,
        )
        try:
            make_client().get("/employee")
            assert False, "Should have raised TripletexAPIError"
        except TripletexAPIError as e:
            assert e.status_code == 500

    @responses.activate
    def test_error_with_non_json_response(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/employee",
            body="Bad Gateway",
            status=502,
        )
        try:
            make_client().get("/employee")
            assert False, "Should have raised TripletexAPIError"
        except TripletexAPIError as e:
            assert e.status_code == 502
            assert "Bad Gateway" in e.message


class TestTripletexClientAuth:
    @responses.activate
    def test_basic_auth_sent(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/employee",
            json={"values": []},
            status=200,
        )
        make_client().get("/employee")
        auth_header = responses.calls[0].request.headers.get("Authorization")
        # Basic auth with username "0" and password = token
        assert auth_header is not None
        assert auth_header.startswith("Basic ")
