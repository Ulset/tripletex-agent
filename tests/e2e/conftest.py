import os

import pytest
from dotenv import load_dotenv

from src.tripletex_client import TripletexClient


def _load_sandbox_credentials() -> tuple[str, str]:
    """Load sandbox credentials from env vars or .env.test file."""
    # Try .env.test first, then fall back to regular env
    env_test = os.path.join(os.path.dirname(__file__), "..", "..", ".env.test")
    load_dotenv(env_test, override=False)

    base_url = os.getenv("TRIPLETEX_BASE_URL", "")
    session_token = os.getenv("TRIPLETEX_SESSION_TOKEN", "")
    return base_url, session_token


def _credentials_available() -> bool:
    base_url, session_token = _load_sandbox_credentials()
    return bool(base_url and session_token)


# Skip all e2e tests if sandbox credentials are not configured
pytestmark = pytest.mark.e2e

skip_no_credentials = pytest.mark.skipif(
    not _credentials_available(),
    reason="Sandbox credentials not configured (set TRIPLETEX_BASE_URL and TRIPLETEX_SESSION_TOKEN)",
)


@pytest.fixture
def sandbox_credentials() -> tuple[str, str]:
    """Return (base_url, session_token) for the Tripletex sandbox."""
    base_url, session_token = _load_sandbox_credentials()
    if not base_url or not session_token:
        pytest.skip("Sandbox credentials not configured")
    return base_url, session_token


@pytest.fixture
def tripletex_client(sandbox_credentials) -> TripletexClient:
    """Create a TripletexClient connected to the sandbox."""
    base_url, session_token = sandbox_credentials
    return TripletexClient(base_url=base_url, session_token=session_token)


@pytest.fixture
def openai_api_key() -> str:
    """Return the OpenAI API key, skip if not set."""
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        pytest.skip("OPENAI_API_KEY not configured")
    return key
