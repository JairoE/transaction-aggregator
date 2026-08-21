# Operations Runbook

## 1. What this is

Transaction Aggregator is a single-owner, local-first web application: it runs on your own machine, binds its server to `127.0.0.1`, and never accepts a second account or tenant. It connects Capital One, Chase, Citi, and Wells Fargo credit cards through Plaid, caches transactions in a local SQLite database, and searches that cache — dashboard and search requests never call Plaid. Plaid is the only financial-data provider; there is no fallback or second aggregator.

## 2. Prerequisites

- Python 3.12, managed with [uv](https://docs.astral.sh/uv/).
- Node.js with [pnpm](https://pnpm.io/).
- **Full-disk encryption enabled on this machine.** This is a hard prerequisite from the PRD (SEC-011, Risk table), not advice — the SQLite database holds encrypted Plaid access tokens and cached transaction history, and the encryption-at-rest guarantee for that data depends on the disk itself being encrypted.
- To connect real banks: a [Plaid Trial account](https://dashboard.plaid.com/signup) and a stable HTTPS URL that forwards to your local machine (Section 7).

## 3. Three environments

`ENVIRONMENT` in `backend/.env` selects one of four modes (`backend/app/config.py`):

| `ENVIRONMENT` | Talks to | Consumes production Trial Item slots | When to use |
| --- | --- | --- | --- |
| `demo` | Nothing — a deterministic in-process fixture bank (`backend/app/services/demo_gateway.py`) | No | First run, local development, showing the app without any Plaid account |
| `sandbox` | Real Plaid Sandbox API | No | Repeated development and testing against real Plaid Link/OAuth/webhook flows |
| `production` | Real Plaid Production API | Yes, cumulatively | Connecting your actual bank accounts, sparingly |

`test` also exists (`ENVIRONMENT=test`) but it is used only by the automated pytest suite, not for interactive use.

The `demo` fixture (`DEMO_BANKS` and `PAZE_FIXTURE` in `demo_gateway.py`) implements the same `PlaidGateway` protocol as the real client, so every layer above it — encryption, sync, cursors, search — runs the real code path with no network call and no real bank credential involved. It models four banks with two credit cards each (eight cards total) and ten transactions matching `Paze` spread across all eight cards.

## 4. First run (demo, no credentials needed)

```bash
make install
```

```bash
cp .env.example backend/.env
```

Generate secrets and paste them into `backend/.env`, replacing the placeholder `APPLICATION_SECRET` and `TOKEN_ENCRYPTION_KEY` lines (see Section 5 for what each value is for):

```bash
make keys
```

Leave `ENVIRONMENT=demo` and the placeholder `PLAID_CLIENT_ID`/`PLAID_SECRET` values as they are — demo mode never calls Plaid, but `Settings` still requires those fields to be present.

Apply the database migrations:

```bash
make migrate
```

Create the single owner account (this prompts twice for a password of at least 14 characters):

```bash
make owner EMAIL=owner@example.com
```

Build the frontend and start the server:

```bash
make build
```

```bash
make serve
```

Open **http://127.0.0.1:8000** and sign in.

## 5. Generating secrets

```bash
uv run --directory backend python -m app.cli generate-keys
```

This prints two lines:

- `APPLICATION_SECRET` — a random string (`secrets.token_urlsafe(48)`), validated to be at least 32 characters. It signs CSRF tokens and search-pagination cursors.
- `TOKEN_ENCRYPTION_KEY` — a fresh 32-byte key, base64url-encoded. It is the AES-256-GCM key that encrypts every stored Plaid access token (`backend/app/services/crypto.py`).

`TOKEN_ENCRYPTION_KEY` must be **exactly 32 bytes**, base64url-encoded — `TokenCipher` raises `ValueError` at startup if it decodes to any other length. If you lose this key, every stored Plaid access token becomes permanently unreadable: `TokenCipher.decrypt` raises rather than returning plaintext, and there is no recovery path other than reconnecting each bank from scratch. The app fails closed by design — it never falls back to storing tokens unencrypted.

## 6. Connecting real banks (sandbox, then production)

1. In the [Plaid dashboard](https://dashboard.plaid.com/), go to Team Settings → Keys to get your Client ID and (Sandbox or Production) Secret.
2. Register the OAuth redirect URI. It must **exactly equal** `{PUBLIC_BASE_URL}/oauth-return` — the app computes this itself as `Settings.oauth_redirect_uri` and sends it on every Link token request, so a mismatch in the Plaid dashboard will reject the OAuth callback.
3. Register the webhook URL as `{PUBLIC_BASE_URL}/api/webhooks/plaid` (the route mounted in `backend/app/api/webhooks.py`).
4. Enable OAuth for these four institutions (real Plaid institution IDs, from `SUPPORTED_BANKS` in `backend/app/services/plaid_gateway.py`):

   | Bank | Plaid institution id |
   | --- | --- |
   | Capital One | `ins_128026` |
   | Chase | `ins_3` |
   | Citi | `ins_5` |
   | Wells Fargo | `ins_4` |

For **sandbox**, set `ENVIRONMENT=sandbox` and put your Sandbox `PLAID_CLIENT_ID`/`PLAID_SECRET` in `backend/.env`. `Settings` only enforces the HTTPS/non-loopback rule when `ENVIRONMENT=production`, so sandbox can run against `PUBLIC_BASE_URL=http://127.0.0.1:8000` for most testing — but OAuth-based Sandbox institutions still require the redirect URI and webhook URL to be registered against a real HTTPS URL, so use the tunnel from Section 7 if you need to exercise the OAuth path in sandbox.

For **production**, set `ENVIRONMENT=production` and your Production `PLAID_CLIENT_ID`/`PLAID_SECRET`. Production **requires** the stable HTTPS tunnel from Section 7 — see Section 8 before connecting a real bank.

## 7. Stable HTTPS with a named Cloudflare Tunnel

```bash
cloudflared tunnel login
```

```bash
cloudflared tunnel create transaction-aggregator
```

```bash
cloudflared tunnel route dns transaction-aggregator ta.example.com
```

```bash
cloudflared tunnel run --url http://127.0.0.1:8000 transaction-aggregator
```

Update `backend/.env`:

```bash
PUBLIC_BASE_URL=https://ta.example.com
PLAID_WEBHOOK_URL=https://ta.example.com/api/webhooks/plaid
TRUSTED_HOSTS=127.0.0.1,localhost,ta.example.com
```

Restart the server, then verify:

```bash
curl -fsS https://ta.example.com/api/health
```

Expect `{"status":"ok"}`.

`Settings._validate` refuses to start in `production` if `PUBLIC_BASE_URL` is not `https://` or resolves to a loopback host (`127.0.0.1`, `localhost`, `::1`) — a real bank OAuth redirect and Plaid webhook cannot reach `localhost`, so this failure is intentional rather than a bug to work around.

## 8. The Plaid Trial Item budget

The Plaid Trial plan allows at most **10 production Items total, cumulative**. `/item/remove` does **not** return a slot — `ConnectionService.disconnect` marks the row `lifecycle_status="removed"` but leaves `plaid_environment="production"` on it, so it is still counted. This is intentional (`backend/app/services/connection_service.py`, `TRIAL_ITEM_LIMIT = 10`): the app keeps tombstones specifically so the local count stays honest with Plaid's real cumulative count.

Read the current count two ways:

- `GET /api/connections` returns a `production_item_count` field alongside `production_item_limit` (10).
- Directly against the database:

```bash
sqlite3 backend/data/transactions.db "SELECT COUNT(*) FROM bank_connections WHERE plaid_environment='production';"
```

Use `sandbox` for all repeat testing — sandbox connections are stored with `plaid_environment='sandbox'` and never count toward this limit.

## 9. Day-to-day operations

### Migrate

```bash
make migrate
```

### Back up

The database runs in WAL mode (`PRAGMA journal_mode=WAL`, set in `backend/app/db.py`), so a plain `cp` of `transactions.db` while the app is running can capture an inconsistent snapshot — uncommitted pages can still be sitting in the `-wal` sidecar file. Use SQLite's online backup instead:

```bash
sqlite3 backend/data/transactions.db ".backup 'backend/data/backup-$(date +%Y%m%d-%H%M%S).db'"
```

This produces a single consistent file and is safe to run while the server is up. If you ever do copy the raw files (app stopped only), copy `transactions.db`, `transactions.db-wal`, and `transactions.db-shm` together, or checkpoint first so the `-wal` file is empty:

```bash
sqlite3 backend/data/transactions.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

### Restore

Stop the server, then:

```bash
cp backend/data/backup-20260819-120000.db backend/data/transactions.db
```

```bash
rm -f backend/data/transactions.db-wal backend/data/transactions.db-shm
```

Start the server again; `create_database` re-applies `0600`/`0700` permissions on connect.

### Rotate the encryption key

Back up first (see above). Generate a new key, then re-encrypt every stored
Plaid access token under it:

```bash
uv run --directory backend python -m app.cli generate-keys
```

```bash
uv run --directory backend python -m app.cli rotate-key --new-version 2 --new-key <new-base64-key>
```

Omit `--new-key` to read the key from stdin instead of leaving it in shell
history. The command re-encrypts every row whose token is still under the old
version and reports how many it rewrote.

Then set `TOKEN_ENCRYPTION_KEY` to the new key and
`TOKEN_ENCRYPTION_KEY_VERSION` to the new version in `backend/.env`, and
restart the app.

What the command guarantees:

- The whole rotation runs in one transaction. If any row fails to decrypt,
  nothing is written and the old key stays the working key.
- Ciphertext stays bound to its own connection row, because AES-GCM associated
  data covers both the key version and the row id
  (`plaid-access-token:v{version}:{connection_id}`). A ciphertext copied into
  a different row still fails to decrypt after rotation.
- Rows already at the target version are skipped, so an interrupted run can be
  re-run safely.
- The new version must be greater than the current one; reusing a version is
  rejected.

Tombstone rows hold no token and are skipped.

### Inspect sync health

```bash
sqlite3 backend/data/transactions.db ".headers on" ".mode column" \
  "SELECT bank_slug, lifecycle_status, last_successful_sync_at, last_provider_update_at, last_error_code FROM bank_connections WHERE lifecycle_status='active';"
```

```bash
sqlite3 backend/data/transactions.db ".headers on" ".mode column" \
  "SELECT connection_id, trigger, state, attempts, run_after, last_error_code FROM sync_jobs ORDER BY updated_at DESC LIMIT 10;"
```

```bash
sqlite3 backend/data/transactions.db ".headers on" ".mode column" \
  "SELECT connection_id, outcome, added_count, modified_count, removed_count, error_code, started_at, finished_at FROM sync_runs ORDER BY started_at DESC LIMIT 10;"
```

## 10. Disconnecting a bank

`DELETE /api/connections/{id}` (`ConnectionService.disconnect`) does, in order:

1. Calls Plaid's `/item/remove` with the decrypted access token (best-effort — local cleanup proceeds even if this call fails).
2. Deletes that connection's `card_accounts` and their `transactions` rows.
3. Sets `lifecycle_status='removed'`, `removed_at=now`, and clears `access_token_ciphertext`, `access_token_nonce`, `access_token_key_version`, `sync_cursor`, and `last_error_code`.

**The consumed Plaid Trial Item slot is NOT returned.** The tombstone row keeps `plaid_environment='production'`, so it still counts toward the 10-Item cumulative limit in Section 8.

## 11. Troubleshooting

| Symptom / code | Cause | Fix |
| --- | --- | --- |
| `HOST_NOT_ALLOWED` | `TrustedHostMiddleware` (`backend/app/middleware.py`) rejected the request's `Host` header because it isn't in `TRUSTED_HOSTS` | Add the host (e.g. a new tunnel hostname) to `TRUSTED_HOSTS` in `backend/.env`, comma-separated, and restart |
| `TRIAL_LIMIT_REACHED` | `production_item_count` is already 10 (`connection_service.py`) | No automatic fix — capacity is exhausted; use `sandbox` for further testing |
| `TRIAL_SLOT_UNCONFIRMED` | A production Link token was requested without `confirm_trial_slot=true` | Confirm the Trial-slot warning in the UI before Link opens |
| `USE_UPDATE_MODE` | An active connection already exists for that institution | Use Reconnect (update-mode Link) instead of Connect |
| `WRONG_INSTITUTION_LINKED` | The institution actually linked in Plaid Link didn't match the bank tile you started from; the app already called `/item/remove` and recorded a removed tombstone | Retry from the correct bank tile; if this was production, the slot is still consumed (Section 8) |
| `CURSOR_INVALID` | The search pagination cursor was malformed, expired, or replayed against the wrong card (`search_service.py`) | Resubmit the search — cursors are per-card and HMAC-signed, not reusable across cards |
| `AUTH_REQUIRED` | No valid session cookie (never logged in, or the 12-hour session expired) | Sign in again |
| `CSRF_INVALID` | `X-CSRF-Token` header was missing or didn't match the session's CSRF token on a mutating request | Reload to get a fresh session/CSRF token; if this persists, check that `PUBLIC_BASE_URL`/`TRUSTED_HOSTS` match how you're actually reaching the app |
| Bank stuck in `needs_reconnect` | Plaid reported `ITEM_LOGIN_REQUIRED`, `INVALID_CREDENTIALS`, `INVALID_MFA`, `USER_PERMISSION_REVOKED`, `USER_ACCOUNT_REVOKED`, `ACCESS_NOT_GRANTED`, or `ITEM_NOT_SUPPORTED` (`connection_health.py`) | Click Reconnect — opens update-mode Link against the existing Item, does not consume another Trial slot |
| Bank stuck in `consent_expired` | Plaid reported `PENDING_DISCONNECT`/`PENDING_EXPIRATION`, or `consent_expiration_at` has passed | Click Renew — same update-mode Link path, no new Trial slot consumed |
| Sync seems to never run without a webhook | This is expected, not a bug | Webhooks are only an accelerator (`enqueue_sync` on `SYNC_UPDATES_AVAILABLE` etc.). Startup enqueues any active connection whose `last_successful_sync_at` is older than `SYNC_INTERVAL_MINUTES` (default 60), and the in-process scheduler repeats that check every `SYNC_INTERVAL_MINUTES` while running — reconciliation always catches up from the stored cursor even if every webhook is lost |
| Startup fails: "SQLite must be compiled with FTS5 and the trigram tokenizer" | `Database.verify_fts5_trigram()` (`backend/app/db.py`) probed `CREATE VIRTUAL TABLE ... USING fts5(x, tokenize='trigram')` and it failed | Install/use a Python build linked against SQLite 3.34+ with FTS5 enabled. Verify with: `python3 -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute(\"CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')\"); print('ok')"` |

## 12. Security posture

- **Bank credentials:** entered only in bank- or Plaid-hosted Link UI — this application never renders a credential field and never receives a bank username, password, or MFA response (SEC-001).
- **Plaid client secret:** backend-only environment variable, never bundled into the frontend (SEC-002).
- **Plaid access tokens:** encrypted at rest with AES-256-GCM, a versioned 32-byte key from `TOKEN_ENCRYPTION_KEY`, associated-data-bound to both key version and connection row id (SEC-003, SEC-004).
- **Passwords:** hashed with Argon2id (`pwdlib`), never logged (SEC-005).
- **Session tokens:** 256 bits of randomness (`secrets.token_urlsafe(32)`); only the SHA-256 hash is stored (SEC-006).
- **Cookies:** `HttpOnly`, `SameSite=Strict`, and `Secure` whenever the app is reached over HTTPS (SEC-007).
- **Mutations:** require a matching CSRF token and an allowed `Origin` header (SEC-008).
- **Webhooks:** verified via the `Plaid-Verification` signature before any database write or job creation (SEC-009).
- **Logs:** structured JSON with recursive redaction of any key containing `password`, `secret`, `token`, `authorization`, `cookie`, `api_key`, `credential`, `access_token`, `public_token`, `query`, `search_text`, `original_description`, or `merchant_name` (SEC-010, `backend/app/logging.py`).
- **File permissions:** the SQLite database file is `0600` and its directory is `0700`, re-applied on every connection (SEC-011, `backend/app/db.py`).
- **API errors:** returned to the browser as a stable `{code, message}` pair only — no stack traces or provider error text (SEC-012).
