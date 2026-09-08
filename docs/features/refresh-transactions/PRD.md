# Refresh Transactions Button PRD

- **Status:** Approved for implementation planning
- **Version:** 1.1
- **Date:** September 8, 2026
- **Parent product:** [Transaction Aggregator PRD](../../PRD.md)
- **Implementation plan:** [Refresh Transactions Implementation Plan](implementation-plan.md)

## Summary

Add a dashboard action labeled **Check for new transactions**. One activation creates a durable, owner-scoped refresh run for every active bank connection, returns immediately, and reports progress while background work asks supported institutions for an on-demand Plaid refresh and then reconciles the local cache with `/transactions/sync`.

The feature improves freshness without weakening the product's local-first behavior. Dashboard reads continue to use SQLite, the action does not promise bank-real-time data, and one unavailable or unsupported institution does not prevent the other connections from completing.

## Problem and User Value

Plaid normally checks institutions on its own schedule, commonly one to four times per day. The current dashboard can therefore be locally synchronized and still omit a very recent bank transaction. The existing per-connection **Sync now** action also performs provider I/O inside the HTTP request, gives the browser no fleet-level progress model, and can lose a webhook-triggered follow-up when a job is already running.

The owner needs one safe action that:

1. checks every connected bank without visiting the connection-management page;
2. acknowledges quickly even when providers are slow;
3. makes partial, unsupported, delayed, and uncertain outcomes understandable; and
4. cannot multiply paid provider calls when the browser retries or several tabs act at once.

## Goals

- Provide one dashboard action that covers all active connections in both **All cards** and **All transactions**.
- Return the create request without waiting for Plaid or a bank.
- Persist enough state to survive process restarts and let the browser resume progress polling.
- Guarantee at most one `/transactions/refresh` dispatch per connection in each 15-minute eligibility window.
- Prevent duplicate runs and duplicate provider dispatches caused by double-clicks, retries, concurrent tabs, scheduler overlap, or duplicate webhooks.
- Reconcile the local cache after every eligible attempt and preserve any sync request that arrives while synchronization is running.
- Keep previous cached data usable during refresh, partial failure, and offline operation.
- Define explicit scale boundaries, recovery behavior, observability, retention, and a path beyond the current single-owner SQLite deployment.

## Non-goals

- Guaranteeing real-time bank data or that a newly made transaction will be returned.
- Waiting indefinitely for, or correlating completion to, a Plaid webhook.
- Refreshing checking, savings, investment, mortgage, or loan data.
- Adding multi-user signup, multi-tenant deployment, PostgreSQL, Redis, Celery, or a distributed queue in this feature.
- Increasing Plaid plan entitlements or enabling the separately billed Transactions Refresh add-on.
- Retrying a provider refresh whose acceptance is uncertain.
- Removing scheduled synchronization or webhook-triggered synchronization.
- Replacing the existing local-cache search and pagination APIs.

## Users and Primary Flows

### Primary user

The only supported user remains the authenticated local application owner.

### Successful check

1. The owner selects **Check for new transactions** from the dashboard.
2. The browser sends one idempotent create request and receives a durable run within 200 ms at p95, excluding network transit.
3. The button becomes **Checking…** and a polite live region announces fleet progress.
4. For each active connection, background work either requests an eligible provider refresh or records why it was skipped, then runs cursor synchronization.
5. As targets finish, the status endpoint reports their terminal outcomes and transaction change counts.
6. When the run finishes, the browser clears continuation pages, refetches both transaction-query families plus connection and limitation-alert state, and replaces persisted snapshots only with successful fresh responses.
7. The owner sees a concise result such as **Transactions updated from 2 banks** or **No new transactions found**.

### Partial or delayed check

1. Healthy connections continue even if another connection needs reconnection, does not support on-demand refresh, is cooling down, or fails.
2. The summary identifies how many banks completed and how many need attention without exposing provider internals.
3. After 90 seconds of foreground polling, the UI says **This is taking longer than expected. It will continue in the background.** It stops aggressive polling but can resume from the same run on the next dashboard visit or window focus.

### Offline flow

- The button is disabled while the browser is offline.
- Existing cached cards and transactions remain available.
- Going offline during a run does not cancel server-side work. Returning online resumes status retrieval and data invalidation.

## Requirements

### Product and UX requirements

