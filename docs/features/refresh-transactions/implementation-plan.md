# Refresh Transactions Implementation Plan

**Goal:** Add a durable, accessible **Check for new transactions** dashboard action that safely refreshes and synchronizes every active bank connection without duplicate paid calls or stale dashboard state.

**Architecture:** Introduce an owner-scoped refresh parent with per-connection targets, backed by the existing SQLite job worker. The POST endpoint only persists/coalesces work. A leased and fenced worker reserves each eligible provider call, records uncertainty before recovery can redispatch, and uses monotonic sync generations so webhooks or scheduler requests arriving mid-sync force a later pass. The React dashboard polls the durable run for a bounded period, then invalidates both transaction views and their continuation state when terminal.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy 2 async, Alembic, SQLite WAL, Plaid Python, React 19, TypeScript, TanStack Query, Vitest, Testing Library, MSW, axe-core, Playwright, OpenAPI TypeScript

**Spec:** `docs/features/refresh-transactions/PRD.md`

## Global Constraints

The following constraints are copied verbatim from the PRD:

- Dashboard reads continue to use SQLite, the action does not promise bank-real-time data, and one unavailable or unsupported institution does not prevent the other connections from completing.
- Guarantee at most one `/transactions/refresh` dispatch per connection in each 15-minute eligibility window.
- **RT-API-002:** The POST shall perform no Plaid call and shall return a run representation within 200 ms at p95 on the supported local deployment.
- **RT-PROV-004:** A timeout, worker crash, or lost response after `dispatching` shall become `outcome_unknown`, count against the cooldown, enqueue sync-only reconciliation, and never automatically dispatch the refresh again.
- **RT-QUEUE-002:** Every synchronization request shall advance a monotonic requested generation for its connection. A worker shall record the generation it completed and schedule another pass whenever a newer generation arrived during its work.
- **RT-QUEUE-007:** Exactly one background worker and scheduler shall be enabled for the supported SQLite deployment. Claims, leases, and unique indexes remain correctness backstops, not an assertion that SQLite is a horizontally scalable queue.
- **RT-CACHE-005:** Cache invalidation shall cover both dashboard views even when only one is currently visible.
- **RT-SCALE-003:** Completed refresh runs and idempotency keys shall remain queryable for seven days, then be deleted by bounded batches. Cleanup shall not delete active runs.
- **RT-SCALE-004:** Moving to multiple owners, more than 50 active refresh-capable Items, more than one application host, or observed provider utilization above 50% of the account's actual limit shall require a shared provider-budget limiter and a transactional queue on PostgreSQL before rollout.

## Assumptions Resolved for This Plan

1. The current production envelope is one owner, four intended active institution Items, one application process, one worker, and SQLite WAL. Concurrency tests cover browser retries and competing claimers, but do not relabel SQLite as a distributed queue.
2. The UI label is **Check for new transactions**. “Refresh now” may be used as an internal feature name only.
3. The new aggregate endpoint is the sole path that may request provider refresh. The existing connection endpoint remains backward compatible in shape but becomes sync-only and returns `refresh_requested = false`.
4. Refresh work is processed through the existing job worker. A target stores a required sync generation as its completion barrier; it does not wait for a webhook correlation that Plaid does not provide.
5. The 15-minute persisted cooldown is deliberately stricter than Plaid's published default per-Item limits and bounds the current four-Item fleet well below the published default client limit. Runtime rate-limit responses remain authoritative.
6. A provider request ID is operational data and is stored server-side but omitted from browser responses.
7. Frontend polling uses approximately 1, 2, 5, then 10-second intervals with ±20% jitter and stops foreground polling after 90 seconds. Focus/online recovery may resume it.
8. Refresh run retention is seven days. Cleanup runs at most once per day in batches of 100 rows and never touches active rows.
9. The production action remains feature-flagged until the owner confirms Plaid Transactions Refresh access and separate billing.

## File Structure

### Backend persistence and orchestration

| Path | Change | Responsibility |
| --- | --- | --- |
| `backend/alembic/versions/0007_transaction_refreshes.py` | Create | Add refresh parents/request mappings/targets, unique indexes, sync generations, sync-run generation, job generation, and lease/fencing columns. |
| `backend/app/models.py` | Modify | Map `TransactionRefresh`, `TransactionRefreshRequest`, `TransactionRefreshTarget`, connection/sync-run generations, and job lease fields. |
| `backend/app/services/sync_service.py` | Modify | Make enqueue atomic and generation-based; return the requested generation; expose sync summaries to target completion. |
| `backend/app/services/sync_worker.py` | Modify | Claim with leases/fencing, heartbeat, recover expired work, honor newer generations, and drive refresh targets. |
| `backend/app/services/transaction_refresh_service.py` | Create | Create/coalesce runs and leased sync jobs, reserve provider attempts for claimed jobs, derive aggregate state, complete targets, and clean expired runs. |
| `backend/app/services/plaid_gateway.py` | Modify | Return a refresh request ID and classify refresh-limit/unsupported/owner-action outcomes. |
| `backend/app/services/plaid_client.py` | Modify | Return the Plaid refresh request ID without exposing secrets. |
| `backend/app/services/demo_gateway.py` | Modify | Provide deterministic accepted, unsupported, failed, and delayed refresh behavior. |
| `backend/app/api/transaction_refreshes.py` | Create | Expose POST/GET owner-scoped refresh-run APIs and serialize stable response schemas. |
| `backend/app/api/connections.py` | Modify | Expose the server-side refresh feature capability in the existing owner summary. |
| `backend/app/api/sync.py` | Modify | Remove inline provider refresh from the legacy endpoint while preserving its response shape. |
| `backend/app/api/webhooks.py` | Modify | Advance sync generation atomically for every actionable verified webhook. |
| `backend/app/schemas.py` | Modify | Define refresh run, target, summary, and enum response contracts. |
| `backend/app/config.py` | Modify | Add feature enablement, provider timeout, lease, heartbeat, and retention settings with safe validation. |
| `backend/app/main.py` | Modify | Register the router, recover expired work at startup, and schedule bounded cleanup. |

