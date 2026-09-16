"""API request and response schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class MessageRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    content_type: Literal["text", "audio", "image", "document"] = "text"
    debounce: bool = False


class MessageResponse(BaseModel):
    status: Literal["completed", "buffered", "requires_confirmation", "failed"]
    response: str | None
    checkpoint_id: str | None
    trace_id: str
    confirmation: dict[str, object] | None = None
