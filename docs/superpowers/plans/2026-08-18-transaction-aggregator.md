# Transaction Aggregator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a private, local-first web application that connects Capital One, Chase, Citi, and Wells Fargo through Plaid and searches cached credit-card transactions from one card-by-card dashboard.

**Architecture:** A React/Vite single-page application talks to a same-origin FastAPI API. FastAPI owns authentication, encrypted Plaid tokens, a SQLite cache, durable sync jobs, and Plaid webhooks; the UI never calls Plaid directly except through `react-plaid-link`. Searches use SQLite FTS5 and independent per-card cursors, while `/transactions/sync` maintains the cache once per Plaid Item.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic, SQLite WAL/FTS5, `plaid-python`, React 19, TypeScript 5, Vite, React Router, TanStack Query, TanStack Virtual, `react-plaid-link`, Pytest, Vitest, Testing Library, MSW, and Playwright.

**Spec:** [docs/PRD.md](../../PRD.md)

## Global Constraints

- Support one locally created owner account; do not add public signup or tenant concepts.
- Connect only Capital One, Chase, Citi, and Wells Fargo credit-card accounts in v1.
- Use Plaid Transactions with `days_requested=730` and the current Plaid User API.
- Never collect bank credentials or expose Plaid secrets/access tokens to the frontend.
- Use SQLite only; do not add PostgreSQL, Redis, Celery, RabbitMQ, or a second data provider.
- Search only the local database; dashboard and search requests must not call Plaid.
- Treat the Plaid Trial production Item count as cumulative, including removed Items, with a hard maximum of 10.
- Keep one active connection per owner and institution; use update mode for repair and consent renewal.
- Keep the application server bound to localhost and use a stable HTTPS forwarding URL for OAuth and webhooks.
- Implement every behavior test-first and commit only after the task's focused and regression suites pass.

---

## Planned Repository Structure

```text
.
├── Makefile
├── .env.example
├── backend
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── alembic.ini
│   ├── alembic
│   │   ├── env.py
│   │   └── versions
│   │       ├── 0001_core_schema.py
│   │       └── 0002_transaction_search.py
│   ├── app
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── dependencies.py
│   │   ├── cli.py
│   │   ├── api
│   │   │   ├── auth.py
│   │   │   ├── connections.py
│   │   │   ├── search.py
│   │   │   ├── sync.py
│   │   │   └── webhooks.py
│   │   └── services
│   │       ├── auth.py
│   │       ├── crypto.py
│   │       ├── plaid_gateway.py
│   │       ├── connection_service.py
│   │       ├── sync_service.py
│   │       ├── sync_worker.py
│   │       └── search_service.py
│   └── tests
│       ├── conftest.py
│       ├── fakes
│       │   └── plaid.py
│       ├── api
│       ├── services
│       └── migrations
├── frontend
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── playwright.config.ts
│   ├── index.html
│   ├── src
│   │   ├── main.tsx
│   │   ├── app.tsx
│   │   ├── styles.css
│   │   ├── api
│   │   │   ├── client.ts
│   │   │   └── generated.ts
│   │   ├── auth
│   │   ├── connections
│   │   ├── dashboard
│   │   └── test
│   └── e2e
│       └── transaction-flow.spec.ts
└── docs
    ├── PRD.md
    └── operations.md
```

`backend/app/models.py` and `backend/app/schemas.py` are intentionally centralized for v1 so relationships and wire contracts remain easy to audit. Split either file only after it exceeds 500 lines and a task requires touching unrelated sections.

---

### Task 1: Establish the Tested Frontend and Backend Skeleton

**Files:**
- Create: `Makefile`
- Create: `.gitignore`
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_health.py`
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app.tsx`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/app.test.tsx`

**Interfaces:**
- Produces: `backend.app.main.create_app() -> FastAPI`
- Produces: `GET /api/health -> {"status": "ok"}`
- Produces: React `App` component with the product heading
- Consumes: no application interfaces

- [x] **Step 1: Create the dependency manifests and failing smoke tests**

Use Python 3.12 and these dependency groups in `backend/pyproject.toml`:

```toml
[project]
name = "transaction-aggregator-api"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "alembic>=1.16,<2",
  "aiosqlite>=0.21,<1",
  "cryptography>=45,<46",
  "fastapi>=0.116,<1",
  "httpx>=0.28,<1",
  "plaid-python>=38,<40",
  "pydantic-settings>=2.10,<3",
  "pwdlib[argon2]>=0.2,<1",
  "sqlalchemy[asyncio]>=2.0.43,<3",
  "uvicorn[standard]>=0.35,<1",
]