- **RT-UX-001:** When the server reports Transactions Refresh enabled, the dashboard shall show one action labeled **Check for new transactions** whenever at least one active bank connection exists, regardless of selected dashboard view or submitted search. The action shall be absent when the feature is disabled.
- **RT-UX-002:** The action shall be disabled while offline or while an owner refresh run is active. It shall meet the existing 44-by-44 CSS-pixel touch-target requirement.
- **RT-UX-003:** Activating the action shall preserve the current dashboard view, search query, results, and cached data while work is in progress.
- **RT-UX-004:** The interface shall say **Checking…**, not **Up to date**, while work is active and shall never promise that institution data is real time.
- **RT-UX-005:** Dynamic progress and terminal summaries shall be announced through a polite live region and shall not move keyboard focus.
- **RT-UX-006:** A failed target shall not blank or roll back already cached data and shall not hide successful results from other targets.
- **RT-UX-007:** A refresh run that outlives 90 seconds of foreground polling shall continue in the background without indefinite browser polling.
- **RT-UX-008:** The freshness control shall show the most recent transaction-sync attempt across the owner's active connections, regardless of whether it was manual, scheduled, webhook-triggered, successful, or failed. It shall use relative visible copy, expose the exact localized timestamp to assistive technology and pointer hover, and show **Not checked yet** when no attempt exists.

### API and orchestration requirements

- **RT-API-001:** `POST /api/transaction-refreshes` shall require owner authentication, CSRF validation, an allowed Origin, and an `Idempotency-Key` header of 1–128 visible ASCII characters.
- **RT-API-002:** The POST shall perform no Plaid call and shall return a run representation within 200 ms at p95 on the supported local deployment.
- **RT-API-003:** `GET /api/transaction-refreshes/active` shall let the authenticated owner rediscover current work after reload or in another tab. `GET /api/transaction-refreshes/{refresh_id}` shall return only a run belonging to that owner; a missing, expired, or other-owner ID shall return the same 404 contract.
- **RT-API-004:** A repeated idempotency key during retention shall return the original run. A concurrent request with a different key while a run is active shall coalesce onto that active run rather than create another fleet dispatch.
- **RT-API-005:** Creating a run shall snapshot exactly the active connections owned by the requester. If none exist, the API shall return HTTP 409 with `code = "NO_ACTIVE_CONNECTIONS"`.
- **RT-API-006:** Run and target state values, summary counts, timestamps, stable error codes, `next_refresh_eligible_at`, and the connection-response feature capability shall be generated by the server and represented by typed OpenAPI schemas.
- **RT-API-007:** The endpoint shall not return access tokens, Plaid Item IDs, raw provider messages, transaction descriptions, or full card numbers.
- **RT-API-008:** The connections summary shall expose the nullable, owner-scoped `last_transaction_sync_attempt_at` timestamp. It shall be derived from sync audit records belonging to active connections only.

### Provider refresh requirements

- **RT-PROV-001:** Each target shall use the connection capability flag and a persisted 15-minute eligibility window before reserving a provider call.
- **RT-PROV-002:** The system shall commit the target transition from `reserved` to `dispatching` before calling `/transactions/refresh`.
- **RT-PROV-003:** Run creation shall reserve one sync generation per target. A successful provider response shall record `accepted` and its request ID, then immediately execute the reserved `/transactions/sync` pass. Completion shall not wait for a webhook.
- **RT-PROV-004:** A timeout, worker crash, or lost response after `dispatching` shall become `outcome_unknown`, count against the cooldown, continue the already reserved sync generation as sync-only reconciliation, and never automatically dispatch the refresh again.
- **RT-PROV-005:** `PRODUCTS_NOT_SUPPORTED` shall disable future refresh attempts for that connection and complete the target as `automatic_updates_only` after a sync-only pass.
- **RT-PROV-006:** A connection still inside its eligibility window shall skip the paid provider call, perform sync-only reconciliation, finish as `cooldown`, and return `next_refresh_eligible_at`.
- **RT-PROV-007:** Owner-action errors such as `ITEM_LOGIN_REQUIRED` shall finish as `reconnect_required`; transient sync failures shall use the existing capped retry policy.
- **RT-PROV-008:** The existing `POST /api/connections/{connection_id}/sync` route shall become sync-only and shall not provide a second path around refresh cooldown, reservation, or uncertainty rules.

### Queue, concurrency, and recovery requirements

