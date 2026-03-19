from urllib.parse import parse_qs

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FileAttachment(BaseModel):
    filename: str
    content_base64: str
    mime_type: str = Field(alias="mime_type")

    model_config = ConfigDict(populate_by_name=True)


class TripletexCredentials(BaseModel):
    base_url: str
    session_token: str


class SolveRequest(BaseModel):
    prompt: str = Field(alias="task_prompt")
    files: list[FileAttachment] = Field(default=[], alias="attachments")
    tripletex_credentials: TripletexCredentials

    model_config = ConfigDict(populate_by_name=True)


class SolveResponse(BaseModel):
    status: str


class PlanStep(BaseModel):
    step_number: int
    action: str  # GET, POST, PUT, DELETE
    endpoint: str
    payload: dict | None = None
    params: dict | None = None
    description: str

    @field_validator("params", mode="before")
    @classmethod
    def coerce_params(cls, v):
        if isinstance(v, str):
            # Parse query string like "name=Mineral Water&fields=id" into dict
            parsed = parse_qs(v, keep_blank_values=True)
            return {k: vals[0] if len(vals) == 1 else vals for k, vals in parsed.items()}
        return v


class ExecutionPlan(BaseModel):
    steps: list[PlanStep]


class ExecutionResult(BaseModel):
    steps_completed: int = 0
    results: list[dict] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    success: bool = False
    total_api_calls: int = 0
    error_count: int = 0