[dependency-groups]
dev = [
  "anyio>=4.10,<5",
  "freezegun>=1.5,<2",
  "pytest>=8.4,<9",
  "pytest-asyncio>=1.1,<2",
  "pytest-cov>=6.2,<7",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Use React 19, Vite, Vitest, and Testing Library in `frontend/package.json`, with scripts named `dev`, `build`, `test`, `test:watch`, `typecheck`, and `e2e`.

Create `backend/tests/test_health.py` first:

```python
from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_health_endpoint_returns_ok() -> None:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

Create `frontend/src/app.test.tsx` first:

```tsx
import { render, screen } from '@testing-library/react'
import { App } from './app'

it('renders the product heading', () => {
  render(<App />)
  expect(
    screen.getByRole('heading', { name: 'Transaction Aggregator' }),
  ).toBeInTheDocument()
})
```

- [x] **Step 2: Install dependencies and verify both smoke tests fail**

Run:

```bash
uv sync --project backend --all-groups
pnpm --dir frontend install
uv run --project backend pytest tests/test_health.py -q
pnpm --dir frontend test -- app.test.tsx
```

Expected: backend collection fails because `create_app` is missing, and frontend collection fails because `App` is missing.

- [x] **Step 3: Implement the minimal application entry points**

Create `backend/app/main.py`:

```python
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Transaction Aggregator API")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

Create `frontend/src/app.tsx`:

```tsx
export function App() {
  return <h1>Transaction Aggregator</h1>
}
```

Wire `frontend/src/main.tsx` through `createRoot`, configure Vitest with `jsdom` and the setup file, and add Make targets `install`, `test`, `typecheck`, and `build` that call both workspaces.

- [x] **Step 4: Verify the skeleton**

Run:

```bash
uv run --project backend pytest tests/test_health.py -q
pnpm --dir frontend test -- app.test.tsx
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

Expected: two smoke tests pass, TypeScript exits 0, and Vite writes `frontend/dist`.

- [x] **Step 5: Commit the skeleton**

```bash
git add Makefile .gitignore backend frontend
git commit -m "chore: scaffold frontend and backend"
```

---

### Task 2: Add Settings, Encryption, Database Models, and the Core Migration

**Files:**
- Create: `.env.example`
- Create: `backend/app/config.py`
- Create: `backend/app/db.py`
- Create: `backend/app/models.py`
- Create: `backend/app/services/crypto.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0001_core_schema.py`
- Create: `backend/tests/services/test_crypto.py`
- Create: `backend/tests/test_config.py`
- Create: `backend/tests/migrations/test_core_schema.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Produces: `get_settings() -> Settings`
- Produces: `create_database(settings: Settings) -> Database`
- Produces: `TokenCipher.encrypt(value: str) -> EncryptedSecret`
- Produces: `TokenCipher.decrypt(secret: EncryptedSecret) -> str`
- Produces: SQLAlchemy models `Owner`, `OwnerSession`, `BankConnection`, `CardAccount`, `Transaction`, `SyncJob`, `SyncRun`, and `WebhookReceipt`
- Consumes: `create_app()` from Task 1

- [x] **Step 1: Write failing configuration, encryption, and schema tests**

Define the encryption contract in `backend/tests/services/test_crypto.py`:

```python
from base64 import urlsafe_b64encode
from os import urandom

from app.services.crypto import TokenCipher


def test_access_token_round_trip_does_not_store_plaintext() -> None:
    key = urlsafe_b64encode(urandom(32)).decode()
    cipher = TokenCipher.from_base64_key(key, key_version=1)

    encrypted = cipher.encrypt("access-production-secret")

    assert "access-production-secret" not in encrypted.ciphertext
    assert encrypted.key_version == 1
    assert cipher.decrypt(encrypted) == "access-production-secret"
```

Define a migration test that upgrades an empty SQLite database and asserts the exact core table names and uniqueness of `transactions.plaid_transaction_id`.

- [x] **Step 2: Run the focused tests and verify failure**

Run:

```bash
uv run --project backend pytest \
  tests/test_config.py \
  tests/services/test_crypto.py \
  tests/migrations/test_core_schema.py -q
```

Expected: collection fails because `config`, `models`, and `TokenCipher` do not exist.

- [x] **Step 3: Implement validated settings and AES-GCM encryption**

Define `Settings` with these required values:

```python
class Settings(BaseSettings):
    environment: Literal["test", "sandbox", "production"] = "sandbox"
    database_url: str = "sqlite+aiosqlite:///./data/transactions.db"
    application_secret: SecretStr
    token_encryption_key: SecretStr
    token_encryption_key_version: int = 1
    session_cookie_name: str = "ta_session"
    public_base_url: AnyHttpUrl
    plaid_client_id: SecretStr
    plaid_secret: SecretStr
    plaid_webhook_url: AnyHttpUrl | None = None
```

`TokenCipher` shall decode exactly 32 key bytes, generate a new 12-byte nonce for every encryption, authenticate the key version as associated data, and store URL-safe base64 ciphertext and nonce values.

- [x] **Step 4: Implement models and the initial Alembic migration**

Use string UUID primary keys and UTC-aware timestamps. Add these constraints:

- `owners.email` unique.
- `bank_connections(owner_id, institution_id)` unique for active rows through service validation.
- `card_accounts.plaid_account_id` unique.
- `transactions.plaid_transaction_id` unique.
- `sync_jobs` partial unique index on `connection_id` where state is `queued` or `running`.
- `webhook_receipts.payload_sha256` unique.

Keep removed `BankConnection` rows with `lifecycle_status="removed"`, null encrypted-token fields, and `removed_at` populated. Store money as signed integer cents plus ISO currency code.

- [x] **Step 5: Verify migration, round trip, permissions defaults, and model constraints**

Run:

```bash
uv run --project backend alembic upgrade head
uv run --project backend pytest \
  tests/test_config.py \
  tests/services/test_crypto.py \
  tests/migrations/test_core_schema.py -q
```

Expected: migration reaches `0001`, all focused tests pass, and a second insert using the same Plaid transaction ID raises an integrity error.

- [x] **Step 6: Commit the persistence foundation**

```bash
git add .env.example backend/app/config.py backend/app/db.py \
  backend/app/models.py backend/app/services/crypto.py backend/alembic.ini \
  backend/alembic backend/tests
git commit -m "feat: add encrypted local persistence"
```

---

### Task 3: Implement Single-Owner Authentication and CSRF Protection

**Files:**
- Create: `backend/app/schemas.py`
- Create: `backend/app/dependencies.py`
- Create: `backend/app/services/auth.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/auth.py`
- Create: `backend/app/cli.py`
- Create: `backend/tests/api/test_auth.py`
- Create: `backend/tests/services/test_auth.py`
- Modify: `backend/app/main.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces: `create_owner(session, email, password) -> Owner`
- Produces: `authenticate_owner(session, email, password) -> Owner | None`
- Produces: `create_owner_session(session, owner_id) -> CreatedSession`
- Produces: `require_owner(request) -> Owner`
- Produces: `require_csrf(request) -> None`
- Produces: `POST /api/auth/login`, `GET /api/auth/session`, and `POST /api/auth/logout`
- Consumes: `Owner`, `OwnerSession`, and `Settings` from Task 2

- [x] **Step 1: Write failing service and endpoint tests**

Cover these behaviors in `backend/tests/api/test_auth.py`:

```python
async def test_login_sets_opaque_cookie_and_returns_csrf_token(client, owner) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"email": owner.email, "password": "correct horse battery staple"},
    )

    assert response.status_code == 200
    assert response.json()["owner"]["email"] == owner.email
    assert len(response.json()["csrf_token"]) >= 32
    assert "ta_session=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]


