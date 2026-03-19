# Tripletex Agent

Entry for the Norwegian Championship in Vibe Coding (NM i Vibe-koding).

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and fill in your `OPENAI_API_KEY`.

## Running

```bash
python -m src.main
```

Or with Docker:

```bash
docker-compose up
```

## Tests

### Unit & Integration Tests

```bash
.venv/bin/pytest
```

### End-to-End Tests (Tripletex Sandbox)

E2E tests run against the real Tripletex sandbox API and are **skipped by default** unless sandbox credentials are configured.

#### Configuration

Set the following environment variables (or create a `.env.test` file in the project root):

```bash
TRIPLETEX_BASE_URL=https://api.tripletex.io   # or your sandbox proxy URL
TRIPLETEX_SESSION_TOKEN=your-sandbox-token
OPENAI_API_KEY=your-openai-key                 # required for full-flow tests
```

#### Running E2E Tests

```bash
# Run only e2e tests
.venv/bin/pytest -m e2e

# Run all tests including e2e
.venv/bin/pytest --run-e2e

# Run only unit tests (excludes e2e)
.venv/bin/pytest -m "not e2e"
```

E2E tests are marked with `@pytest.mark.e2e` and will be automatically skipped if the required credentials are not available. The full-flow test (`test_full_flow.py`) additionally requires `OPENAI_API_KEY` as it uses the LLM to generate execution plans.
