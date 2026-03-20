import os
import subprocess

import google.auth
import google.auth.transport.requests
from openai import OpenAI

VERTEX_ENDPOINT = (
    "https://europe-north1-aiplatform.googleapis.com/v1beta1"
    "/projects/ainm26osl-716/locations/europe-north1/endpoints/openapi"
)


def _get_access_token() -> str:
    """Get a valid access token for Vertex AI.

    On Cloud Run (K_SERVICE set): uses service account via google.auth.default().
    Locally: uses `gcloud auth print-access-token` which has full cloud-platform scope.
    """
    if os.environ.get("K_SERVICE"):
        # Cloud Run — service account credentials with proper scopes
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token

    # Local development — gcloud CLI token has full scopes
    return subprocess.check_output(
        ["gcloud", "auth", "print-access-token"],
        text=True,
    ).strip()


def get_openai_client() -> OpenAI:
    """Return an OpenAI client pointed at Vertex AI's OpenAI-compatible endpoint."""
    token = _get_access_token()
    return OpenAI(api_key=token, base_url=VERTEX_ENDPOINT)