### Backend verification

| Path | Change | Responsibility |
| --- | --- | --- |
| `backend/tests/migrations/test_transaction_refreshes.py` | Create | Verify upgrade schema, defaults, foreign keys, partial unique indexes, and downgrade. |
| `backend/tests/services/test_sync_service.py` | Modify | Prove atomic enqueue/coalescing and monotonic generation behavior. |
| `backend/tests/services/test_sync_worker.py` | Modify | Prove leases, fencing, heartbeat, newer-generation reruns, crash recovery, and retry behavior. |
| `backend/tests/services/test_transaction_refresh_service.py` | Create | Prove run creation, provider state machine, cooldown, unsupported handling, uncertainty, aggregation, and cleanup. |
| `backend/tests/api/test_transaction_refreshes.py` | Create | Prove auth, CSRF, idempotency, owner isolation, validation, state serialization, and latency/no-inline-I/O. |
| `backend/tests/api/test_connections.py` | Modify | Prove the refresh capability reflects server configuration. |
| `backend/tests/api/test_sync.py` | Modify | Prove the legacy route is sync-only and still deduplicates. |
| `backend/tests/api/test_webhooks.py` | Modify | Prove a webhook during running sync advances generation and causes a later pass. |
| `backend/tests/fakes/plaid.py` | Modify | Record refresh/sync calls, request IDs, barriers, delays, and injected outcomes safely. |

### Frontend

| Path | Change | Responsibility |
| --- | --- | --- |
| `frontend/src/api/openapi.json` | Regenerate | Record refresh endpoint and response schemas. |
| `frontend/src/api/generated.ts` | Regenerate | Supply generated refresh contracts and enum unions. |
| `frontend/src/dashboard/transactionRefreshApi.ts` | Create | Generate idempotency keys and call create/status endpoints through `apiClient`. |
| `frontend/src/dashboard/transactionRefreshApi.test.ts` | Create | Verify header/path behavior, structured errors, and key reuse after ambiguous client failure. |
| `frontend/src/dashboard/useTransactionRefresh.ts` | Create | Own active-run recovery, bounded jittered polling, online/focus resume, terminal invalidation, and announcements. |
| `frontend/src/dashboard/useTransactionRefresh.test.tsx` | Create | Verify polling schedule, single mutation, terminal/timeout behavior, and invalidation roots. |
| `frontend/src/dashboard/RefreshTransactionsControl.tsx` | Create | Render the action, progress, outcome summary, offline help, and reconnect link accessibly. |
| `frontend/src/dashboard/DashboardPage.tsx` | Modify | Place the control, supply owner/fleet state, and reset both continuation generations after terminal refresh. |
| `frontend/src/dashboard/dashboard.test.tsx` | Modify | Cover the control in the grouped-card view without regressing search behavior. |
| `frontend/src/dashboard/all-transactions-view.test.tsx` | Modify | Cover the control and fresh aggregate data in the table view. |
| `frontend/src/dashboard/recovery-states.test.tsx` | Modify | Cover offline start, reconnect outcomes, long-running background copy, and last-known-good preservation. |
| `frontend/src/test/handlers.ts` | Modify | Add default and configurable refresh POST/GET handlers. |
| `frontend/src/test/dashboardFixtures.ts` | Modify | Add typed run/target fixture builders. |
| `frontend/src/styles.css` | Modify | Style responsive freshness action, progress, summaries, disabled state, and reduced motion. |
| `frontend/e2e/transaction-flow.spec.ts` | Modify | Exercise one real demo refresh across both dashboard views and verify stale continuation replacement. |

### Operations and product documentation

| Path | Change | Responsibility |
| --- | --- | --- |
| `.env.example` | Modify | Document the opt-in flag and bounded timeout/lease defaults. |
| `docs/operations.md` | Modify | Document entitlement/billing confirmation, rollout, metrics, unknown outcomes, recovery, and scale triggers. |
| `docs/PRD.md` | Modify | Link the feature PRD and replace legacy manual-refresh wording with the finalized behavior. |
| `README.md` | Modify | Describe the dashboard action without promising real-time results and link the feature PRD. |

