import json

from graph.state import RonaState
from toolbox import has_tool, requires_confirmation


def route_after_agent(state: RonaState) -> str:
    messages = state.get("messages") or []
    last = messages[-1] if messages else {}
    tool_calls = last.get("tool_calls") or []
    if not tool_calls:
        return "end"
    for tool_call in tool_calls:
        name = tool_call["function"]["name"]
        if not has_tool(name):
            continue
        try:
            args = json.loads(tool_call["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = None
        if requires_confirmation(name, args):
            return "confirm"
    return "tools"
