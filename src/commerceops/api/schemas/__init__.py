"""API request and response schemas."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MessageRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    content_type: Literal["text", "audio", "image", "document"] = "text"
    debounce: bool = False

    @model_validator(mode="after")
    def text_debounce_only(self) -> "MessageRequest":
        if self.debounce and self.content_type != "text":
            raise ValueError("Debounce aggregation supports text messages only.")
        return self


class MessageResponse(BaseModel):
    status: Literal["completed", "buffered", "requires_confirmation", "failed"]
    response: str | None
    checkpoint_id: str | None
    trace_id: str
    confirmation: dict[str, object] | None = None
    error_code: str | None = None


class SessionStateResponse(BaseModel):
    session_id: str
    status: Literal["buffered", "running", "requires_confirmation", "completed", "failed"]
    source_message_ids: list[str]
    result: MessageResponse | None
    state: dict[str, Any]