## Stable Interfaces

These names and contracts are pinned by the PRD and must not drift during implementation.

### Persistence model

```python
class TransactionRefresh(Base):
    id: str
    owner_id: str
    state: Literal["queued", "running", "succeeded", "partial", "failed"]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime


class TransactionRefreshRequest(Base):
    id: str
    owner_id: str
    idempotency_key_sha256: str
    refresh_id: str
    created_at: datetime
    expires_at: datetime


class TransactionRefreshTarget(Base):
    id: str
    refresh_id: str
    connection_id: str
    state: RefreshTargetState
    refresh_outcome: RefreshAttemptState
    required_sync_generation: int | None
    provider_request_id: str | None
    next_refresh_eligible_at: datetime | None
    added_count: int
    modified_count: int
    removed_count: int
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None
```

Partial unique indexes enforce one `queued`/`running` refresh per owner and one non-terminal target per connection. `TransactionRefreshRequest(owner_id, idempotency_key_sha256)` is unique during retention, and every accepted key—including a different key coalesced onto an active run—gets a mapping. Requests and targets cascade when a retained parent is deleted; connections remain protected from deletion semantics by the existing lifecycle/tombstone flow.

`BankConnection.sync_requested_generation` and `sync_completed_generation` are non-negative integers defaulting to zero. `SyncRun.completed_generation` records which request barrier its counts satisfy. `SyncJob.target_generation` is non-negative: historical terminal jobs upgrade as zero, existing active jobs and their connections upgrade consistently to one, and all newly enqueued jobs are positive. `SyncJob.lease_owner`, `lease_token`, and `lease_expires_at` are nullable outside `running`.

### Service contracts

```python
@dataclass(frozen=True)
class EnqueuedSync:
    job: SyncJob
    requested_generation: int


async def enqueue_sync(
    session: AsyncSession,
    connection_id: str,
    trigger: str,
) -> EnqueuedSync: ...


class TransactionRefreshService:
    async def create_or_coalesce(
        self,
        owner_id: str,
        idempotency_key: str,
    ) -> tuple[TransactionRefresh, bool]: ...

    async def get_owned(self, owner_id: str, refresh_id: str) -> TransactionRefresh: ...

    async def reserve_target_for_job(
        self,
        connection_id: str,
        job_id: str,
        lease_token: str,
    ) -> str | None: ...

    async def recover_expired(self) -> int: ...

    async def cleanup_expired(self, batch_size: int = 100) -> int: ...
```

`create_or_coalesce` returns `(run, coalesced)`. It hashes the idempotency key before persistence, snapshots active owner connections in deterministic `(created_at, id)` order, reserves a sync generation/job for each new target, and does no provider I/O. `reserve_target_for_job` may advance a target only when the supplied job still owns its lease, so provider work has no separate queue or claim protocol.

### Job and target transition rules

```text
target: queued -> refreshing -> syncing -> terminal
attempt: not_attempted -> reserved -> dispatching -> accepted
                                      -> unsupported
                                      -> failed
                                      -> outcome_unknown
```

The worker claims a `SyncJob`, then checks for its connection's queued refresh target. It commits `dispatching`, `last_refresh_at`, and `next_refresh_eligible_at` before the provider call. `last_refresh_at` therefore means “dispatch reserved/possibly sent,” not “known provider success.” Every target already owns the sync generation reserved when its run was created; accepted, skipped, unsupported, failed, or uncertain refresh handling continues that job as sync-only and never creates an unleased work item. A webhook can request a higher generation at any time.

The worker claim sets a 60-second lease and heartbeats every 15 seconds. Provider and sync calls execute outside the event-loop thread with a 40-second per-call timeout. Every completion/retry transition includes `WHERE lease_token = :token`; a stale worker that loses the lease cannot commit a terminal job state or transaction changes. Values are configurable within validated bounds, and the lease must always exceed the provider timeout plus heartbeat grace.

### HTTP API

```text
POST /api/transaction-refreshes
Idempotency-Key: <1..128 visible ASCII characters>

GET /api/transaction-refreshes/{refresh_id}

GET /api/transaction-refreshes/active
```

```python
class TransactionRefreshSummaryResponse(BaseModel):
    total: int
    completed: int
    updated: int
    attention: int
    added: int
    modified: int
    removed: int


class TransactionRefreshTargetResponse(BaseModel):
    connection_id: str
    bank: str
    state: RefreshTargetState
    refresh_outcome: RefreshAttemptState
    next_refresh_eligible_at: datetime | None
    added: int
    modified: int
    removed: int
    error_code: str | None


class TransactionRefreshResponse(BaseModel):
    id: str
    state: RefreshRunState
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime
    summary: TransactionRefreshSummaryResponse
    targets: list[TransactionRefreshTargetResponse]


class CreateTransactionRefreshResponse(BaseModel):
    coalesced: bool
    refresh: TransactionRefreshResponse
```

