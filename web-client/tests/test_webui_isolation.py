import subprocess
import sys

FORBIDDEN_PREFIXES = (
    "app",
    "graph",
    "subagents",
    "trigger",
    "toolbox",
    "memory",
    "tavily",
    "google.genai",
    "googleapiclient",
    "deepl",
    "langgraph",
    "bs4",
    "openai",
)


def test_webui_modules_never_import_the_backend_package():
    script = (
        "import sys\n"
        "before = set(sys.modules)\n"
        "import webui.db\n"
        "import webui.logging_config\n"
        "import webui.proxy\n"
        "import webui.host\n"
        "import webui.server\n"
        "import webui.supervisor\n"
        "after = set(sys.modules)\n"
        "print(','.join(sorted(after - before)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=".",
    )
    new_modules = result.stdout.strip().split(",") if result.stdout.strip() else []
    forbidden = [
        module
        for module in new_modules
        if any(module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES)
    ]
    assert forbidden == []
    assert len(new_modules) > 0