async def test_mutation_rejects_missing_csrf(client, authenticated_owner) -> None:
    response = await client.post("/api/auth/logout")
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_INVALID"
```

Also test invalid credentials, normalized email case, expired sessions, logout revocation, repeated owner creation, and that the stored session value is a SHA-256 hash rather than the cookie value.

- [x] **Step 2: Run authentication tests and verify failure**

Run:

```bash
uv run --project backend pytest \
  tests/services/test_auth.py tests/api/test_auth.py -q
```

Expected: collection fails because authentication services and routes are missing.

- [x] **Step 3: Implement password and session services**

Use Argon2id through `pwdlib.PasswordHash.recommended()`. Generate the browser token and CSRF token independently with `secrets.token_urlsafe(32)`, store only `sha256(browser_token).hexdigest()`, and set a 12-hour expiry.

Return this authenticated session contract:

```python
class SessionResponse(BaseModel):
    owner: OwnerResponse
    csrf_token: str


class OwnerResponse(BaseModel):
    id: str
    email: str
```

Return the same generic `AUTH_INVALID` response for unknown email and wrong password.

- [x] **Step 4: Implement the local owner CLI and route dependencies**

Expose this command:

```bash
uv run --project backend python -m app.cli create-owner --email owner@example.com
```

Prompt twice with `getpass`, reject fewer than 14 characters, and refuse creation when an owner row already exists. `require_csrf` shall compare the `X-CSRF-Token` header using `secrets.compare_digest` and reject an unexpected `Origin` before a mutation reaches a route handler.

- [x] **Step 5: Register routes and verify authentication**

Run:

```bash
uv run --project backend pytest \
  tests/services/test_auth.py tests/api/test_auth.py -q
uv run --project backend pytest -q
```

Expected: focused and regression suites pass with no plaintext password or session token in captured logs.

- [x] **Step 6: Commit owner authentication**

```bash
git add backend/app backend/tests backend/pyproject.toml backend/uv.lock
git commit -m "feat: add single-owner authentication"
```

---

### Task 4: Implement Plaid Link and Trial-Safe Connection Management

**Files:**
- Create: `backend/app/services/plaid_gateway.py`
- Create: `backend/app/services/connection_service.py`
- Create: `backend/app/api/connections.py`
- Create: `backend/tests/fakes/plaid.py`
- Create: `backend/tests/services/test_connection_service.py`
- Create: `backend/tests/api/test_connections.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces: `PlaidGateway` protocol and `PlaidPythonGateway`
- Produces: `ConnectionService.create_link_token(owner, bank, confirm_trial_slot) -> LinkTokenResponse`
- Produces: `ConnectionService.exchange_public_token(owner, request) -> ConnectionResponse`
- Produces: `ConnectionService.create_update_link_token(owner, connection_id) -> LinkTokenResponse`
- Produces: `ConnectionService.disconnect(owner, connection_id) -> None`
- Produces: `GET /api/connections`, `POST /api/connections/link-token`, `POST /api/connections/exchange`, `POST /api/connections/{id}/update-token`, and `DELETE /api/connections/{id}`
- Consumes: authentication dependencies and encrypted persistence from Tasks 2–3

- [x] **Step 1: Write a fake Plaid gateway and failing connection tests**

Define this protocol before the concrete client:

```python
class PlaidGateway(Protocol):
    def create_user(self, client_user_id: str) -> str:
        raise NotImplementedError

    def create_link_token(self, request: LinkTokenRequest) -> str:
        raise NotImplementedError

    def exchange_public_token(self, public_token: str) -> ExchangedItem:
        raise NotImplementedError

    def get_accounts(self, access_token: str) -> list[PlaidAccount]:
        raise NotImplementedError

    def remove_item(self, access_token: str) -> None:
        raise NotImplementedError
```

The concrete `PlaidPythonGateway` must implement every method and translate provider responses into the application dataclasses; it must never inherit these protocol bodies at runtime.

Test:

- a Link token requests `transactions`, 730 days, US, the Plaid `user_id`, redirect URI, webhook URL, and `credit card` account filter;
- Sandbox Link does not consume production capacity;
- Production Link requires `confirm_trial_slot=true`;
- a tenth recorded production tombstone blocks another production Link;
- an active institution blocks duplicate Link and returns `USE_UPDATE_MODE`;
- exchange encrypts the access token and persists two credit cards while ignoring checking accounts;
- an unexpected institution is immediately removed, recorded as a consumed tombstone, and returns `WRONG_INSTITUTION_LINKED`;
- disconnect removes the Plaid Item, purges cards/transactions, clears token fields, and retains the tombstone.

- [x] **Step 2: Run connection tests and verify failure**

Run:

```bash
uv run --project backend pytest \
  tests/services/test_connection_service.py tests/api/test_connections.py -q
```

Expected: collection fails because the Plaid gateway, connection service, and routes are missing.

- [x] **Step 3: Implement the Plaid gateway boundary**

Use these default institution identifiers, while allowing a JSON environment override for provider migrations:

```python
SUPPORTED_BANKS = {
    "capital-one": SupportedBank("Capital One", frozenset({"ins_128026"})),
    "chase": SupportedBank("Chase", frozenset({"ins_3"})),
    "citi": SupportedBank("Citi", frozenset({"ins_5"})),
    "wells-fargo": SupportedBank("Wells Fargo", frozenset({"ins_4"})),
}
```