POST returns `CreateTransactionRefreshResponse`: 202 for newly accepted or active/coalesced work and 200 for an idempotent replay of a terminal retained run. GET by ID returns `TransactionRefreshResponse` with 200. GET active returns that response or 204 when absent. Anonymous access returns 401; invalid CSRF/Origin returns 403; missing/expired/cross-owner IDs return the same 404; a missing or malformed idempotency header returns 422; no active connections returns 409/`NO_ACTIVE_CONNECTIONS`; a disabled feature returns 409/`TRANSACTION_REFRESH_DISABLED`. The existing connections response adds `transaction_refresh_enabled: bool` so the browser hides the action when disabled.

### Frontend boundary

```ts
export function createTransactionRefresh(idempotencyKey: string): Promise<CreateTransactionRefreshResponse>
export function fetchTransactionRefresh(refreshId: string): Promise<TransactionRefreshResponse>
export function fetchActiveTransactionRefresh(): Promise<TransactionRefreshResponse | null>

export interface UseTransactionRefreshResult {
  run: TransactionRefreshResponse | null
  start(): void
  isStarting: boolean
  isActive: boolean
  foregroundTimedOut: boolean
  announcement: string
}
```

One generated UUID remains attached to the logical click until POST returns a definite response or terminal replay. The hook does not create a new key for a retry after a network/parse failure with an unknown server outcome.

### Query invalidation boundary

On terminal state, invalidate these prefixes exactly:

```ts
['transactions', 'search', ownerId]
['transactions', 'all', ownerId]
CONNECTIONS_QUERY_KEY
TRANSACTION_LIMIT_ALERTS_QUERY_KEY
```

Increment a dashboard data-revision value at the same boundary. The existing continuation-scope generation includes that revision, and both `pageState` and `aggregatePage` are cleared before refetch results render.

## Dependency Order

```text
durable schema
  └── atomic generations + lossless enqueue
        └── leases/fencing + async provider boundary
              └── refresh state machine
                    └── owner-scoped API + generated contract
                          └── browser API + bounded polling
                                └── dashboard UI + cache reset
                                      └── E2E, rollout, and operations docs
```

## Task 1: Add Durable Refresh, Generation, and Lease State

**Commit:** `feat: persist transaction refresh orchestration`

**Files:**

- Create: `backend/alembic/versions/0007_transaction_refreshes.py`
- Modify: `backend/app/models.py`
- Create: `backend/tests/migrations/test_transaction_refreshes.py`

### Step 1.1: Write the failing migration test

Add tests that upgrade from `0006` and assert:

- all three refresh tables, foreign keys, timestamps, count defaults, and state columns exist;
- only one active run per owner and one active target per connection can be inserted;
- every accepted owner/idempotency hash maps to one retained run and cannot repeat during retention;
- connection generation defaults are zero and existing connection rows upgrade safely;
- job generation and lease fields allow existing queued jobs to upgrade with a valid target generation, and sync runs can record completed generation; and
- downgrade to `0006` removes only the new objects.

Run:

```bash
uv run --directory backend pytest tests/migrations/test_transaction_refreshes.py -q
```

Expected red: migration `0007` and mapped entities do not exist.

### Step 1.2: Implement the additive migration and mappings

- Use explicit named indexes/check constraints and SQLite partial-index predicates matching the mapped models.
- Backfill historical terminal jobs and sync runs with generation zero. Backfill existing active jobs to generation one and set their connections' requested generation to one before making the new fields non-null.
- Add non-negative checks for generations and counts.
- Add ORM relationships only where cascade semantics are explicit; never cascade from a connection into retained owner audit by accident.
- Export the new models from `models.py`.

### Step 1.3: Verify and commit

```bash
uv run --directory backend pytest tests/migrations/test_transaction_refreshes.py tests/migrations/test_core_schema.py -q
git add backend/alembic/versions/0007_transaction_refreshes.py backend/app/models.py backend/tests/migrations/test_transaction_refreshes.py
git diff --staged --check
git commit -m "feat: persist transaction refresh orchestration"
```

## Task 2: Make Synchronization Requests Atomic and Lossless

**Commit:** `fix: preserve concurrent synchronization requests`

**Files:**

- Modify: `backend/app/services/sync_service.py`
- Modify: `backend/app/api/webhooks.py`
- Modify: `backend/app/api/sync.py`
- Modify: `backend/tests/services/test_sync_service.py`
- Modify: `backend/tests/api/test_webhooks.py`
- Modify: `backend/tests/api/test_sync.py`

### Step 2.1: Write failing concurrency and generation tests

- Run 100 concurrent enqueue attempts against one connection and assert callers receive one active job without leaked `IntegrityError`.
- Hold a running sync at a fake gateway barrier, enqueue a webhook generation, release the barrier, and assert requested generation exceeds completed generation and a later pass remains queued.
- Assert duplicate webhook deliveries share one audit receipt but still advance/coalesce the requested generation, while distinct actionable webhooks do the same.
- Assert stale/startup/manual triggers use the same enqueue primitive.
- Assert the legacy connection endpoint makes zero `transactions_refresh` calls, returns `refresh_requested = false`, and still returns/coalesces its sync job.

