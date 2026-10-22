from typing import Any, Literal

from pydantic import BaseModel, Field


class ConfirmationDecision(BaseModel):
    approved: bool
    pending_hash: str = Field(..., min_length=1, max_length=128)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    conversation_id: str | None = Field(None, min_length=8, max_length=64)
    # Structured Approve/Reject bound to the pending calls. When the
    # conversation is awaiting confirmation it decides (no LLM); `message`
    # stays the visible user text. Ignored when nothing is pending.
    confirmation: ConfirmationDecision | None = None


class ToolCallInfo(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    reply: str
    model: str
    conversation_id: str
    status: Literal["ok", "confirmation_required"] = "ok"
    tool_calls: list[ToolCallInfo] | None = None
    pending_hash: str | None = None


# -- History import ---------------------------------------------------------
# The payload is validated as a whole: any schema error rejects the entire
# import with a 422 rather than importing "the good part". That is
# predictable for the one-time browser migration (which can simply be
# retried) and keeps a bad entry from silently dropping a conversation.
# Folder/conversation *content* oddities that graph.history already
# tolerates (blank folder name, non-dict messages, unknown folderId) are not
# schema errors and stay lenient.

HISTORY_IMPORT_MAX_CONVERSATIONS = 1000
HISTORY_IMPORT_MAX_FOLDERS = 500
HISTORY_IMPORT_MAX_MESSAGES = 5000
HISTORY_IMPORT_MAX_BYTES = 50 * 1024 * 1024
# Milliseconds since epoch; generous upper bound that still fits SQLite.
_MAX_TIMESTAMP_MS = 10**15


class HistoryImportFolder(BaseModel):
    id: str = Field(..., max_length=64)
    name: str | None = Field(None, max_length=200)
    createdAt: int | None = Field(None, ge=0, le=_MAX_TIMESTAMP_MS)
    collapsed: bool | None = None


class HistoryImportConversation(BaseModel):
    # Same bounds as ChatRequest.conversation_id, plus a safe charset since
    # the id becomes a thread_id / checkpoint key.
    conversationId: str = Field(..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str | None = Field(None, max_length=500)
    titleCustom: bool | None = None
    updatedAt: int | None = Field(None, ge=0, le=_MAX_TIMESTAMP_MS)
    pinned: bool | None = None
    folderId: str | None = Field(None, max_length=64)
    messages: list[Any] = Field(default_factory=list, max_length=HISTORY_IMPORT_MAX_MESSAGES)


class HistoryImportPayload(BaseModel):
    conversations: list[HistoryImportConversation] = Field(
        default_factory=list, max_length=HISTORY_IMPORT_MAX_CONVERSATIONS
    )
    folders: list[HistoryImportFolder] = Field(
        default_factory=list, max_length=HISTORY_IMPORT_MAX_FOLDERS
    )
