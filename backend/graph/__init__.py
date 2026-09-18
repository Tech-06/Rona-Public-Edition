from langgraph.graph import END, START, StateGraph

from graph.conversations import touch
from graph.edges import route_after_agent
from graph.nodes import (
    agent_node,
    ask_confirmation_node,
    await_confirmation_node,
    tools_node,
)
from graph.state import RonaState
from graph.threads import get_lock, purge_expired
from toolbox.db import DB_PATH

CHECKPOINT_DB_PATH = DB_PATH.parent / "rona_checkpoints.db"

__all__ = [
    "CHECKPOINT_DB_PATH",
    "build_graph",
    "get_lock",
    "purge_expired",
    "touch",
]


def build_graph(checkpointer):
    builder = StateGraph(RonaState)
    builder.add_node("agent", agent_node)
    builder.add_node("ask_confirmation", ask_confirmation_node)
    builder.add_node("await_confirmation", await_confirmation_node)
    builder.add_node("tools", tools_node)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        route_after_agent,
        {"end": END, "confirm": "ask_confirmation", "tools": "tools"},
    )
    builder.add_edge("ask_confirmation", "await_confirmation")
    builder.add_edge("await_confirmation", "tools")
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)
