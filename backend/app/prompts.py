from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

PROMPT_FILES = [
    "persona.md",
    "output_text.md",
    "user.md",
    "toolbox.md",
    "subagents.md",
    "trigger.md",
]


def load_prompts() -> list[dict[str, str]]:
    messages = []
    for name in PROMPT_FILES:
        path = PROMPTS_DIR / name
        if path.is_file():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                messages.append({"role": "system", "content": content})
    return messages
