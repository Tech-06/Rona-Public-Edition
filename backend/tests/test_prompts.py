"""Tests for the prompt file order and content added by the memory
guidance prompt: `app/prompts.py`'s `PROMPT_FILES` list, and the split
between `prompts/toolbox.md` (tool-usage behavior) and the new
`prompts/memory.md` (layer/recall rules moved out of toolbox.md).
"""

from app.prompts import PROMPT_FILES, PROMPTS_DIR, load_prompts


def test_memory_prompt_immediately_follows_toolbox_prompt():
    assert "toolbox.md" in PROMPT_FILES
    assert "memory.md" in PROMPT_FILES
    toolbox_index = PROMPT_FILES.index("toolbox.md")
    assert PROMPT_FILES[toolbox_index + 1] == "memory.md"


def test_memory_prompt_file_exists():
    assert (PROMPTS_DIR / "memory.md").is_file()


def test_toolbox_prompt_no_longer_mentions_conservative_deep():
    content = (PROMPTS_DIR / "toolbox.md").read_text(encoding="utf-8")
    assert "conservative with layer 'deep'" not in content


def test_memory_prompt_has_bilingual_layer_examples():
    content = (PROMPTS_DIR / "memory.md").read_text(encoding="utf-8")
    assert "bu akşam" in content
    assert "bu dönem" in content


def test_assembled_prompts_include_memory_guidance_heading():
    messages = load_prompts()
    combined = "\n".join(message["content"] for message in messages)
    assert "# Memory Guidance" in combined
