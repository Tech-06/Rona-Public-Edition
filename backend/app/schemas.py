from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    conversation_id: str | None = Field(None, min_length=8, max_length=64)


class ToolCallInfo(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    reply: str
    model: str
    conversation_id: str
    status: Literal["ok", "confirmation_required"] = "ok"
    tool_calls: list[ToolCallInfo] | None = None
