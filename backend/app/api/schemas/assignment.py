from typing import Literal

from pydantic import BaseModel, Field


class DraftUpdateRequest(BaseModel):
    content: str = Field(max_length=100_000)
    source: Literal["student", "ai"] = "student"


class SuggestionRequest(BaseModel):
    action: Literal["generate", "rewrite"]
    length: Literal["short", "standard", "detailed"] = "standard"
    style: Literal["academic", "simple", "formal"] = "academic"
    selected_text: str | None = Field(default=None, max_length=20_000)
    instruction: str | None = Field(default=None, max_length=2_000)


class RestoreVersionRequest(BaseModel):
    version_id: int = Field(gt=0)