Translate Plaid SDK exceptions into application exceptions containing only provider error code, request ID, and retry class. Never include access tokens or raw request bodies in exception text.

- [x] **Step 4: Implement the Trial guard and connection transaction**

Before production Link token creation:

1. Lock the owner's connection rows.
2. Reject an active expected institution.
3. Count every `environment="production"` connection row, including removed rows.
4. Reject a count of 10.
5. Require the explicit confirmation flag.

During exchange, decrypt nothing from browser input. Exchange server-side, validate the institution metadata against the selected bank, encrypt the access token, upsert only `type="credit"` and `subtype="credit card"` accounts, and enqueue initial synchronization in the same database transaction.

- [x] **Step 5: Implement authenticated routes and update mode**

Use these request shapes:

```python
class CreateLinkTokenRequest(BaseModel):
    bank: Literal["capital-one", "chase", "citi", "wells-fargo"]
    confirm_trial_slot: bool = False


class ExchangePublicTokenRequest(BaseModel):
    bank: Literal["capital-one", "chase", "citi", "wells-fargo"]
    public_token: str
    institution_id: str
    institution_name: str
```

Update-mode Link tokens use the decrypted existing access token, omit `products`, and never increment the local production Item count.

- [x] **Step 6: Verify all connection paths**

Run:

```bash
uv run --project backend pytest \
  tests/services/test_connection_service.py tests/api/test_connections.py -q
uv run --project backend pytest -q
```

Expected: all connection cases and the regression suite pass; fake gateway call logs contain no plaintext access token after assertions are complete.

- [x] **Step 7: Commit connection management**

```bash
git add backend/app backend/tests
git commit -m "feat: add Plaid connection management"
```

---

### Task 5: Build Durable Incremental Transaction Synchronization

**Files:**
- Create: `backend/app/services/sync_service.py`
- Create: `backend/app/services/sync_worker.py`
- Create: `backend/app/api/sync.py`
- Create: `backend/app/api/webhooks.py`
- Create: `backend/tests/services/test_sync_service.py`
- Create: `backend/tests/services/test_sync_worker.py`
- Create: `backend/tests/api/test_webhooks.py`
- Create: `backend/tests/api/test_sync.py`
- Modify: `backend/app/services/plaid_gateway.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces: `enqueue_sync(session, connection_id, trigger) -> SyncJob`
- Produces: `SyncService.synchronize(connection_id, job_id) -> SyncSummary`
- Produces: `SyncWorker.run_once() -> bool`
- Produces: `POST /api/connections/{id}/sync`, `GET /api/sync/status`, and `POST /api/webhooks/plaid`
- Consumes: encrypted connections and `PlaidGateway` from Task 4

- [x] **Step 1: Extend the fake gateway and write failing reconciliation tests**

Add exact gateway values:

```python
from collections.abc import Sequence


@dataclass(frozen=True)
class SyncPage:
    added: Sequence[PlaidTransaction]
    modified: Sequence[PlaidTransaction]
    removed_ids: Sequence[str]
    next_cursor: str
    has_more: bool


class SyncMutationDuringPagination(Exception):
    pass
```

Test:

- initial empty-cursor synchronization;
- multi-page cursor advancement;
- added, modified, and removed rows committed atomically;
- rollback leaves the previous cursor and cache intact;
- mutation-during-pagination restarts from the attempt's starting cursor;
- duplicate job enqueue returns the existing queued/running job;
- startup enqueues connections older than 60 minutes;
- transient failures use capped backoff of 30 seconds, 2 minutes, 8 minutes, and 30 minutes;
- owner-action errors stop retries and set `attention` status;
- unsupported refresh records `refresh_supported=false` without failing normal sync;
- duplicate signed webhooks create one receipt and at most one queued job;
- invalid webhook signatures return 401 and enqueue nothing.

- [x] **Step 2: Run synchronization tests and verify failure**

Run:

```bash
uv run --project backend pytest \
  tests/services/test_sync_service.py \
  tests/services/test_sync_worker.py \
  tests/api/test_sync.py \
  tests/api/test_webhooks.py -q
```

Expected: collection fails because synchronization services and routes are missing.

- [x] **Step 3: Implement transactional cursor reconciliation**

Use this page-loop invariant:

```python
attempt_cursor = connection.sync_cursor or ""
request_cursor = attempt_cursor
pages: list[SyncPage] = []

while True:
    try:
        page = gateway.transactions_sync(access_token, request_cursor)
    except SyncMutationDuringPagination:
        request_cursor = attempt_cursor
        pages.clear()
        continue
    pages.append(page)
    request_cursor = page.next_cursor
    if not page.has_more:
        break

apply_pages_and_cursor_in_one_transaction(pages, request_cursor)
```

Convert decimal Plaid amounts to integer cents with `Decimal.quantize`, normalize dates to ISO values, and compute `search_text` from merchant, name, and original description. Upsert by Plaid transaction ID; deleting a removed ID must be idempotent.

- [x] **Step 4: Implement the durable job worker and scheduler**

Claim one due queued job with a database transaction, mark it running, execute outside the claim transaction, then record success or the classified failure. The FastAPI lifespan starts one worker loop and one hourly stale-connection scheduler. Tests receive a disabled lifespan worker and invoke `run_once()` deterministically.

Use job triggers `initial`, `startup`, `scheduled`, `webhook`, and `manual`. The partial unique index prevents more than one queued/running job per connection.

- [x] **Step 5: Implement verified webhook and manual sync routes**

The webhook route shall:

1. Read the raw body once.
2. Verify `Plaid-Verification` through the gateway.
3. Hash the body with SHA-256.
4. Insert the receipt idempotently.
5. Resolve `item_id` to an active connection.
6. Enqueue on `SYNC_UPDATES_AVAILABLE`, `PENDING_DISCONNECT`, or Item error events.
7. Return 204 without calling `/transactions/sync` inline.

Manual sync returns HTTP 202 with the existing or new job ID. If refresh is allowed and its 15-minute cooldown has elapsed, request refresh before enqueueing normal sync.

- [x] **Step 6: Verify sync recovery and regression behavior**

Run:

```bash
uv run --project backend pytest \
  tests/services/test_sync_service.py \
  tests/services/test_sync_worker.py \
  tests/api/test_sync.py \
  tests/api/test_webhooks.py -q