Run:

```bash
uv run --directory backend pytest tests/services/test_sync_service.py tests/api/test_webhooks.py tests/api/test_sync.py -q -k 'generation or concurrent or manual_sync or webhook'
```

Expected red: enqueue uses a read-then-insert race, has no generations, and the legacy route calls refresh inline.

### Step 2.2: Implement one enqueue transaction

- Atomically increment `BankConnection.sync_requested_generation` and obtain the new value.
- Insert a queued job or coalesce by raising the active job's `target_generation` to the new value.
- Catch the unique-index race inside a savepoint and read/update the winner without rolling back the webhook receipt transaction.
- Return `EnqueuedSync(job, requested_generation)` to every caller.
- Remove `request_refresh` from `sync.py`; keep the existing response fields and route.

### Step 2.3: Verify and commit

```bash
uv run --directory backend pytest tests/services/test_sync_service.py tests/api/test_webhooks.py tests/api/test_sync.py -q
git add backend/app/services/sync_service.py backend/app/api/webhooks.py backend/app/api/sync.py backend/tests/services/test_sync_service.py backend/tests/api/test_webhooks.py backend/tests/api/test_sync.py
git diff --staged --check
git commit -m "fix: preserve concurrent synchronization requests"
```

## Task 3: Add Worker Leases, Fencing, and Recovery

**Commit:** `fix: recover and fence synchronization jobs`

**Files:**

- Modify: `backend/app/services/sync_worker.py`
- Modify: `backend/app/services/sync_service.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/services/test_sync_worker.py`

### Step 3.1: Write failing worker tests

Use fake time and two worker instances to prove:

- only one worker can claim a job and each claim has a random fencing token;
- heartbeat extends an owned lease during a slow provider call;
- an expired ordinary job returns to queued and completes within two lease periods;
- a stale worker cannot apply transactions or mark a job complete after losing its token;
- a generation requested during sync causes the same connection to remain queued for a later pass;
- completed generation advances only with the atomic transaction/cursor commit; and
- startup recovery and cleanup do not block lifespan startup indefinitely.

Run:

```bash
uv run --directory backend pytest tests/services/test_sync_worker.py -q -k 'lease or fence or generation or recover'
```

Expected red: current running jobs have no expiry or fencing and newer requests are discarded.

### Step 3.2: Implement the minimum lease protocol

- Claim due or expired work with a conditional update that writes owner/token/expiry.
- Run a heartbeat task while provider work runs and stop it in `finally`.
- Move blocking gateway calls through `asyncio.to_thread` and wrap each with the configured timeout.
- Verify the lease token immediately before the transaction apply and in the terminal/retry update predicate.
- On success, advance `sync_completed_generation` to the claimed target. If a newer request exists, clear lease fields and return the job to queued; otherwise finish it.
- Recover expired ordinary jobs without incrementing provider refresh attempts.
- Validate `heartbeat_seconds < lease_seconds` and `provider_timeout_seconds + heartbeat_seconds < lease_seconds`.

### Step 3.3: Verify and commit

```bash
uv run --directory backend pytest tests/services/test_sync_worker.py tests/services/test_sync_service.py -q
git add backend/app/services/sync_worker.py backend/app/services/sync_service.py backend/app/config.py backend/app/main.py backend/tests/services/test_sync_worker.py
git diff --staged --check
git commit -m "fix: recover and fence synchronization jobs"
```

## Task 4: Implement the Provider Refresh State Machine

**Commit:** `feat: orchestrate on-demand transaction refresh`

**Files:**

- Create: `backend/app/services/transaction_refresh_service.py`
- Modify: `backend/app/services/sync_worker.py`
- Modify: `backend/app/services/plaid_gateway.py`
- Modify: `backend/app/services/plaid_client.py`
- Modify: `backend/app/services/demo_gateway.py`
- Modify: `backend/tests/fakes/plaid.py`
- Create: `backend/tests/services/test_transaction_refresh_service.py`
- Modify: `backend/tests/services/test_sync_worker.py`

### Step 4.1: Write failing state-machine tests

Cover each pinned branch with explicit call counts and persisted states:

- eligible accepted refresh -> immediate sync -> `updated` or `no_changes`;
- cooldown -> no refresh call -> sync -> `cooldown` with eligibility timestamp;
- unsupported capability and provider `PRODUCTS_NOT_SUPPORTED` -> sync -> `automatic_updates_only`, with future calls skipped;
- owner-action failure -> `reconnect_required` without unsafe retries;
- response timeout/crash after `dispatching` -> `outcome_unknown`, cooldown consumed, no redispatch, sync-only recovery;
- transient sync failure after accepted refresh -> existing capped retry, with the target non-terminal until exhausted;
- disconnect before reservation -> `disconnected`, zero provider calls;
- one target failure does not cancel the remaining targets;
- parent summary/count/state derivation is deterministic;
- cleanup deletes at most 100 expired terminal parents and never active work; and
- structured events contain stable IDs/codes and numeric durations/counts but no tokens, plaintext idempotency keys, transaction text, amounts, or raw provider messages.

