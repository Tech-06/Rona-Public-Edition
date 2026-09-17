from subagents.runner import _allowed_tool_names
from toolbox.registry import background_tool_names
from trigger.executor import _free_tool_names

TRIGGER_TOOL_NAMES = {
    "create_task",
    "list_tasks",
    "get_task",
    "update_task",
    "delete_task",
    "get_task_run",
    "dismiss_task_run",
}

SUBAGENT_TOOL_NAMES = {
    "start_subagent",
    "list_subagents",
    "get_subagent_report",
    "dismiss_subagent_report",
}


def test_background_set_is_nonempty():
    assert len(background_tool_names()) > 0


def test_subagent_and_trigger_derive_from_the_same_background_set():
    # Both used to maintain their own hand-written exclusion list; a drift
    # between the two let subagents reach trigger tools (get_task_run,
    # dismiss_task_run) and silently mark scheduled-task notifications as
    # delivered. Both must now come from the single manifest-driven source.
    assert _allowed_tool_names() == background_tool_names()
    assert _free_tool_names() == background_tool_names()


def test_background_set_excludes_trigger_and_subagent_tools():
    bg = background_tool_names()
    assert bg.isdisjoint(TRIGGER_TOOL_NAMES)
    assert bg.isdisjoint(SUBAGENT_TOOL_NAMES)
