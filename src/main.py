import logging

from fastapi import Depends, FastAPI, HTTPException, Request

from src.config import settings
from src.models import SolveRequest, SolveResponse
from src.orchestrator import TaskOrchestrator

logger = logging.getLogger(__name__)

app = FastAPI(title="Tripletex AI Agent")


async def verify_api_key(request: Request) -> None:
    if not settings.api_key:
        return
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {settings.api_key}":
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/")
async def root():
    return {"status": "ok"}


@app.post("/solve", response_model=SolveResponse)
async def solve(request: SolveRequest, _: None = Depends(verify_api_key)):
    orchestrator = TaskOrchestrator(settings)
    return orchestrator.solve(request)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=settings.port, reload=True)
