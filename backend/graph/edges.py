from graph.nodes import call_needs_confirmation
from graph.state import RonaState


def route_after_agent(state: RonaState) -> str:
    messages = state.get("messages") or []
    last = messages[-1] if messages else {}
    tool_calls = last.get("tool_calls") or []
    if not tool_calls:
        return "end"
    if any(call_needs_confirmation(tool_call, state) for tool_call in tool_calls):
        return "confirm"
    return "tools"
