import json as json_module
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
        # Strip /v2 prefix from endpoint if base_url already ends with /v2
        clean_endpoint = endpoint.lstrip("/")
        if self.base_url.rstrip("/").endswith("/v2") and clean_endpoint.startswith("v2/"):
            clean_endpoint = clean_endpoint[3:]  # strip "v2/"
        url = f"{self.base_url}/{clean_endpoint}"

        # Log request details
        req_body = kwargs.get("json")
        req_params = kwargs.get("params")
        if req_body:
            logger.info(">>> %s %s body=%s", method, url, json_module.dumps(req_body, ensure_ascii=False))
        elif req_params:
            logger.info(">>> %s %s params=%s", method, url, req_params)
        else:
            logger.info(">>> %s %s", method, url)

        response = requests.request(method, url, auth=self.auth, timeout=30, **kwargs)

        # Log response
        if response.status_code >= 400:
            try:
                detail = response.json()
                message = detail.get("message", response.text)
                logger.error("<<< %d %s | detail=%s", response.status_code, message,
                             json_module.dumps(detail.get("validationMessages", []), ensure_ascii=False))
            except Exception:
                message = response.text
                logger.error("<<< %d %s", response.status_code, message)
            raise TripletexAPIError(response.status_code, message)

        if response.status_code == 204 or not response.content:
            logger.info("<<< %d (no content)", response.status_code)
            return {}

        result = response.json()
        # Log response summary (truncate large responses)
        resp_str = json_module.dumps(result, ensure_ascii=False)
        if len(resp_str) > 500:
            logger.info("<<< %d (%d chars) %s...", response.status_code, len(resp_str), resp_str[:500])
        else:
            logger.info("<<< %d %s", response.status_code, resp_str)
        return result

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