- **RT-QUEUE-001:** Enqueue shall be an atomic insert-or-coalesce operation. Concurrent callers shall not surface an integrity error and shall observe the winning active job or run.
- **RT-QUEUE-002:** Every synchronization request shall advance a monotonic requested generation for its connection. A worker shall record the generation it completed and schedule another pass whenever a newer generation arrived during its work.
- **RT-QUEUE-003:** Duplicate webhook receipts may share one audit record, but every verified actionable delivery shall request a generation. Deliveries may coalesce into one higher target generation, and a webhook received during a running sync shall not be lost; at least one subsequent pass shall cover it.
- **RT-QUEUE-004:** Running jobs shall have a lease owner, random fencing token, expiry, and heartbeat. State-changing commits shall verify the fencing token.
- **RT-QUEUE-005:** An expired ordinary sync lease shall be recoverable. An expired lease with a refresh target in `dispatching` shall first mark that attempt `outcome_unknown` and recover as sync-only.
- **RT-QUEUE-006:** Disconnecting a connection before dispatch shall prevent provider I/O and finish its target as `disconnected`. Disconnecting during work shall not restore or retain token material.
- **RT-QUEUE-007:** Exactly one background worker and scheduler shall be enabled for the supported SQLite deployment. Claims, leases, and unique indexes remain correctness backstops, not an assertion that SQLite is a horizontally scalable queue.

### Cache consistency requirements

- **RT-CACHE-001:** A terminal run shall invalidate all owner-scoped TanStack Query keys rooted at `['transactions', 'search', ownerId]` and `['transactions', 'all', ownerId]`, plus connection summaries and transaction-limitation alerts.
- **RT-CACHE-002:** Refresh completion shall clear the in-memory per-card and aggregate continuation pages before fresh first pages are rendered.
- **RT-CACHE-003:** The browser shall replace `searchCache` and `allTransactionsCache` snapshots only after their corresponding fresh request succeeds. Failed refetches shall preserve the last-known-good snapshots.
- **RT-CACHE-004:** A late continuation response started before refresh completion shall be rejected by the existing generation boundary and shall not append stale rows.
- **RT-CACHE-005:** Cache invalidation shall cover both dashboard views even when only one is currently visible.

### Scale and retention requirements

- **RT-SCALE-001:** Under 100 concurrent POSTs for one owner, there shall be one active run and no more than one eligible provider dispatch per target connection in the cooldown window.
- **RT-SCALE-002:** The current product limit of one owner and four intended active bank Items, together with the 15-minute per-Item cooldown, shall remain below Plaid's documented default per-client Transactions Refresh limits without adding a distributed rate-limit service.
- **RT-SCALE-003:** Completed refresh runs and idempotency keys shall remain queryable for seven days, then be deleted by bounded batches. Cleanup shall not delete active runs.
- **RT-SCALE-004:** Moving to multiple owners, more than 50 active refresh-capable Items, more than one application host, or observed provider utilization above 50% of the account's actual limit shall require a shared provider-budget limiter and a transactional queue on PostgreSQL before rollout.
- **RT-SCALE-005:** Provider limits shall be configuration and operational data, not hard-coded claims of entitlement; rate-limit responses shall back off and emit a metric.

## UX and Content

### Placement and responsive behavior

Place the action in the dashboard freshness region adjacent to `CacheStatusBanner`, not inside either view's transaction results. It therefore remains visible and consistent while switching views. At narrow widths, the status text and action may stack, but the action remains full-label and keyboard reachable.

### Required copy

| State | Visible copy |
| --- | --- |
| Idle | **Check for new transactions** |
| Freshness helper | **Last checked: {relative time}** or **Not checked yet** |
| Active button | **Checking…** |
| Active announcement | **Checking {completed} of {total} banks for new transactions.** |
| Updated | **Transactions updated from {count} banks.** |
| No changes | **No new transactions found.** |
| Partial | **Checked {completed} of {total} banks. {attention} need attention.** |
| Unsupported only | **Checked available updates. Some banks update automatically only.** |
| Long-running | **This is taking longer than expected. It will continue in the background.** |
| Offline helper | **Connect to the internet to check for new transactions.** |

Provider error strings and Plaid rate-limit details shall not be rendered directly. Reconnect outcomes shall link to **Manage connections**.

## Data and API Contract

### Durable entities

`TransactionRefresh` is the owner-scoped parent run. It stores aggregate state, timestamps, and retention expiry. A partial unique index permits only one parent in `queued` or `running` per owner.

`TransactionRefreshRequest` maps every accepted owner/idempotency-key hash to the run returned for it. This includes keys that arrived while another run was active, so a retry of any coalesced request still resolves to the same run after it becomes terminal. Plaintext keys are never persisted.

