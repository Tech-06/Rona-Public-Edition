from pathlib import Path

import i18n

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

PROMPT_FILES = [
    "persona.md",
    "output_text.md",
    "user.md",
    "toolbox.md",
    "memory.md",
    "subagents.md",
    "trigger.md",
]

# {{...}} placeholders substituted into prompt files at load time, so the
# handful of spots that genuinely depend on LANGUAGE (persona.md's "speak
# X" directive, trigger.md's worked example) don't require a whole second
# copy of every prompt file -- everything else in these files is
# instructions *to the model*, not shown to the user, and is deliberately
# left as plain English prose regardless of LANGUAGE (see the language
# plan's rationale).
_PLACEHOLDERS = {
    "PRIMARY_LANGUAGE_RULE": lambda: i18n.t("prompt.primary_language_rule"),
    "EXAMPLE_GREETING": lambda: i18n.t("prompt.example_greeting"),
}


def _substitute_placeholders(content: str) -> str:
    for name, resolve in _PLACEHOLDERS.items():
        content = content.replace("{{" + name + "}}", resolve())
    return content


def load_prompts() -> list[dict[str, str]]:
    messages = []
    for name in PROMPT_FILES:
        path = PROMPTS_DIR / name
        if path.is_file():
            content = _substitute_placeholders(path.read_text(encoding="utf-8").strip())
            if content:
                messages.append({"role": "system", "content": content})
    return messages