Run:

```bash
uv run --directory backend pytest tests/services/test_transaction_refresh_service.py tests/services/test_sync_worker.py -q -k refresh
```

Expected red: refresh-run service and worker transitions do not exist.

### Step 4.2: Implement safe dispatch and completion

- Hash idempotency keys with SHA-256 and never log/store plaintext.
- Resolve an existing request mapping first; otherwise create/coalesce the owner parent, insert a mapping for this key, and snapshot targets only for a newly created parent, all transactionally.
- Reserve only active targets and re-read connection lifecycle/token state before provider I/O.
- Commit `reserved`, then `dispatching` plus cooldown timestamp, before leaving the database transaction.
- Return provider request IDs from real/demo/fake gateways.
- During new-run creation, call the generation enqueue primitive once per target and store its returned generation as the target barrier. The claimed job then continues to sync after every refresh outcome that permits reconciliation; it never enqueues an unleased side task.
- Complete target counts from the `SyncRun` that satisfies the required generation; do not infer completion from webhook receipt.
- On expired dispatching recovery, mark unknown before permitting sync-only work.
- Derive parent state and timestamps from all child targets in one transaction.
- Emit the PRD's dispatch, target-outcome, generation-rerun, lease-recovery, stale-fence, cleanup, provider-latency, and sync-latency events through the existing structured logger.

### Step 4.3: Verify and commit

```bash
uv run --directory backend pytest tests/services/test_transaction_refresh_service.py tests/services/test_sync_worker.py tests/services/test_sync_service.py -q
git add backend/app/services/transaction_refresh_service.py backend/app/services/sync_worker.py backend/app/services/plaid_gateway.py backend/app/services/plaid_client.py backend/app/services/demo_gateway.py backend/tests/fakes/plaid.py backend/tests/services/test_transaction_refresh_service.py backend/tests/services/test_sync_worker.py
git diff --staged --check
git commit -m "feat: orchestrate on-demand transaction refresh"
```

## Task 5: Expose the Owner-Scoped Refresh API and Contract

**Commit:** `feat: expose transaction refresh API`

**Files:**

- Create: `backend/app/api/transaction_refreshes.py`
- Modify: `backend/app/api/connections.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/config.py`
- Create: `backend/tests/api/test_transaction_refreshes.py`
- Modify: `backend/tests/api/test_connections.py`
- Regenerate: `frontend/src/api/openapi.json`
- Regenerate: `frontend/src/api/generated.ts`

### Step 5.1: Write failing API tests

Assert exact status and response keys for:

- anonymous, missing CSRF, invalid Origin, missing/malformed idempotency key, and disabled feature;
- new 202, same-key replay, concurrent different-key coalescing with a durable mapping for every key, and terminal 200 replay;
- active-run discovery returning 200 during work and 204 when idle, including reload/second-tab use;
- no active connections;
- owner-safe not-found behavior for missing, expired, and another owner's IDs;
- every target/run enum value and stable error envelope;
- true/false `transaction_refresh_enabled` values on the connections response;
- 100 concurrent POSTs yielding one run; and
- a fake gateway barrier proving POST completes before any provider call, with p95 below 200 ms across local test requests; and
- create/coalesce/completion logs and acknowledgement timing contain no plaintext idempotency key or financial data.

Run:

```bash
uv run --directory backend pytest tests/api/test_transaction_refreshes.py -q
```

Expected red: the router and response schemas do not exist.

### Step 5.2: Add schemas, serializer, route, and feature settings

- Validate the idempotency header without reflecting it in errors.
- Use dependencies already established for owner/session/CSRF/Origin.
- Serialize bank slug and owner-safe stable codes only.
- Emit create/coalesce/completion counters and acknowledgement duration through named structured log events.
- Register literal `/active` before `/{refresh_id}` and register the router before the static-app fallback.
- Default production enablement to false; demo/test may enable deterministic behavior in fixtures, and the connections response exposes the resolved value.

### Step 5.3: Regenerate and verify the contract

```bash
pnpm --dir frontend generate:api
uv run --directory backend pytest tests/api/test_transaction_refreshes.py tests/api/test_connections.py tests/api/test_sync.py -q
pnpm --dir frontend typecheck
```

Inspect the generated diff for the three paths, the four response schemas, and exact enum unions. Do not hand-edit generated artifacts.

### Step 5.4: Commit

```bash
git add backend/app/api/transaction_refreshes.py backend/app/api/connections.py backend/app/schemas.py backend/app/main.py backend/app/config.py backend/tests/api/test_transaction_refreshes.py backend/tests/api/test_connections.py frontend/src/api/openapi.json frontend/src/api/generated.ts
git diff --staged --check
git commit -m "feat: expose transaction refresh API"
```

## Task 6: Add the Browser API and Bounded Polling Controller

