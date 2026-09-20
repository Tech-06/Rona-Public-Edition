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

### `rona edit lang [tr|en] [--backend --web --cli]`

Shows or sets the language of all three installed components. With no
target flags, a language argument changes all three at once (backend
`LANGUAGE` in `backend/.env`, web dashboard `UI_LANGUAGE` in
`web-client/.env`, and this CLI's own `language` field in
`~/.rona/config.json`); with no language argument at all, it just prints
each one's current value. `--backend`/`--web`/`--cli` restrict a change to
specific targets. Only writes to files/components that are actually part
of this install; existing fields in `~/.rona/config.json` are preserved.

```bash
rona edit lang              # show current language of all three
rona edit lang en           # switch all three to English
rona edit lang tr --backend --web   # only the backend and web dashboard
```

### `rona tools list|available|install|uninstall|verify|config|actions|run`

A thin wrapper over the backend's own `toolbox.manager`, delegating to the
backend's venv python exactly the way `rona web` delegates to
`python -m webui` -- this command never imports anything from `toolbox/`
itself, so the CLI stays stdlib-only and keeps working even without the
backend installed.

`list`/`available`/`verify`/`actions`, and `config` without `--edit`, run the
manager with `--json`, captured, and are re-printed through this CLI's own
table (or passed straight through if `rona` itself was given `--json`).
`install`/`uninstall`/`run`, and `config --edit`, inherit stdio instead, since
a package's own config prompts (an API key read via `getpass`, the
health-check retry/keep/cancel choice), the dependency confirmation and an
action's input round trips all need a live terminal.

```bash
rona tools available                 # every package in the catalog
rona tools install web_search        # prompts for its Tavily API key
rona tools list                      # installed packages
rona tools verify web_search
rona tools uninstall web_search
```

`available` also prints what a package will drag in with it -- but only when
the catalog actually publishes that metadata, since an older index saying
nothing about dependencies is not the same as a package having none.
`install` then surfaces the manager's own confirmation before anything is
downloaded.

### `rona tools config <id> [--set key=value] [--edit]`

Shows or changes an installed package's configuration, going through the same
`.env` / `config.json` / copied-file paths the installer uses. With no flags it
prints the current values; a secret is never sent back from the manager, so it
shows only as set or not set. `--set` changes individual values; `--edit` walks
every field on the terminal (blank keeps the current value, secrets read
through `getpass`) and so runs with inherited stdio rather than captured.

```bash
rona tools config google_calendar
rona tools config google_calendar --set accounts=personal,work
rona tools config google_auth --edit
```

### `rona tools actions <id>` and `rona tools run <id> <action>`

Actions are the operations a package exposes to *you* rather than to the
model: authorizing a Google account, listing or revoking those
authorizations. `actions` lists them (with their parameters, and whether one
is irreversible); `run` runs one.

`run` always inherits stdio. An action may answer "input_required" -- needing
something it can only ask for now, like the address a browser was redirected
to -- and the link it prints has to reach you unmangled. Actions a package
marks terminal-only never appear in the dashboard, only here.

```bash
rona tools actions google_auth
rona tools run google_auth add_account           # prompts for the account name
rona tools run google_auth list_accounts
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
- **`i18n.py`** + **`locales/{tr,en}.py`** — this CLI's own language
  catalog. The active language is resolved once, before the argparse
  parser is built (so help text comes out in the right language), from
  `RONA_LANG` or the `language` field in `~/.rona/config.json`, falling
  back to `tr`.
- **`commands/`** — one module per top-level command (`status.py`,
  `server.py`, `web.py`, `task.py`, `log.py`, `tools.py`), plus an `edit/`
  subpackage (`model.py`, `auth.py`, `env.py`, `memory.py`, `lang.py`).

## Tests

```bash
cd cli
pip install -r requirements-dev.txt
./.venv/Scripts/python -m pytest     # Windows
# ./.venv/bin/python -m pytest       # macOS/Linux
```