uv run --project backend pytest -q
```

Expected: focused tests pass, duplicate fixtures leave one row, mutation fixtures restart at the original cursor, and the full backend suite passes.

- [x] **Step 7: Commit synchronization**

```bash
git add backend/app backend/tests
git commit -m "feat: synchronize Plaid transactions"
```

---

### Task 6: Add Cached Search and Grouped Per-Card API Contracts

**Files:**
- Create: `backend/alembic/versions/0002_transaction_search.py`
- Create: `backend/app/services/search_service.py`
- Create: `backend/app/api/search.py`
- Create: `backend/tests/migrations/test_transaction_search.py`
- Create: `backend/tests/services/test_search_service.py`
- Create: `backend/tests/api/test_search.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces: `normalize_query(query: str) -> NormalizedQuery`
- Produces: `SearchService.search(owner_id, query, per_card_limit, cursors) -> GroupedSearchResponse`
- Produces: `GET /api/transactions/search?q={query}&per_card_limit={limit}&cursor.{card_id}={cursor}`
- Produces: `GET /api/cards/{card_id}/transactions?cursor={cursor}&limit={limit}`
- Consumes: cached `CardAccount` and `Transaction` rows from Tasks 2 and 5

- [x] **Step 1: Write the failing migration, service, and API tests**

Seed eight cards and transactions whose `merchant_name`, `name`, and `original_description` contain mixed-case variants of `Paze`. Assert:

- `q=Paze` returns 10 matches grouped into exactly eight card groups;
- every active card appears even when its match count is zero;
- matching is case-insensitive and preserves the provider's original display text;
- pending and posted transactions remain distinct only when their Plaid IDs are distinct;
- each group has an independent opaque cursor and `has_more` flag;
- a card cursor cannot be replayed against another card;
- punctuation-only input and SQL metacharacters are treated as literal data rather than query syntax;
- an input shorter than three normalized characters uses the indexed fallback path;
- a 50,000-row fixture completes the service search under 250 ms at p95 on the test runner.

Define the wire contract in the tests:

```python
class TransactionMatch(BaseModel):
    id: str
    card_id: str
    merchant_name: str | None
    description: str
    original_description: str | None
    amount_cents: int
    currency_code: str
    authorized_date: date | None
    posted_date: date | None
    pending: bool


class CardTransactionGroup(BaseModel):
    card: CardResponse
    transactions: list[TransactionMatch]
    match_count: int
    next_cursor: str | None
    has_more: bool


class GroupedSearchResponse(BaseModel):
    query: str
    total_matches: int
    groups: list[CardTransactionGroup]
    cache_as_of: datetime | None
```

- [x] **Step 2: Run the focused tests and verify failure**

Run:

```bash
uv run --project backend pytest \
  tests/migrations/test_transaction_search.py \
  tests/services/test_search_service.py \
  tests/api/test_search.py -q
```

Expected: migration assertions fail because the search index is absent, then test collection fails on the missing search service and route.

- [x] **Step 3: Add the FTS5 migration and query normalization**

Create an external-content FTS5 table with `tokenize='trigram'`, keyed by the integer transaction row ID and indexing `merchant_name`, `name`, `original_description`, and `search_text`. Add insert, update, and delete triggers, then rebuild the index during migration. Verify SQLite was compiled with FTS5 and the trigram tokenizer at application startup and fail with a clear configuration error if either is unavailable.

`normalize_query` shall Unicode-normalize, trim, collapse internal whitespace, cap input at 100 characters, and generate safely quoted FTS terms. A blank normalized query selects the recent-transactions path. Punctuation-only input remains a literal substring query. For normalized terms shorter than three characters, use escaped `LIKE` predicates over indexed normalized columns; never concatenate user input into SQL.

- [x] **Step 4: Implement deterministic grouped pagination**

Order matches by `COALESCE(posted_date, authorized_date) DESC`, then `id DESC`. Encode each card cursor as URL-safe base64 JSON containing `card_id`, last sort date, and last ID, signed with HMAC-SHA256 using the application secret. Reject malformed, expired, or cross-card cursors with `CURSOR_INVALID`.

The grouped endpoint executes entirely against SQLite, lists active credit cards in bank/card display order, queries at most `per_card_limit + 1` matches per card, and computes exact per-card and total counts in the same read transaction. Clamp `per_card_limit` to 1–50, default 25. The unfiltered card endpoint uses the same serializer and cursor rules.

- [x] **Step 5: Register the routes and verify search behavior**

Run:

```bash
uv run --project backend alembic upgrade head
uv run --project backend pytest \
  tests/migrations/test_transaction_search.py \
  tests/services/test_search_service.py \
  tests/api/test_search.py -q
uv run --project backend pytest -q
```

Expected: migration reaches `0002`; the `Paze` fixture reports 10 matches across eight groups; cursor, injection, and performance tests pass; the full backend suite stays green.

- [x] **Step 6: Commit cached search**

```bash
git add backend/alembic backend/app backend/tests
git commit -m "feat: add grouped transaction search"
```

---

