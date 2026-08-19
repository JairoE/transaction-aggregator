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

To connect real banks, set `ENVIRONMENT=sandbox` (or `production`) with your
Plaid credentials and a stable HTTPS URL. See [docs/operations.md](docs/operations.md).

## Other commands

```bash
make check
```

Runs the backend suite, the frontend suite, TypeScript, and the production
build. `make dev` runs the Vite dev server against a separately running API;
`make e2e` runs the Playwright flows.

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
