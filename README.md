# Transaction Aggregator

A private, single-owner, local-first web app for searching credit-card
transactions across Capital One, Chase, Citi, and Wells Fargo from one search
box. Connections go through Plaid; transactions are cached in local SQLite, so
search never calls a bank and keeps working offline.

One search field sits above a grid of card panels. Searching `Paze` returns
every match while keeping the results grouped card by card.

## Run it (demo bank, no credentials needed)

```bash
make install
```

```bash
make keys
```

Copy `.env.example` to `backend/.env`, paste in the two generated secrets, and
leave `ENVIRONMENT=demo`.

```bash
make migrate
```

```bash
make owner EMAIL=you@example.com
```

```bash
make serve
```

Open http://127.0.0.1:8000 and sign in. `ENVIRONMENT=demo` runs a
deterministic in-process fixture bank — four institutions, eight credit cards,
and ten `Paze` transactions — so the whole flow works without a Plaid account
and without touching the network.

## Run it against real Plaid

Set `ENVIRONMENT=sandbox` to exercise the real Plaid API without spending
anything, or `ENVIRONMENT=production` to connect actual bank accounts. Both
need your Plaid `PLAID_CLIENT_ID`/`PLAID_SECRET` in `backend/.env`; production
additionally requires a stable HTTPS URL in `PUBLIC_BASE_URL`, with
`{PUBLIC_BASE_URL}/oauth-return` registered as the OAuth redirect URI in the
Plaid dashboard. [docs/operations.md](docs/operations.md) covers the tunnel
setup, key rotation, backups, and the full troubleshooting table.

```bash
make serve
```

**Open the HTTPS URL from `PUBLIC_BASE_URL` — not `http://127.0.0.1:8000`.**
Whenever `PUBLIC_BASE_URL` is `https://`, the session cookie is marked `Secure`,
and a browser will not store or return a `Secure` cookie over plain HTTP: you
will appear signed out immediately after a successful sign-in. In `production`
the CSRF origin allowlist also narrows to exactly `PUBLIC_BASE_URL` — the
`localhost:5173` exceptions apply only to `demo`, `sandbox`, and `test` — so
requests from any other origin come back as `403 ORIGIN_INVALID`. `make serve`
builds the frontend and serves it from the backend's own origin for this
reason; don't put `make dev` (Vite on `:5173`) in front of a production API.

Two things to know before connecting a real bank:

- **Plaid's Trial plan allows 10 production Items, cumulatively.** Removing a
  connection does not give the slot back, and a connection that fails after the
  Item was created still consumes one. The app keeps tombstone rows so its
  count stays honest with Plaid's; `GET /api/connections` reports
  `production_item_count` against the limit.
- **`backend/.env` and `backend/data/` are gitignored**, so they do not travel
  with a branch, merge, or worktree. Moving your setup somewhere else means
  copying those two by hand — the encryption key in `.env` is what decrypts the
  stored Plaid access tokens, so a mismatched key silently invalidates every
  existing connection.

## Other commands

```bash
make check
```

Runs the backend suite, the frontend suite, TypeScript, and the production
build. `make dev` runs the Vite dev server against a separately running API;
`make e2e` runs the Playwright flows.

```bash
make sync
```

Reinstalls dependencies and applies migrations. Run it after pulling a merged
branch — stale `node_modules` or an un-migrated schema will otherwise surface
as a confusing `make serve` failure. It does not touch `backend/.env` or
`backend/data/`.

## Layout

- `backend/` — FastAPI, SQLAlchemy 2, Alembic, SQLite in WAL mode with an FTS5
  trigram index; owns authentication, encrypted Plaid tokens, the durable sync
  job worker, and webhooks.
- `frontend/` — React 19, Vite, TanStack Query and Virtual, `react-plaid-link`.
- `docs/PRD.md` — requirements. `docs/operations.md` — setup and runbook.

## Security posture

Bank credentials are only ever entered in bank- or Plaid-hosted screens. Plaid
access tokens are encrypted with AES-256-GCM under a key held outside the
database and bound to the row that owns them. Passwords use Argon2id; session
tokens are stored only as SHA-256 hashes. The database and its directory are
owner-readable only, and logs redact credentials, tokens, and transaction text.
Full-disk encryption on the host is a prerequisite, not a suggestion.