### Task 7: Build Owner Sign-In, Bank Connection, and Loading-State UI

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/generated.ts`
- Create: `frontend/src/auth/AuthProvider.tsx`
- Create: `frontend/src/auth/LoginPage.tsx`
- Create: `frontend/src/auth/auth.test.tsx`
- Create: `frontend/src/connections/ConnectionsPage.tsx`
- Create: `frontend/src/connections/BankConnectionCard.tsx`
- Create: `frontend/src/connections/PlaidLinkLauncher.tsx`
- Create: `frontend/src/connections/OAuthReturnPage.tsx`
- Create: `frontend/src/connections/connections.test.tsx`
- Create: `frontend/src/test/server.ts`
- Create: `frontend/src/test/handlers.ts`
- Modify: `frontend/src/app.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces: `ApiClient.request<T>(path, options) -> Promise<T>` with credentials and CSRF handling
- Produces: `useAuth() -> { owner, csrfToken, login, logout, status }`
- Produces: `ConnectionsPage` for four fixed supported-bank connection cards
- Produces: `PlaidLinkLauncher` using `react-plaid-link`
- Produces: `/oauth-return` continuation through `OAuthReturnPage`
- Consumes: authentication and connection API contracts from Tasks 3–4

- [x] **Step 1: Write failing UI tests with MSW**

Test these user-observable states:

- an anonymous visitor lands on the owner sign-in form;
- valid login routes to four connection cards;
- failed login keeps the password out of logs and renders the generic API error;
- production connection requires a Trial-slot confirmation before requesting a Link token;
- a successful Link callback exchanges the public token and shows per-bank loading progress;
- an OAuth redirect reinitializes Link with the original Link token and current redirect URI before exchange;
- an absent or expired OAuth continuation returns safely to the connection page without an exchange call;
- already connected banks offer `Reconnect` and `Disconnect`, not a second `Connect`;
- all four connected banks reveal `View cards`;
- network and provider errors remain scoped to the affected bank;
- rendered markup and captured logs never contain Link tokens, public tokens, or access tokens.

Use semantic role queries and add an `axe` smoke assertion for the login and connections views.

- [x] **Step 2: Run the UI tests and verify failure**

Run:

```bash
pnpm --dir frontend test -- auth connections
```

Expected: tests fail because `AuthProvider`, `LoginPage`, `ConnectionsPage`, `OAuthReturnPage`, and the MSW handlers do not exist.

- [x] **Step 3: Implement the typed API boundary and auth route guard**

Generate `frontend/src/api/generated.ts` from FastAPI's OpenAPI document with a pinned script, then expose a small manual wrapper:

```ts
export interface RequestOptions extends RequestInit {
  csrf?: boolean
}

export class ApiClient {
  constructor(private readonly getCsrfToken: () => string | null) {}
  request<T>(path: string, options?: RequestOptions): Promise<T>
}
```

Always use `credentials: 'same-origin'`. Add `X-CSRF-Token` only for mutating requests, decode the stable API error envelope, and redirect to sign-in on `AUTH_REQUIRED` without retrying a mutation.

- [x] **Step 4: Implement fixed-bank connection cards and Plaid Link**

Render Capital One, Chase, Citi, and Wells Fargo from a typed constant, not from provider-supplied markup. A connect action obtains a Link token server-side, invokes `usePlaidLink`, and sends only `public_token`, selected bank slug, and institution metadata back to the exchange endpoint. Disable repeat clicks while Link or exchange is active.

Display initial synchronization as `Connecting`, `Loading accounts`, `Loading transactions`, `Ready`, or `Needs attention` using connection/sync responses. Announce state changes through an `aria-live="polite"` region and preserve keyboard focus when the Plaid dialog closes.

Before Link opens, store only `{ bank, linkToken, expiresAt }` in `sessionStorage` under an owner-scoped continuation key. Route the registered redirect URI to `/oauth-return`; there, reject missing or expired state and otherwise reinitialize `react-plaid-link` with the same Link token and `receivedRedirectUri=window.location.href`. Clear the continuation on success, exit, logout, or expiry. A top-level OAuth return shall never place a public token, access token, or bank credential in a URL or persistent browser storage.

- [x] **Step 5: Verify frontend connection flows**

Run:

```bash
pnpm --dir frontend test -- auth connections
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

Expected: all focused tests pass, TypeScript exits 0, and the production bundle contains no Plaid secret or server access token pattern.

- [x] **Step 6: Commit the sign-in and connection UI**

```bash
git add frontend
git commit -m "feat: add owner and bank connection flows"
```

---

### Task 8: Build the Responsive Card Grid and Explicit `Paze` Search Flow

**Files:**
- Create: `frontend/src/dashboard/DashboardPage.tsx`
- Create: `frontend/src/dashboard/SearchBar.tsx`
- Create: `frontend/src/dashboard/CardGrid.tsx`
- Create: `frontend/src/dashboard/CardPanel.tsx`
- Create: `frontend/src/dashboard/TransactionList.tsx`
- Create: `frontend/src/dashboard/dashboard.test.tsx`
- Create: `frontend/src/dashboard/search-flow.test.tsx`
- Modify: `frontend/src/app.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces: `SearchBar({ initialQuery, onSubmit, pending })`
- Produces: `CardGrid({ groups, onLoadMore })`
- Produces: `CardPanel({ group, onLoadMore })`
- Produces: `TransactionList({ transactions, height })` with virtualization
- Consumes: grouped search and per-card transaction contracts from Task 6

- [x] **Step 1: Write the failing dashboard and interaction tests**

Use the approved eight-card fixture and assert:

- the initial dashboard renders all eight cards under one search bar;
- each card has a fixed-height, independently scrollable transaction region;
- typing `Paze` does not search until Enter or the Search button is used;
- submitting `Paze` renders `10 matches for “Paze” across 8 cards`;
- all eight card groups remain visible, including zero-match groups;
- loading more one card changes only that card's list and cursor;
- a second search cancels stale in-flight results and resets all cursors;
- an empty submit restores recent cached transactions;
- 320 px, 768 px, and 1440 px viewport snapshots have no horizontal overflow;
- every result row exposes date, merchant/description, pending state, and signed amount to assistive technology.