**Commit:** `feat: add transaction refresh client state`

**Files:**

- Create: `frontend/src/dashboard/transactionRefreshApi.ts`
- Create: `frontend/src/dashboard/transactionRefreshApi.test.ts`
- Create: `frontend/src/dashboard/useTransactionRefresh.ts`
- Create: `frontend/src/dashboard/useTransactionRefresh.test.tsx`
- Modify: `frontend/src/test/handlers.ts`
- Modify: `frontend/src/test/dashboardFixtures.ts`

### Step 6.1: Write failing API/helper tests

- Assert POST sends a stable idempotency header and no unnecessary body.
- Assert GET path encodes the run ID and structured API errors are preserved.
- Assert active-run discovery maps 200 to a run and 204 to `null`.
- Simulate a network failure after server acceptance; retry and assert the same logical key is reused.
- Assert a definite 4xx abandons the key while an unknown network/parse outcome retains it.

Run:

```bash
pnpm --dir frontend test -- transactionRefreshApi.test.ts
```

Expected red: the API helper does not exist.

### Step 6.2: Write failing hook tests with fake timers

- One click creates one mutation even under repeated UI events.
- Poll timing advances through 1/2/5/10-second capped intervals with deterministic jitter injection.
- Terminal state stops polling and invalidates both owner transaction roots, connections, and alerts exactly once.
- Ninety seconds stops foreground polling and sets background copy without cancelling the run.
- Offline pauses requests; online/focus resumes the known run rather than creating another.
- Remount/reload and a second tab discover the owner-scoped active run from the server without persisting a refresh ID or creating a second run.

Run:

```bash
pnpm --dir frontend test -- useTransactionRefresh.test.tsx
```

Expected red: hook and query boundary do not exist.

### Step 6.3: Implement the minimum client controller

- Use generated response types only.
- Keep idempotency key lifecycle inside the hook; never persist it to storage or logs.
- Query the active endpoint on mount, online recovery, and window focus when no known run is already active.
- Use TanStack Query cancellation and a completion guard to prevent duplicate terminal invalidation.
- Pause interval advancement while offline/hidden and resume from the same elapsed-wall-clock deadline.
- Return semantic state to the component; keep copy selection in the component.

### Step 6.4: Verify and commit

```bash
pnpm --dir frontend test -- transactionRefreshApi.test.ts useTransactionRefresh.test.tsx
pnpm --dir frontend typecheck
git add frontend/src/dashboard/transactionRefreshApi.ts frontend/src/dashboard/transactionRefreshApi.test.ts frontend/src/dashboard/useTransactionRefresh.ts frontend/src/dashboard/useTransactionRefresh.test.tsx frontend/src/test/handlers.ts frontend/src/test/dashboardFixtures.ts
git diff --staged --check
git commit -m "feat: add transaction refresh client state"
```

## Task 7: Integrate the Accessible Dashboard Control and Cache Reset

**Commit:** `feat: add dashboard transaction refresh control`

**Files:**

- Create: `frontend/src/dashboard/RefreshTransactionsControl.tsx`
- Modify: `frontend/src/dashboard/DashboardPage.tsx`
- Modify: `frontend/src/dashboard/dashboard.test.tsx`
- Modify: `frontend/src/dashboard/all-transactions-view.test.tsx`
- Modify: `frontend/src/dashboard/recovery-states.test.tsx`
- Modify: `frontend/src/styles.css`

### Step 7.1: Write failing dashboard tests

Cover:

- presence with an enabled feature and active connection, and absence/disabled behavior when the feature is disabled or no active connection exists;
- exact idle, active, progress, updated, no-change, partial, unsupported, long-running, and offline copy;
- disabled double-click behavior and no focus movement;
- polite live-region updates and reconnect link destination;
- preservation of search, selected view, and current rows while running;
- clearing per-card and aggregate continuation state at terminal completion;
- rejection of a late pre-refresh continuation response;
- invalidation/refetch behavior in both views and last-known-good snapshots after failed refetch;
- 280-pixel viewport containment, 44-pixel target, keyboard use, reduced motion, and axe checks.

Run:

```bash
pnpm --dir frontend test -- dashboard.test.tsx all-transactions-view.test.tsx recovery-states.test.tsx
```

Expected red: the refresh control and data revision do not exist.

### Step 7.2: Implement the component and integration

- Place the control beside the cache-status region, outside view-specific result markup.
- Derive active connection count from the existing connection query.
- Add `dataRevision` to `continuationScopeKey`; clear both continuation state objects before invalidating/refetching.
- Keep visible rows and persisted snapshots until successful query data replaces them.
- Do not make the control depend on the submitted search or active dashboard view.
- Render no provider request IDs or raw provider messages.

### Step 7.3: Verify and commit

```bash
pnpm --dir frontend test -- dashboard.test.tsx all-transactions-view.test.tsx recovery-states.test.tsx search-flow.test.tsx
pnpm --dir frontend typecheck
git add frontend/src/dashboard/RefreshTransactionsControl.tsx frontend/src/dashboard/DashboardPage.tsx frontend/src/dashboard/dashboard.test.tsx frontend/src/dashboard/all-transactions-view.test.tsx frontend/src/dashboard/recovery-states.test.tsx frontend/src/styles.css
git diff --staged --check
git commit -m "feat: add dashboard transaction refresh control"
```

