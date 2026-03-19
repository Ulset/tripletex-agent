from pydantic import BaseModel, ConfigDict, Field


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


class ExecutionPlan(BaseModel):
    steps: list[PlanStep]
