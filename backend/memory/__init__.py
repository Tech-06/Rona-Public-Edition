"""Memory Consolidation ("Konsolidasyon"): lifecycle management for Rona's
built-in long-term memory (`rona.db` -> `memories`).

This package owns:

- The layer lifecycle: promotion between `short` -> `seasonal` -> `deep`
  by recall count, seasonal archiving after a long idle period, and
  deletion of rarely-recalled short-layer memories. `deep` memories are
  never touched automatically.
- Access tracking: counting how often a memory is actually recalled by
  Rona's own `search_memories` tool (never web/CLI lookups), so promotion
  and archiving decisions are based on real usage.
- The archive: a separate table (`memory_archive`) that manually- or
  auto-archived memories move into, with a path back to `deep`.

Modules: `clock` (UTC time helpers), `schema` (DDL + self-healing
migration, mirroring `graph/conversations.py`'s pattern), `policy` (the
`MemoryPolicy` read from `Settings`), `access` (recall counting),
`archive`, `runs` (consolidation run log), `consolidation` (the engine)
and `scheduler` (the periodic background run).

Import rule (critical -- keep this true for every module added here): no module in `backend/memory/` may import
`toolbox`, `app`, `graph`, `trigger` or `subagents` at module level.
Allowed at module level: the standard library, `i18n` (which itself only
imports `locales` at module level and reads settings lazily), and other
`memory.*` modules. Database access goes through `memory.schema.connect()`
/ `connect_if_exists()`, which import `toolbox.db` *inside* the function
body and use `db.DB_PATH` / `db.connect()` at call time -- this is also
why tests that monkeypatch `toolbox.db.DB_PATH` keep working. Settings
are likewise read inside functions via `from app.config import
get_settings`, never at module level.

The reason is a real import cycle, not just a style preference:
`toolbox/__init__.py` eagerly loads the tool registry, and
`toolbox/tools/mem_tool.py` imports `memory.*`. If any `memory.*`
module imported `toolbox` (or `app`, which `toolbox`'s registry already
pulls in via `subagent_tools.py`/`trigger_tools.py`) at module level,
`toolbox/__init__` -> `mem_tool` -> `memory.*` -> `toolbox` would be a
circular import.
"""
