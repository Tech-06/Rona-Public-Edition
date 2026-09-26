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
polling. `status` (and a successful `start`/`restart`) also warns if the
compiled frontend is older than its source -- see `rona web build` below.

### `rona web build`

Compiles the frontend (`npm ci`/`install` + `npm run build` in
`web-client/frontend`, mirroring what the installer does on first install).
Needed after a `git pull`: `web-client/webui/dist` is a gitignored build
artifact, so pulling updates the frontend's source but not what a browser
actually gets served -- the dashboard detects that mismatch itself (via
`/host/healthz`'s `frontend_stale` field) and `rona web status` surfaces it
as a warning naming this command. A running panel picks up the rebuilt
`index.html` on its own, no restart needed for the frontend half; if the
backend or the dashboard's own Python code also changed, follow up with
`rona server restart && rona web restart`.

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
`nano`). `$VISUAL`/`$EDITOR` can be a whole command line, not just a bare
executable name -- something like `code --wait` or `subl -w` works, since
the value is split into an argv the same way a shell would rather than
treated as a single program path.

### `rona edit memory search|add|edit|delete|list|archive|archived|restore|purge|stats`

A thin CLI over the backend's `/api/data/memories*` and `/api/data/archive*`
endpoints. Needs a running, reachable backend. `list` shows each memory's
layer, its access count in the current layer vs. lifetime, and when it was
last recalled (web and CLI searches never count as a recall -- only the
model's own `search_memories` tool calls do); `archive`/`restore` move a
memory to/from the archive by hand (archiving is reversible, so it isn't
confirmed); `archived` lists the archive, and `purge` deletes an archived
record for good (confirmed, like `delete`). `stats` also reports the
archive's size and the last consolidation run, when the backend supports it.

```bash
rona edit memory search "coffee" --limit 5
rona edit memory add "loves tea" --layer short
rona edit memory list --layer short --person all
rona edit memory archive 42
rona edit memory archived
rona edit memory restore 7          # comes back as a deep memory
rona edit memory purge 7 --yes
rona edit memory stats
```

### `rona edit memory consolidate run|status|config`

Manages the memory consolidation engine -- the background job that
promotes often-recalled memories to a longer-lived layer, archives
seasonal memories nobody has recalled in a long time, and deletes
rarely-recalled short ones. `run` triggers a pass immediately (`--dry-run`
previews it -- exact same logic, nothing is written) over
`/api/memory/consolidation/run`, and needs a reachable backend, same as
`status`, which shows the scheduler's state, the active policy and the
last few runs. `config` is different: it reads/writes `MEMORY_*` keys in
`backend/.env` directly, exactly like `rona edit model`, so it works even
before the backend has ever been started; changing it needs
`rona server restart` to take effect.

```bash
rona edit memory consolidate run --dry-run
rona edit memory consolidate status
rona edit memory consolidate config                              # show current settings
rona edit memory consolidate config --short-promote-hits 5 --auto-delete off
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

### `rona edit prompt list|show|edit|reset`

A thin CLI over the backend's `/api/prompts*` endpoints -- the same nine
identity/behavior prompt files (`persona`, `output_text`, `user`, `toolbox`,
`memory`, `subagents`, `trigger`, plus the `subagent_worker`/`trigger_worker`
prompts background jobs run with) that the dashboard's Prompts panel edits.
Needs a running, reachable backend, same as `rona edit memory`; `edit` also
needs a text editor (or `--file`), since these are multi-line Markdown, not
single values.

`list` shows each prompt's id and group, plus whether it's customized or the
underlying default has changed since you customized it. `show <id>` prints
the effective content (`--default` prints the shipped one instead, ignoring
any override). `edit <id> [--file PATH]` writes the current content to a
temp file (or reads `--file` if one was given), opens it in `$VISUAL`/
`$EDITOR` and waits for it to close, then saves back only if something
actually changed. A stale version (someone else saved it in the meantime)
or a validation error (a required placeholder like
`{{PRIMARY_LANGUAGE_RULE}}` removed, an empty worker prompt) is reported
without discarding your edit -- the draft file's path is printed so nothing
is lost. `reset <id> [--yes]` deletes the customization and reverts to the
shipped default.

```bash
rona edit prompt list
rona edit prompt show trigger_worker --default
rona edit prompt edit user
rona edit prompt reset persona --yes
```

A customization is written to `backend/prompts/custom/<filename>`, which
git never tracks, so a `git pull` can never revert or conflict with it; a
saved change takes effect on the very next message or task run, no restart
needed.

### `rona tools list|available|install|update|uninstall|verify|config|actions|run`

A thin wrapper over the backend's own `toolbox.manager`, delegating to the
backend's venv python exactly the way `rona web` delegates to
`python -m webui` -- this command never imports anything from `toolbox/`
itself, so the CLI stays stdlib-only and keeps working even without the
backend installed.

`list`/`available`/`verify`/`actions`, and `config` without `--edit`, run the
manager with `--json`, captured, and are re-printed through this CLI's own
table (or passed straight through if `rona` itself was given `--json`).
`install`/`update`/`uninstall`/`run`, and `config --edit`, inherit stdio
instead, since a package's own config prompts (an API key read via
`getpass`, the health-check retry/keep/cancel choice), the dependency
confirmation and an action's input round trips all need a live terminal.

```bash
rona tools available                 # every package in the catalog
rona tools install web_search        # prompts for its Tavily API key
rona tools list                      # installed packages
rona tools verify web_search
rona tools update web_search         # pulls in a newer catalog version
rona tools uninstall web_search
```

`available` also prints what a package will drag in with it -- but only when
the catalog actually publishes that metadata, since an older index saying
nothing about dependencies is not the same as a package having none. A
`requires` entry can also carry a version constraint (`google_auth>=2.0`,
`x~=2.1`, and so on); when an installed dependency no longer satisfies one,
`available` marks it `installed 1.0.0 -> 1.1.0 available` and prints a hint
to run `rona tools update <package>` once the table is done. `install` then
surfaces the manager's own confirmation before anything is downloaded, and
so does `update`, described next.

### `rona tools update <id> [--source --set --yes --keep-on-health-failure --defer-config]`

Upgrades an installed package to whatever the catalog currently offers,
through the same plan → confirm → install machinery as `rona tools install`
(same flags, same interactive dependency confirmation unless `--yes`). A
dependency that's too old to satisfy the package's `requires` is upgraded
first, automatically, as part of the same plan; running `update` when
nothing is newer just reports "up to date" rather than doing anything.
Preserved across the update: `.env` values, `custom/<id>/config.json`, any
file written through a `file`-typed config field, and anything matching the
package's `user_data_globs` -- and if anything goes wrong, including the
new version simply failing to load, the previous version is restored
automatically. `--keep-on-health-failure` (implied by `--yes`) keeps a
successful upgrade even if its post-install health check then fails,
instead of rolling it back. `--defer-config` (also accepted by `install`)
skips asking for newly-required configuration and leaves the package to be
configured afterwards with `rona tools config <id>` -- this is what the
dashboard's Catalog tab relies on, since a long-running install has no
terminal to prompt. Only one install/update/uninstall runs at a time across
the whole machine, CLI and dashboard alike; a second one is rejected rather
than left to race the first.

```bash
rona tools update get_time --yes
rona tools update google_calendar --defer-config
```

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
  subpackage (`model.py`, `auth.py`, `env.py`, `memory.py`,
  `memory_consolidate.py`, `lang.py`, `prompt.py`). `memory_consolidate.py`
  holds the `consolidate run|status|config` subgroup that `memory.py`'s
  `register()` wires in; `prompt.py` is `rona edit prompt`.

## Tests

```bash
cd cli
pip install -r requirements-dev.txt
./.venv/Scripts/python -m pytest     # Windows
# ./.venv/bin/python -m pytest       # macOS/Linux
```