`TransactionRefreshTarget` is one snapshotted connection in a run. It stores target state, refresh-attempt state, required sync generation, provider request ID, change counts, stable error code, next eligibility time, and timestamps. A partial unique index permits only one non-terminal target per connection.

`BankConnection` gains monotonic `sync_requested_generation` and `sync_completed_generation` values. `SyncRun` records the generation it completed. `SyncJob` gains `target_generation`, lease/fencing fields, and retains one queued/running row per connection. Creating a new refresh parent advances one generation and creates/coalesces one sync job for each target; that job's lease covers both the optional provider refresh and the required sync, so there is no second unleased queue.

### State contracts

Run states are `queued`, `running`, `succeeded`, `partial`, and `failed`.

Target states are `queued`, `refreshing`, `syncing`, `updated`, `no_changes`, `automatic_updates_only`, `cooldown`, `reconnect_required`, `outcome_unknown`, `failed`, and `disconnected`.

Refresh-attempt states are `not_attempted`, `reserved`, `dispatching`, `accepted`, `unsupported`, `cooldown`, `outcome_unknown`, and `failed`.

Terminal target states are every target state after `syncing`. A run is terminal when all targets are terminal. It is `succeeded` when all targets are `updated`, `no_changes`, `automatic_updates_only`, or `cooldown`; `failed` when no target completed acceptably; otherwise it is `partial`. The summary's `attention` count includes `reconnect_required`, `outcome_unknown`, `failed`, and `disconnected` targets.

### HTTP interface

```text
POST /api/transaction-refreshes
Idempotency-Key: <1..128 visible ASCII characters>
```

New or coalesced active work returns HTTP 202. A replay of a terminal retained run returns HTTP 200. POST uses `CreateTransactionRefreshResponse`, which contains `coalesced` and a `refresh` resource.

```text
GET /api/transaction-refreshes/{refresh_id}
```

The GET returns HTTP 200 with `TransactionRefreshResponse`.

```text
GET /api/transaction-refreshes/active
```

The active lookup returns HTTP 200 with `TransactionRefreshResponse` or HTTP 204 when the owner has no active run. The literal `/active` route is registered before `/{refresh_id}`.

```json
{
  "coalesced": false,
  "refresh": {
    "id": "uuid",
    "state": "running",
    "created_at": "2026-09-03T14:00:00Z",
    "started_at": "2026-09-03T14:00:01Z",
    "finished_at": null,
    "expires_at": "2026-09-10T14:00:00Z",
    "summary": {
      "total": 4,
      "completed": 1,
      "updated": 1,
      "attention": 0,
      "added": 2,
      "modified": 0,
      "removed": 0
    },
    "targets": [
      {
        "connection_id": "uuid",
        "bank": "chase",
        "state": "updated",
        "refresh_outcome": "accepted",
        "next_refresh_eligible_at": "2026-09-03T14:15:02Z",
        "added": 2,
        "modified": 0,
        "removed": 0,
        "error_code": null
      }
    ]
  }
}
```

The response uses stable application codes. It does not expose `provider_request_id`; that value is retained only for redacted operational troubleshooting.

## Rules and Edge Cases

- Provider refresh acceptance means that Plaid accepted the request, not that a particular transaction exists or that every institution returned real-time data.
- Webhooks are dirty signals. They advance a connection generation and may trigger another sync pass, but are not tied to a particular refresh-run completion.
- A successful sync with zero patches produces `no_changes` after an accepted refresh, `cooldown` after an eligibility skip, or `automatic_updates_only` after an unsupported skip.
- If sync applies patches after an uncertain provider attempt, counts are retained but the target remains `outcome_unknown`; the system must not hide dispatch uncertainty.
- A repeated idempotency key is scoped to the owner. Keys are stored only as SHA-256 hashes.
- Every dashboard load or window-focus recovery may discover an active run through the active endpoint; the browser does not need to persist a refresh ID or idempotency key.
- A run's target set never expands after creation. A connection added later participates in the next run; a disconnected target is safely skipped.
- Searches submitted during an active run continue using the existing cache. Terminal invalidation preserves the submitted query and selected view.
- Session storage may contain the same owner-visible transaction fields it contains today, but never refresh idempotency keys or provider request IDs.
- Demo and test gateways shall produce deterministic outcomes without network access or paid calls.

## Acceptance Criteria

