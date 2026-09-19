# rona-cli

Terminal management tool for a Rona installation: start/stop/status for the
backend and the web dashboard, from anywhere on the machine.

This is a stdlib-only Python package on purpose -- it must keep working
right after a fresh install and must not import anything from the
`backend/` or `web-client/` packages (see `web-client/tests/
test_webui_isolation.py` for the sibling-isolation rule the whole project
follows).

## Install (development)

```bash
cd cli
python -m venv .venv
./.venv/Scripts/pip install -e .          # Windows
# ./.venv/bin/pip install -e .            # macOS/Linux
```

This registers a `rona` console script inside `cli/.venv`. Cross-platform
PATH integration (so `rona` works from any shell without activating that
venv) is added by the installer, not by this package itself.

## Usage

```
rona [--root <path>] [--json] <command> ...
```

`--root` points at a Rona checkout (the folder containing `backend/` and
`web-client/`). It's optional -- `rona` looks for `RONA_HOME`, then
`~/.rona/config.json` (written by the installer), then walks upward from
its own install location and from the current directory looking for that
layout. `--json` switches every command to machine-readable output.

### Implemented so far

```
rona status                  # combined snapshot: backend, web, installed tool packages
rona server start|stop|restart|status   # backend process (port 8000)
rona web    start|stop|restart|status   # web dashboard (port 8016)
```

`rona server` prefers a systemd `--user` unit named `rona` when one is
available (same detection the web dashboard's own `/host/server` endpoint
uses); otherwise it spawns/tracks `backend/run.py` itself via a pid file at
`backend/rona.pid`. `rona web` delegates to the web dashboard's own
`python -m webui start|stop|restart|status`, which already has its own
lock file and health polling.

More command groups (`edit`, `task`, `log`) land in a later phase.

## Tests

```bash
./.venv/Scripts/python -m pytest
```
