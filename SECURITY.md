# Security Policy

## Supported versions

Only the latest commit on the `main` branch is supported. Fixes are made on
`main`; there are no maintained release branches.

## Reporting a vulnerability

Please report vulnerabilities privately, not in a public issue or pull request.

Use GitHub's private vulnerability reporting: open the repository's **Security**
tab at <https://github.com/Tech-06/Rona-Public-Edition/security> and choose
**Report a vulnerability** (a private security advisory). Include what you
found, how to reproduce it, the commit you tested and the impact you expect.

Reports are handled on a best-effort basis by a single maintainer. Please allow
reasonable time for a fix before disclosing publicly.

## Threat model (in brief)

Rona is a single-user, self-hosted assistant. It is designed to run on a machine
you control and to be reached only by you.

- **Backend.** Listens on `127.0.0.1` by default. Every endpoint needs the
  `AUTH_TOKEN` bearer token (at least 32 characters). Optional TLS via
  `SSL_CERTFILE` / `SSL_KEYFILE`.
- **Web dashboard.** Requires a password login (`rona web password`) and issues
  a signed, HttpOnly, SameSite=Strict session cookie. Everything that reaches
  the backend or controls the host (`/api/*`, `/chat*`, `/health`, `/host/*`,
  except `/host/healthz`) needs a session. Failed logins are rate-limited, and
  the dashboard refuses to start on a non-loopback `WEB_HOST` without a
  password. It sets a Content-Security-Policy and other security headers.
- **Shared secrets.** The dashboard holds the backend's `AUTH_TOKEN` and proxies
  requests with it, so a logged-in dashboard user controls the whole backend.
  Anyone with shell access as the same OS user can read the `.env` files
  (tokens, password hash, session secret). That is out of scope: the host is
  trusted.
- **Tool packages.** Optional packages from the Rona Tools catalog run inside
  the backend process with its full privileges, and `pip`-install their
  declared dependencies. Installing a package is equivalent to running its code.
  Install only catalogs you trust and pin them (`--source github:owner/repo@<sha>`,
  or `sha256` / `commit` pins in the catalog index).
- **Prompt injection.** Output of tools that return third-party text (web pages,
  emails, calendar entries, contacts) is fenced in `<untrusted_data>` and the
  model is instructed to treat it as data. Once a turn or run has read such
  content, tool calls that could leak data or persist attacker-chosen content
  need approval, and are refused in unattended runs (scheduled tasks,
  sub-agents). Sensitive actions (sending email, deleting data) always ask for
  confirmation. These are mitigations: a model can still be manipulated, so do
  not give Rona access to data or accounts you cannot afford to expose.

## Hardening checklist

- Keep `HOST=127.0.0.1` for the backend and `WEB_HOST=127.0.0.1` for the
  dashboard unless you need remote access.
- For remote access use an authenticated channel: Tailscale/WireGuard, or a
  reverse proxy with TLS plus an authentication layer (Caddy `forward_auth` +
  Authelia/Authentik, Cloudflare Access). A plain tunnel is acceptable only with
  the dashboard password and HTTPS.
- Behind a proxy, set `WEB_ALLOWED_HOSTS` to your real hostname and
  `WEB_COOKIE_SECURE=true` (the default `auto` also detects HTTPS and
  `X-Forwarded-Proto`).
- Set a strong dashboard password with `rona web password`; changing it signs
  out all existing sessions.
- Rotate the shared token with `rona edit auth reset` if it may have leaked
  (it updates both `.env` files); also revoke and recreate any leaked provider
  API keys.
- Keep the `.env` files private (Rona writes them with mode `0600` where the OS
  supports it), run Rona as a dedicated unprivileged user, and use a restrictive
  `umask` (e.g. `077`). Do not commit `.env` files or `rona.db`.
- Keep tool packages pinned to a reviewed commit or release, review catalog
  updates before installing, and uninstall packages you no longer use
  (`rona tools uninstall <id> --purge` also removes their `.env` keys and tables).
- Keep dependencies updated (the repository uses Dependabot) and re-run
  `rona web build` / restart services after `git pull`.
