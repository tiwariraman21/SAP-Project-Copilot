from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExtractedRequirement(BaseModel):
    title: str
    statement: str
    requirement_type: Literal["functional", "non_functional", "integration", "data", "security", "reporting"]
    priority: Literal["must", "should", "could"]
    rationale: str = ""
    acceptance_criteria: list[str] = Field(min_length=1)
    assumptions: list[str] = []
    source_chunk_ids: list[str] = Field(min_length=1)
    source_quote: str
    confidence: float = Field(ge=0, le=1)


class RequirementBatch(BaseModel):
    requirements: list[ExtractedRequirement]


class RequirementUpdate(BaseModel):
    title: str | None = None
    statement: str | None = None
    requirement_type: Literal["functional", "non_functional", "integration", "data", "security", "reporting"] | None = None
    priority: Literal["must", "should", "could"] | None = None
    rationale: str | None = None
    acceptance_criteria: list[str] | None = None
    assumptions: list[str] | None = None
    review_status: Literal["pending", "approved", "rejected"] | None = None
    reviewer_note: str | None = None


class RequirementCreate(BaseModel):
    title: str
    statement: str
    requirement_type: Literal["functional", "non_functional", "integration", "data", "security", "reporting"] = "functional"
    priority: Literal["must", "should", "could"] = "must"
    rationale: str = ""
    acceptance_criteria: list[str] = Field(default_factory=lambda: ["Requirement criteria met"])
    assumptions: list[str] = Field(default_factory=list)
    source_quote: str = "Manually specified requirement"
    reviewer_note: str = ""
    review_status: Literal["pending", "approved", "rejected"] = "approved"



class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    page: int
    locator: str
    text: str


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    requirement_key: str
    title: str
    statement: str
    requirement_type: str
    priority: str
    rationale: str
    acceptance_criteria: list[str]
    assumptions: list[str]
    source_chunk_ids: list[str]
    source_quote: str
    confidence: float
    review_status: str
    reviewer_note: str


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    kind: str
    status: str
    payload: dict


class CompanionAsk(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class CompanionSourceOut(BaseModel):
    kind: str
    label: str
    detail: str = ""
    status: str | None = None


class CompanionTurnOut(BaseModel):
    question: str
    answer: str
    sources: list[CompanionSourceOut] = []
    asked_at: str | None = None


class CompanionAnswerOut(BaseModel):
    project_id: str
    project_name: str
    question: str
    answer: str
    sources: list[CompanionSourceOut]
    suggested_questions: list[str]
    asked_at: str


class CompanionContextOut(BaseModel):
    project_id: str
    project_name: str
    available_sources: list[CompanionSourceOut]
    suggested_questions: list[str]
    history: list[CompanionTurnOut]
    guardrail: str


class ProjectOut(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime
    filename: str
    page_count: int
    chunks: list[ChunkOut]
    requirements: list[RequirementOut]
    artifacts: list[ArtifactOut]


class JiraConfigIn(BaseModel):
    jira_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_project_key: str | None = None


class JiraConfigStatusOut(BaseModel):
    configured_in_env: bool
    jira_url: str | None = None
    jira_email: str | None = None
    has_api_token: bool = False
    suggested_project_key: str = "GP"



class JiraTestConnectionOut(BaseModel):
    success: bool
    message: str
    user_display_name: str | None = None
    project_name: str | None = None
    project_key: str | None = None



class JiraSyncIn(BaseModel):
    jira_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_project_key: str | None = None
    create_epic: bool = True
    create_sprints: bool = True


class JiraSyncResultOut(BaseModel):
    success: bool
    message: str
    jira_url: str
    project_key: str
    epic_key: str | None = None
    epic_url: str | None = None
    sprints_created: int = 0
    stories_created: int = 0
    board_url: str | None = None
    synced_stories: list[dict] = []