- [x] **Step 2: Run the focused dashboard tests and verify failure**

Run:

```bash
pnpm --dir frontend test -- dashboard search-flow
```

Expected: tests fail because dashboard components and query hooks are missing.

- [x] **Step 3: Implement query ownership and explicit submission**

Keep `draftQuery` separate from `submittedQuery`. Only the form submit handler copies draft to submitted state. Use TanStack Query keys `['transactions', 'search', submittedQuery]` and a distinct query per card cursor. Abort the previous request when the key changes and retain the previous successful page only while the new request is pending.

The search form contract is:

```ts
type SearchBarProps = {
  initialQuery: string
  pending: boolean
  onSubmit: (query: string) => void
}
```

- [x] **Step 4: Implement responsive, independent card lists**

Use one column below 768 px, two columns from 768–1199 px, and four columns at 1200 px and above. Keep each card panel at a minimum 360 px height and its transaction viewport at 260 px. Use TanStack Virtual only inside each transaction viewport, with stable transaction IDs as keys and a visible `Load more` control when `has_more=true`.

Amounts use `Intl.NumberFormat` and stored currency; dates use the user's locale while retaining an ISO `datetime`. Do not encode bank identity with color alone.

- [x] **Step 5: Verify the approved `Paze` behavior and responsive grid**

Run:

```bash
pnpm --dir frontend test -- dashboard search-flow
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

Expected: the eight-card fixture shows 10 grouped `Paze` matches only after submit, each card paginates independently, and all tested viewports avoid horizontal scrolling.

- [x] **Step 6: Commit the dashboard**

```bash
git add frontend
git commit -m "feat: add grouped transaction dashboard"
```

---

### Task 9: Handle Reconnection, Stale/Offline Data, Partial Failure, and Consent Expiration

**Files:**
- Create: `backend/app/services/connection_health.py`
- Create: `backend/tests/services/test_connection_health.py`
- Create: `frontend/src/connections/ConnectionNotice.tsx`
- Create: `frontend/src/dashboard/CacheStatusBanner.tsx`
- Create: `frontend/src/dashboard/recovery-states.test.tsx`
- Modify: `backend/app/api/connections.py`
- Modify: `backend/app/api/sync.py`
- Modify: `backend/app/schemas.py`
- Modify: `frontend/src/connections/BankConnectionCard.tsx`
- Modify: `frontend/src/dashboard/DashboardPage.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces: `classify_connection_health(connection, latest_run, now) -> ConnectionHealth`
- Produces: connection states `ready`, `syncing`, `stale`, `needs_reconnect`, `consent_expired`, `provider_degraded`, and `disconnected`
- Produces: `ConnectionNotice` and `CacheStatusBanner`
- Consumes: update-mode Link, sync status, and cached-search responses from Tasks 4–8

- [x] **Step 1: Write failing backend classification and frontend recovery tests**

Cover:

- `ITEM_LOGIN_REQUIRED` maps to `needs_reconnect` and opens Link update mode;
- consent expiration maps to `consent_expired` with a renewal action;
- transient Plaid outage maps to `provider_degraded` while cached search remains available;
- a failed bank does not hide healthy banks or their cards;
- data older than 60 minutes is labeled stale with its exact cache timestamp;
- offline navigation after one successful load shows cached TanStack Query data and disables sync/connect actions;
- reconnect success enqueues sync and returns the connection to `syncing` then `ready`;
- a removed connection's cached transactions are absent rather than silently stale.

- [x] **Step 2: Run the recovery tests and verify failure**

Run:

```bash
uv run --project backend pytest tests/services/test_connection_health.py -q
pnpm --dir frontend test -- recovery-states
```

Expected: backend collection fails on the missing classifier and frontend tests fail on missing recovery components.

- [x] **Step 3: Implement one canonical health classifier**

Define:

```python
class ConnectionHealth(BaseModel):
    state: Literal[
        "ready", "syncing", "stale", "needs_reconnect",
        "consent_expired", "provider_degraded", "disconnected",
    ]
    cache_as_of: datetime | None
    last_error_code: str | None
    action: Literal["none", "sync", "reconnect", "renew_consent"]
```

Use provider error codes only for classification and user-safe copy; never return raw Plaid messages. `needs_reconnect` and `consent_expired` create an update-mode Link token against the existing Item and do not consume another Trial slot.

- [x] **Step 4: Implement resilient cached-data UI states**

Keep bank errors inside their associated connection card and card panels. A global banner may summarize `2 of 4 banks need attention`, but it must not replace successful results. Persist only successful query-cache entries in `sessionStorage`, namespace by owner ID, expire them after 12 hours, and clear them on logout. Never persist auth or CSRF tokens.

When `navigator.onLine` is false, label results `Offline · cached {timestamp}`, keep local search results visible, and disable controls that require the backend. When the API is reachable but Plaid is degraded, local search and cached lists remain enabled.

- [x] **Step 5: Verify recovery and regression behavior**

Run:

```bash
uv run --project backend pytest tests/services/test_connection_health.py -q
pnpm --dir frontend test -- recovery-states
uv run --project backend pytest -q
pnpm --dir frontend test
pnpm --dir frontend typecheck
```

Expected: targeted and regression tests pass; partial failures preserve healthy data; update mode repairs the existing Item without increasing the production Item count.

- [x] **Step 6: Commit recovery states**

```bash
git add backend/app backend/tests frontend
git commit -m "feat: add connection recovery states"
```

---

### Task 10: Package Same-Origin Delivery, HTTPS Tunneling, Observability, and End-to-End Verification

