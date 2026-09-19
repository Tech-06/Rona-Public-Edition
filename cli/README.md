# rona-cli

Terminal management tool for a Rona installation: start/stop/status for the
backend and the web dashboard, editing model/auth/`.env` configuration,
managing scheduled tasks, and viewing execution history/logs -- from
anywhere on the machine.

This is a stdlib-only Python package on purpose -- it must keep working
right after a fresh install and must not import anything from the
`backend/` or `web-client/` packages (see `web-client/tests/
test_webui_isolation.py` for the sibling-isolation rule the whole project
follows). It talks to the backend purely over HTTP, the same way the web
dashboard does.

## Install

Normally you don't install this by hand -- the repository root's
`install.ps1`/`install.sh` do it as part of setting up the whole project
(see the main [README](../README.md)). To install just this package:

```bash
cd cli
python -m venv .venv
./.venv/Scripts/pip install -e .          # Windows
# ./.venv/bin/pip install -e .            # macOS/Linux
```

This registers a `rona` console script inside `cli/.venv`. Cross-platform
PATH integration (so `rona` works from any shell without activating that
venv) is added by the installer's `pathsetup.py`, not by this package
itself.

## Usage

```
rona [--root <path>] [--json] <command> ...
```

`--root` points at a Rona checkout (the folder containing `backend/` and
`web-client/`). It's optional -- `rona` looks for `RONA_HOME`, then
`~/.rona/config.json` (written by the installer), then walks upward from
its own install location and from the current directory looking for that
layout. `--json` switches any command to machine-readable output; both
flags work before or after the subcommand name.

### `rona status`

A combined snapshot: is the backend up (uptime, flash model, pro
configured, scheduler), is the web dashboard up (pid, uptime), and which
optional tool packages are installed.

### `rona server start|stop|restart|status`

Manages the backend process (port 8000), which has no supervisor of its
own. Prefers a systemd `--user` unit named `rona` when one is available
(same detection the web dashboard's own `/host/server` endpoint uses);
otherwise spawns/tracks `backend/run.py` itself via a pid file at
`backend/rona.pid`.

### `rona web start|stop|restart|status`

Delegates to the web dashboard's own `python -m webui start|stop|restart|
status` (port 8016), which already has its own lock file and health
polling.

### `rona edit model flash|pro|embedding [--name --url --key --headers --test]`

Views/edits the model tier settings in `backend/.env` directly -- no
running backend needed. Run with no flags for an interactive prompt (shows
the current value, masked for the key; blank keeps it; `s` skips the whole
block). `--test` verifies the values with a real provider API call before
saving; on failure you're offered try-again / save-anyway / skip. `--url`/
`--headers` don't apply to `embedding` (it's Google-API-key + model name
only).

```bash
rona edit model flash --name deepseek-flash --url https://api.example.com --key sk-... --test
rona edit model embedding --test
```

### `rona edit auth get|reset|set`

The shared `AUTH_TOKEN` that `backend/.env` and `web-client/.env` must
hold identically. `get` shows it (masked unless `--show`); `reset`
generates a new random one; `set <token>` sets a specific value -- both
always write to **both** `.env` files.

### `rona edit env [--web]`

Opens `backend/.env` (or `web-client/.env` with `--web`) in `$EDITOR`/
`$VISUAL`, falling back to a per-OS default (`notepad` / `open -t` /
`nano`).

### `rona edit memory search|add|edit|delete|stats`

A thin CLI over the backend's `/api/data/memories*` endpoints. Needs a
running, reachable backend.

```bash
rona edit memory search "coffee" --limit 5
rona edit memory add "loves tea" --layer short
rona edit memory stats
```

### `rona task list|del|toggle`

Over the backend's `/api/tasks*` endpoints. `toggle` flips a task between
`active`/`passive` through the API (not sqlite directly), since that's
also what (un)registers it with the live scheduler.

### `rona log list|show|del`

Combined execution history -- scheduled-task runs and subagent runs,
merged and sorted by recency -- over `/api/runs*`. `del` only works on a
run that's already been reported to the user (409 otherwise).

### `rona log tail [--level --grep]`

Follows the live text log. Consumes the backend's `GET /api/logs` SSE
stream when it's reachable; falls back to polling `backend/rona.log`
directly when the backend is down.

## Module layout

- **`paths.py`** — installation-root resolution and per-component paths.
- **`envio.py`** — independent stdlib copy of `backend/toolbox/envfile.py`'s
  safe `.env` read/write (in-place replace, `.bak` backup, atomic write).
- **`http.py`** — a small urllib-based JSON client, plus SSE line
  streaming for `log tail`.
- **`procutil.py`** — cross-platform process helpers (spawn detached, pid
  file, kill tree, port probing) used by `commands/server.py`.
- **`backend_client.py`** — shared helper for commands that need a
  running backend (raises a clear error naming `rona server start` if it
  isn't reachable).
- **`providers.py`** — a real connectivity check directly against an LLM
  provider or the Gemini embedding API, bypassing the backend entirely;
  used by both `rona edit model --test` and the installer's wizard.
- **`ui.py`** — small print helpers (colored when the output is a TTY).
- **`commands/`** — one module per top-level command (`status.py`,
  `server.py`, `web.py`, `task.py`, `log.py`), plus an `edit/` subpackage
  (`model.py`, `auth.py`, `env.py`, `memory.py`).

## Tests

```bash
cd cli
pip install -r requirements-dev.txt
./.venv/Scripts/python -m pytest     # Windows
# ./.venv/bin/python -m pytest       # macOS/Linux
```