- **AC-001 (RT-UX-001–008):** Given at least one active connection, the dashboard in either view exposes one accessible **Check for new transactions** action; offline and active states disable it, progress is announced, cached results remain visible, the latest attempted sync is shown with relative and exact time, and foreground polling stops after 90 seconds with background-work copy.
- **AC-002 (RT-API-001–008):** Given authenticated, anonymous, cross-owner, missing-key, repeated-key, and concurrent requests, the API enforces auth/CSRF/Origin, owner-safe 404s, required idempotency, one active run, typed responses including the owner-scoped latest attempt, and no inline provider I/O.
- **AC-003 (RT-PROV-001–008):** Given eligible, cooling-down, unsupported, reconnect-required, failed, timed-out, and disconnected connections, each target follows the pinned attempt transitions, syncs when safe, never redispatches an unknown attempt, and the legacy connection endpoint cannot bypass the rules.
- **AC-004 (RT-QUEUE-001–007):** Given simultaneous enqueue calls, a webhook during sync, worker termination before and after provider dispatch, and an expired lease, work coalesces atomically, generations preserve follow-up work, leases recover safely, and fencing rejects stale commits.
- **AC-005 (RT-CACHE-001–005):** Given loaded continuation pages and persisted snapshots in both dashboard views, a terminal run resets pagination, rejects late pages, invalidates both transaction roots plus connections and alerts, and replaces only successfully refetched snapshots.
- **AC-006 (RT-SCALE-001–005):** Given 100 concurrent create requests and four active Items, one run is created, provider calls remain bounded by per-Item eligibility, terminal data expires in bounded batches, and scale-trigger configuration/metrics identify when shared infrastructure is required.
- **AC-007:** Given keyboard-only use, axe analysis, reduced motion, and a 280-pixel viewport, the action, progress, summaries, reconnect link, disabled explanation, and layout meet the product's WCAG 2.2 AA requirements.
- **AC-008:** Given the existing grouped search, aggregate table, limitation alerts, connection management, webhook, scheduler, and preview flows, their unaffected contracts and tests continue to pass.

## Observability and Privacy

Emit structured counters for runs created/coalesced/completed, target outcomes, refresh dispatches, refresh rate limits, sync reruns caused by newer generations, lease recoveries, stale-fence rejections, and cleanup deletions. Emit histograms for POST acknowledgement latency, target duration, run duration, provider refresh latency, and sync latency. Logs may include owner-safe internal IDs, target state, stable error code, and Plaid request ID; they shall exclude access tokens, idempotency keys, raw webhook bodies, transaction text, amounts, and provider error messages.

Alert locally when an active run exceeds 15 minutes, a running lease repeatedly expires, outcome-unknown targets occur, rate-limit responses occur, or cleanup fails on three consecutive sweeps. Existing health and logs remain sufficient for the single-owner deployment; no third-party analytics service is introduced.

## Rollout or Migration

1. Add one additive Alembic migration for refresh-run/request/target tables, sync generations, and lease fields. Existing transactions and cursors require no data rewrite; generation backfills follow the migration contract in the implementation plan.
2. Ship backend orchestration and the API behind `ENABLE_TRANSACTION_REFRESH=false` by default outside demo/test. Startup validates that Transactions Refresh is intentionally enabled before production dispatches are possible.
3. Enable deterministic demo/test behavior and complete concurrency, crash-recovery, API, accessibility, and cache-invalidation verification.
4. Confirm the Plaid account has Transactions Refresh access and accepts its separate billing before enabling production.
5. Enable for the local owner and monitor target outcomes, durations, rate limits, and unknown attempts through at least ten runs.

Rollback disables new run creation and hides the action while allowing already queued work to finish sync-only. The additive tables and columns remain in place so rollback does not discard audit or recovery state.

## Open Questions

None. The implementation shall use the approved decisions in this version. A change to endpoint shape, state semantics, cooldown, polling window, retention, or scale triggers requires a PRD revision before code changes.

## References

- [Plaid Transactions API](https://plaid.com/docs/api/products/transactions/) — refresh latency, add-on access, Capital One limitation, and sync/refresh behavior; verified September 3, 2026.
- [Plaid Transactions webhooks](https://plaid.com/docs/transactions/webhooks/) — `SYNC_UPDATES_AVAILABLE` semantics after refresh; verified September 3, 2026.
- [Plaid rate-limit documentation](https://plaid.com/docs/errors/rate-limit-exceeded/) — default per-Item and per-client limits plus billing guidance for user-triggered refresh; verified September 3, 2026.