## Task 8: Verify End to End, Instrument, and Prepare Rollout

**Commit:** `docs: prepare transaction refresh rollout`

**Files:**

- Modify: `frontend/e2e/transaction-flow.spec.ts`
- Modify: `.env.example`
- Modify: `docs/operations.md`
- Modify: `docs/PRD.md`
- Modify: `README.md`

### Step 8.1: Add the failing end-to-end flow

In deterministic demo mode:

1. load more rows in **All cards**;
2. start one refresh and assert immediate progress without blanking rows;
3. observe terminal updated/no-change summary;
4. verify the grouped first page reflects fresh data without duplicated continuation rows;
5. switch to **All transactions** and verify its first page is fresh too;
6. reload during an active delayed run and resume status rather than starting a second run; and
7. verify keyboard and narrow-viewport behavior.

Run:

```bash
pnpm --dir frontend exec playwright test e2e/transaction-flow.spec.ts
```

Expected red before fixture/integration completion; green after Tasks 4–7.

### Step 8.2: Add observability and operations guidance

- Add the PRD metrics using the existing structured logging/metrics boundary; if the repository has no metric sink, emit named structured log events with numeric duration/count fields and document that limitation.
- Document entitlement and separate billing confirmation before production enablement.
- Document `outcome_unknown`, lease recovery, disabling the feature, allowing sync-only drain, seven-day cleanup, and interpreting stable error codes.
- Record the exact scale migration triggers and state that PostgreSQL queue migration and a shared provider-budget limiter ship together before multi-host/multi-owner expansion.
- Update the parent PRD and README to link this feature without describing it as real-time.

### Step 8.3: Run focused scale and failure drills

```bash
uv run --directory backend pytest tests/api/test_transaction_refreshes.py tests/services/test_transaction_refresh_service.py tests/services/test_sync_worker.py tests/api/test_webhooks.py -q
pnpm --dir frontend test -- transactionRefreshApi.test.ts useTransactionRefresh.test.tsx dashboard.test.tsx all-transactions-view.test.tsx recovery-states.test.tsx
```

Record evidence in the implementation PR description for:

- 100 concurrent POSTs -> one active run;
- one provider dispatch per eligible target/window;
- response timeout -> no redispatch;
- webhook during sync -> later generation pass;
- expired lease -> recovery within two lease periods;
- cross-owner status ID -> indistinguishable 404; and
- terminal refresh -> both transaction roots and continuation states reset.

### Step 8.4: Run the full quality gate

```bash
make check
make e2e
git diff --check
```

Expected green: backend, frontend, preview, typecheck, production build, and Playwright suites pass. The known baseline `test_api_routes_never_fall_through_to_the_spa` failure must be fixed or explicitly separated in a prior commit before claiming this feature branch fully green; it may not be silently waived at launch.

### Step 8.5: Commit rollout artifacts

```bash
git add frontend/e2e/transaction-flow.spec.ts .env.example docs/operations.md docs/PRD.md README.md
git diff --staged --check
git commit -m "docs: prepare transaction refresh rollout"
```

## Verification Matrix

| Risk | Primary evidence |
| --- | --- |
| Paid-call multiplication | 100-request API concurrency test, partial unique indexes, idempotency replay test, provider call counter |
| Lost webhook during sync | Barrier-based generation test across webhook and worker suites |
| Double dispatch after crash | Persisted `dispatching` state, expired-lease test, unknown-outcome no-retry assertion |
| Stale worker commit | Two-worker fencing test around transaction apply and terminal update |
| Stale dashboard mode | Both query-root invalidation assertions plus cross-view E2E |
| Stale pagination append | Data-revision/late-continuation component test |
| Partial bank failure | Four-target service/API test and owner-facing summary test |
| Unsupported Capital One | Gateway/service test proving no provider retry and sync-only completion |
| Run-table growth | Seven-day, 100-row batch cleanup test |
| Accidental horizontal scaling | Config/runbook gate and scale-trigger review |
| Privacy regression | Response schema assertions and log capture excluding keys/tokens/transaction text |
| Accessibility regression | Testing Library semantics, axe, keyboard, reduced-motion, and 280-pixel Playwright checks |

## Out-of-Scope Follow-up Trigger

Do not add Redis or a client-global token bucket speculatively. Before enabling multiple owners, more than 50 refresh-capable Items, multiple hosts, or sustained usage above half the provider account's observed limit, create a separate migration plan that:

1. moves application state and the transactional job queue to PostgreSQL;
2. adds a shared, persisted provider-budget limiter keyed by endpoint and credential set;
3. preserves the idempotency, target-attempt, generation, lease, fencing, and owner-isolation contracts defined here; and
4. proves migration/rollback without running SQLite and PostgreSQL as competing queues.
