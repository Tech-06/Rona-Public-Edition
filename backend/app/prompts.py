from app import prompt_store

PROMPTS_DIR = prompt_store.PROMPTS_DIR

PROMPT_FILES = [prompt_store.spec(prompt_id).filename for prompt_id in prompt_store.MAIN_PROMPT_IDS]

# Kept for backwards compatibility -- tests/test_i18n.py imports
# `_substitute_placeholders` directly, and `_PLACEHOLDERS` used to be the
# canonical home of these lambdas before they moved to prompt_store.py so
# the new prompt-editing API (app/prompts_api.py) could share them too.
_PLACEHOLDERS = prompt_store.PLACEHOLDERS
_substitute_placeholders = prompt_store.substitute_placeholders


def load_prompts() -> list[dict[str, str]]:
    messages = []
    for prompt_id in prompt_store.MAIN_PROMPT_IDS:
        content = prompt_store.load_rendered(prompt_id)
        if content:
            messages.append({"role": "system", "content": content})
    return messages
