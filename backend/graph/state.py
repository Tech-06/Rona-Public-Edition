from typing import Annotated, Any, TypedDict

REPLACE_MESSAGES_KEY = "__replace_messages__"


def replace_messages(value: list[dict[str, Any]]) -> dict[str, Any]:
    return {REPLACE_MESSAGES_KEY: value}


def rona_messages_reducer(
    left: list[dict[str, Any]], right: Any
) -> list[dict[str, Any]]:
    if isinstance(right, dict) and REPLACE_MESSAGES_KEY in right:
        return right[REPLACE_MESSAGES_KEY]
    if isinstance(right, dict):
        right = [right]
    return [*left, *right]


class RonaState(TypedDict):
    messages: Annotated[list[dict[str, Any]], rona_messages_reducer]
    pending_confirmation: dict[str, Any] | None
    confirmation: dict[str, Any] | None
    # True once the current user turn has read untrusted content (web pages,
    # emails...); reset when a new user message starts the next turn.
    tainted: bool


def drop_leading_orphans(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop leading messages an OpenAI-compatible API would reject: a ``tool``
    result without its assistant call, or an assistant ``tool_calls`` message
    whose results are not all present right after it."""
    start = 0
    while start < len(messages):
        message = messages[start]
        role = message.get("role")
        if role == "tool":
            start += 1
            continue
        if role == "assistant" and message.get("tool_calls"):
            wanted = {call.get("id") for call in message["tool_calls"]}
            found = set()
            for later in messages[start + 1:]:
                if later.get("role") != "tool":
                    break
                found.add(later.get("tool_call_id"))
            if not wanted <= found:
                start += 1
                continue
        break
    return messages[start:]


def trim_messages(
    messages: list[dict[str, Any]], max_messages: int
) -> list[dict[str, Any]]:
    """Keep roughly the last ``max_messages`` messages, cutting only at a turn
    boundary (a user message) so a tool result never lands first and the
    current turn is never split. A single turn longer than the limit is kept
    whole -- losing the user's question mid tool loop is worse than going over."""
    if max_messages <= 0 or len(messages) <= max_messages:
        return messages
    start = len(messages) - max_messages
    for index in range(start, len(messages)):
        if messages[index].get("role") == "user":
            return messages[index:]
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            return messages[index:]
    # No user message anywhere: tail only, minus anything left dangling.
    return drop_leading_orphans(messages[start:])