**Files:**
- Create: `backend/app/logging.py`
- Create: `backend/tests/api/test_security_headers.py`
- Create: `backend/tests/test_static_app.py`
- Create: `frontend/e2e/transaction-flow.spec.ts`
- Create: `frontend/e2e/recovery-flow.spec.ts`
- Create: `frontend/playwright.config.ts`
- Create: `docs/operations.md`
- Modify: `backend/app/main.py`
- Modify: `backend/app/config.py`
- Modify: `frontend/vite.config.ts`
- Modify: `Makefile`

**Interfaces:**
- Produces: FastAPI same-origin hosting of `frontend/dist` with SPA fallback outside `/api`
- Produces: structured application events with request, connection, sync-run, and Plaid request IDs
- Produces: `make dev`, `make test`, `make build`, `make serve`, and `make e2e`
- Produces: local HTTPS tunnel and deployment runbook in `docs/operations.md`
- Consumes: all application behavior from Tasks 1–9

- [x] **Step 1: Write failing packaging, header, and end-to-end tests**

Backend tests assert:

- `/api/*` never falls through to the SPA;
- `/dashboard` serves `index.html` after a production build;
- responses include a restrictive Content Security Policy, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and frame protection;
- cookies are `Secure`, `HttpOnly`, `SameSite=Strict`, and scoped to `/` outside tests;
- logs redact keys matching password, secret, token, authorization, cookie, and Plaid payload fields.

Playwright tests cover the exact acceptance flow: owner sign-in; sequential Capital One, Chase, Citi, and Wells Fargo connections; eight loaded credit cards; typing `Paze`; explicit submission; 10 grouped matches; independent list scrolling; and logout. Add a second test for one reconnect-required bank, one provider failure, stale cache, and offline display.

- [x] **Step 2: Run the new tests and verify failure**

Run:

```bash
uv run --project backend pytest \
  tests/api/test_security_headers.py tests/test_static_app.py -q
pnpm --dir frontend e2e
```

Expected: backend assertions fail because static serving and headers are absent, and Playwright fails because the production server fixture and flows are not configured.

- [x] **Step 3: Implement same-origin production delivery and safe telemetry**

Build the SPA before packaging. Mount immutable hashed assets with a one-year cache policy, serve `index.html` with `no-cache`, and return the SPA fallback only for non-API GET requests that accept HTML. Add request IDs at the ASGI boundary and emit structured JSON fields rather than serialized request bodies.

Record route, status, elapsed milliseconds, owner ID, connection ID, sync-run ID, Plaid request ID, rows added/modified/removed, and classified error code where applicable. Apply recursive redaction before serialization and do not log search queries by default.

- [x] **Step 4: Document local HTTPS and deployment operations**

`docs/operations.md` must give exact commands to:

1. generate the encryption key and application secret;
2. configure Plaid Sandbox or Production credentials;
3. register the stable HTTPS redirect URI and webhook URL;
4. start the localhost server and a named Cloudflare Tunnel to it;
5. create the single owner;
6. migrate, back up, restore, rotate encryption keys, and inspect sync health;
7. build and run the same-origin production artifact;
8. disconnect an Item and explain why the Trial capacity is not restored.

Bind Uvicorn to `127.0.0.1` by default. Require an explicit `TRUSTED_HOSTS` allowlist and fail startup when production uses a loopback or plain-HTTP public URL.

- [x] **Step 5: Implement and run the end-to-end fixtures**

Use MSW or a deterministic fake Plaid adapter; automated tests must never access live bank accounts. Configure Playwright for system Chromium, capture traces on retry, and test desktop plus a 375 px mobile project. Assert no `pageerror`, failed API request, console error, or horizontal overflow.

Run:

```bash
make test
make typecheck
make build
make e2e
uv run --project backend alembic upgrade head
uv run --project backend alembic check
```

Expected: backend, frontend, and end-to-end suites pass; builds exit 0; desktop and mobile complete the full `Paze` flow; Alembic reports no pending model changes.

- [x] **Step 6: Perform release security and operations checks**

Run:

```bash
git grep -nEi '(access[-_ ]?token|plaid_secret|password).{0,40}(print|console|log)'
uv run --project backend python -m pip check
pnpm --dir frontend audit --prod
curl -fsS https://localhost.example/api/health
```

Expected: the secret-log scan returns no application matches, Python dependencies are consistent, the production dependency audit has no high/critical findings, and the configured HTTPS tunnel returns `{"status":"ok"}`. Replace `localhost.example` with the registered tunnel hostname from `docs/operations.md` when executing the plan.

- [x] **Step 7: Commit production readiness and end-to-end coverage**

```bash
git add Makefile backend frontend docs/operations.md
git commit -m "chore: add production operations and e2e coverage"
```

---

## Final Verification Before Opening the Implementation PR

- [x] Run `git diff --check main..HEAD` and require no whitespace errors.
- [x] Run `make test`, `make typecheck`, `make build`, and `make e2e`; preserve the command output in the PR validation section.
- [x] Run `uv run --project backend alembic upgrade head` against a new SQLite file and require migrations `0001` and `0002` to succeed.
- [x] Confirm the API's OpenAPI schema matches `frontend/src/api/generated.ts` with the pinned generation command.
- [x] Confirm four supported institutions, eight-card fixture coverage, and 10 grouped `Paze` matches in Playwright.
- [x] Confirm no browser console/page errors, failed API requests, or horizontal overflow at 375 px and 1440 px.
- [x] Confirm a production connection requires Trial-slot acknowledgement and the 10-Item cumulative guard rejects Item 11.
- [x] Confirm every bank-specific failure preserves cached data for healthy banks.
- [x] Confirm no secrets appear in the built frontend, application logs, test snapshots, or committed fixtures.
- [x] Confirm `docs/operations.md` includes backup/restore and stable HTTPS callback procedures.

The implementation is complete only when every checkbox above is satisfied and the acceptance criteria in `docs/PRD.md` have corresponding passing automated evidence.
