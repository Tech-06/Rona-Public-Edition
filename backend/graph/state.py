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


def trim_messages(
    messages: list[dict[str, Any]], max_messages: int
) -> list[dict[str, Any]]:
    if max_messages <= 0 or len(messages) <= max_messages:
        return messages
    start = len(messages) - max_messages
    for index in range(start, len(messages)):
        if messages[index].get("role") == "user":
            return messages[index:]
    return messages[start:]
