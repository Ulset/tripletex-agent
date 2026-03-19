import logging

import requests

logger = logging.getLogger(__name__)


class TripletexAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Tripletex API error {status_code}: {message}")


class TripletexClient:
    def __init__(self, base_url: str, session_token: str):
        self.base_url = base_url.rstrip("/")
        self.session_token = session_token
        self.auth = ("0", session_token)

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = requests.request(method, url, auth=self.auth, timeout=30, **kwargs)
        logger.info("%s %s -> %d", method, endpoint, response.status_code)

        if response.status_code >= 400:
            try:
                detail = response.json()
                message = detail.get("message", response.text)
            except Exception:
                message = response.text
            raise TripletexAPIError(response.status_code, message)

        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def get(self, endpoint: str, params: dict | None = None, fields: str | None = None,
            count: int | None = None, from_: int | None = None) -> dict:
        if params is None:
            params = {}
        if fields is not None:
            params["fields"] = fields
        if count is not None:
            params["count"] = count
        if from_ is not None:
            params["from"] = from_
        return self._request("GET", endpoint, params=params)

    def post(self, endpoint: str, json: dict | None = None) -> dict:
        return self._request("POST", endpoint, json=json)

    def put(self, endpoint: str, json: dict | None = None) -> dict:
        return self._request("PUT", endpoint, json=json)

    def delete(self, endpoint: str) -> dict:
        return self._request("DELETE", endpoint)
