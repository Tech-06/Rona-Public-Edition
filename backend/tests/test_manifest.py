import json
from pathlib import Path

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "toolbox" / "tools.json"


def _load_raw_tools() -> list[dict]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data["tools"]


def test_no_duplicate_tool_names():
    names = [tool["name"] for tool in _load_raw_tools()]
    assert len(names) == len(set(names)), "duplicate tool name in manifest"


def test_conditional_confirmation_param_exists_in_schema():
    for tool in _load_raw_tools():
        rule = tool.get("requires_confirmation")
        if isinstance(rule, dict):
            properties = tool.get("parameters", {}).get("properties", {})
            assert rule["param"] in properties, (
                f"{tool['name']}: requires_confirmation references unknown "
                f"parameter {rule['param']!r}"
            )


def test_background_tools_never_require_confirmation():
    for tool in _load_raw_tools():
        if tool.get("background") is True:
            assert tool["requires_confirmation"] is False, (
                f"{tool['name']}: a background (autonomous-agent) tool cannot "
                "carry a requires_confirmation rule -- approval dialogs are "
                "impossible outside a live chat"
            )


def test_add_and_edit_memory_no_longer_require_confirmation():
    import toolbox

    assert not toolbox.requires_confirmation(
        "add_memory", {"layer": "deep", "content": "x"}
    )
    assert not toolbox.requires_confirmation(
        "edit_memory", {"memory_id": 1, "layer": "deep"}
    )
    assert toolbox.requires_confirmation("delete_memory", {"memory_id": 1})
    assert toolbox.requires_confirmation("delete_person", {"person_id": 1})


def test_registry_loads_every_manifest_tool():
    import toolbox

    specs = toolbox.iter_specs()
    raw = _load_raw_tools()
    assert len(specs) == len(raw)
    for spec in specs:
        assert toolbox.has_tool(spec.name)
        toolbox.get_tool(spec.name)  # must resolve without raising
