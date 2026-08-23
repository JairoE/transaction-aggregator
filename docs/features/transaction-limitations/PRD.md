# Transaction Limitations Product Requirements Document

- **Status:** Proposed for implementation
- **Version:** 1.0
- **Date:** August 22, 2026
- **Audience:** Product owner, designers, implementers, and reviewers
- **Parent product:** [Transaction Aggregator](../../PRD.md)

## 1. Executive Summary

Transaction Limitations lets the application owner save transaction-count rules and see informational alerts on the dashboard when cached transactions meet those rules. A rule combines a literal keyword or phrase, a count threshold, a card scope, and a time window.

The feature does not authorize, decline, block, or otherwise affect transactions. “Limit” means an owner-defined informational threshold only. The app evaluates rules independently for each targeted credit card and activates an alert when that card's matching count is greater than or equal to the threshold.

Examples:

- A `Paze` rule with threshold `10`, all cards, and all available history creates one alert for every card that independently has at least 10 matching cached transactions.
- A `dunkin’ donuts` rule with threshold `5`, all cards, and a rolling five-day window creates one alert for every card that independently has at least five matching cached transactions in the inclusive five-day window.

## 2. Problem, User, and Goal

### Problem

Search answers “where are these transactions?” only after the owner remembers to look. The owner also wants durable watch rules that continuously answer “which cards have reached a transaction-count threshold?” without repeating searches and manually counting per-card results.

### Primary User

The only user remains the authenticated application owner defined in the parent PRD. Multi-user rule sharing, household collaboration, and public alert subscriptions are not part of this feature.

### How Might We

How might we let the owner define reusable per-card transaction-count thresholds and immediately see which cards meet them, while preserving the app's local-first operation and literal search semantics?

### Goal

Provide a reliable, locally evaluated rule system that:

1. Creates and manages rules on a dedicated `/transaction-limitations` page.
2. Targets all active cards dynamically or an explicit set of active cards.
3. Supports all available history, rolling-day, and fixed-date windows.
4. Counts pending transactions and reports how many matches are pending.
5. Shows active, per-card informational alerts on the dashboard.
6. Remains correct after transaction additions, modifications, removals, and calendar-day changes.

## 3. Product Direction

### Recommended Direction: Saved Rules with Query-Time Evaluation

Persist rule definitions, but compute alert instances from the current local transaction cache whenever alerts are requested. This makes an alert a derived view rather than durable event state. It avoids stale counters when Plaid modifies or removes a transaction and naturally lets rolling windows change as calendar days pass.

Evaluation belongs behind a dedicated service and API contract rather than inside dashboard components or the existing search response. That boundary permits a later materialized-count implementation without changing the management or dashboard experience if measured performance requires it.

### Alternatives Considered

| Direction | Benefit | Why not selected |
| --- | --- | --- |
| Saved searches with visible counts | Smallest implementation | A count is not an explicit threshold state and does not satisfy the alert job. |
| Materialized alert events updated during sync | Fast dashboard reads and alert history | Modified/removed transactions and rolling windows require complex correction and expiration logic before product value is proven. |
| External notifications | Alerts can reach the owner away from the dashboard | Email, push, scheduling, delivery state, and secrets expand the product beyond its local-first dashboard use case. |

## 4. Capability Map

| Module ID | Responsibility | Depends on |
| --- | --- | --- |
| `transaction-limit-rules` | Persist, validate, list, create, edit, enable/disable, and delete owner rules. | Existing owner and card models |
| `rule-evaluation` | Match current cached transactions, apply card and date scopes, and derive per-card active alert instances. | `transaction-limit-rules`, existing transaction search index |
| `limitations-ui` | Manage rules on `/transaction-limitations` and render active alerts on `/dashboard`. | `transaction-limit-rules`, `rule-evaluation` |

Build order: `transaction-limit-rules` → `rule-evaluation` → `limitations-ui`.

The three date-window variants extend `rule-evaluation` in strict order: all available history → rolling days → fixed dates. No commit may introduce more than one window variant.

## 5. Product Principles

- **Inform, never imply control.** Copy must say that rules are informational and cannot block card activity.
- **Per-card means per-card.** An all-cards rule fans out to cards; it never combines card counts into one threshold.
- **Current cache is the truth.** Evaluation never calls Plaid or a bank and must work offline.
- **Literal means literal.** Rule matching reuses existing normalized, case-insensitive substring semantics; punctuation is text, not query syntax.
- **Derived alerts stay current.** Alert state is computed from current rules, current transactions, and the current calendar date.
- **Pending is visible uncertainty.** Pending matches count toward the threshold, and every alert discloses its pending-match count.
- **Future cards inherit fleet rules.** “All cards” is a dynamic scope, not a snapshot of card IDs at rule creation.

## 6. Scope

### In Scope

- Authenticated owner-only rule management.
- Rule creation, listing, editing, enable/disable, and deletion.
- Required literal keyword or phrase and integer count threshold.
- Dynamic all-card scope and explicit selected-card scope.
- All available cached history.
- Inclusive rolling windows expressed as the last `N` calendar days.
- Inclusive fixed start and end dates.
- Pending transactions included in total matches and separately counted.
- Active per-card dashboard alerts.
- Offline evaluation from SQLite.
- Accessible loading, empty, validation, success, and failure states.
- Backend unit/API/migration tests, frontend component tests, generated API types, and an end-to-end owner flow.

### Not Doing (and Why)

- **Blocking or declining transactions** — this app has no card-control or money-movement capability.
- **Cross-card aggregate thresholds** — the approved behavior evaluates each card independently.
- **Email, SMS, push, or webhook delivery** — dashboard-only alerts validate the core job without adding delivery infrastructure.
- **Alert acknowledgement, dismissal, or firing history** — alerts are current derived states, not durable events.
- **Amount, category, merchant-ID, or Boolean rule builders** — keyword/phrase count is the minimum coherent rule language.
- **Scheduled digests or escalation levels** — no notification channel exists in scope.
- **Regex, fuzzy, token, or semantic matching** — these would diverge from the existing search contract.
- **Rule templates, import/export, or sharing** — single-owner CRUD is sufficient for the first version.
- **Native mobile surfaces** — the parent product remains a web application.

## 7. Definitions and Evaluation Semantics

### Rule

A rule contains:

| Field | Contract |
| --- | --- |
| `keyword` | Required display value; trimmed; 1–100 characters after trimming. |
| `normalized_keyword` | Server-generated using the existing `normalize_query` behavior; never accepted from the client. |
| `threshold` | Required integer from 1 through 10,000 inclusive. |
| `card_scope` | `all_cards` or `selected_cards`. |
| `card_ids` | Empty for `all_cards`; one or more active, owner-owned card IDs for `selected_cards`. |
| `window` | Exactly one discriminated variant: `all_time`, `rolling`, or `fixed`. |
| `is_enabled` | Defaults to `true`; disabled rules are stored and editable but never evaluated into alerts. |

### Matching

- Matching is a case-insensitive literal substring across the existing normalized `search_text`, which contains merchant name, Plaid transaction name, and original statement description.
- Unicode normalization, whitespace collapsing, the 100-character maximum, FTS5 trigram use for strings of three or more characters, and escaped fallback matching for shorter strings must remain consistent with transaction search.
- Punctuation is literal. `dunkin’ donuts` and `dunkin' donuts` are distinct strings unless the cached provider text itself normalizes them to the same characters.
- Every active cached transaction may match, including pending transactions.

### Card Scope

- `all_cards` evaluates every active credit card belonging to the owner through an active bank connection at request time.
- `selected_cards` evaluates only the saved active card IDs that still belong to the owner.
- Counts are grouped by card before applying the threshold. Counts from different cards are never added together.
- A newly connected card automatically participates in every enabled `all_cards` rule.
- If a selected card is removed, its association is removed with the card. The rule remains visible. If no selected cards remain, the management page marks the rule as needing card selection, and it produces no alerts until edited.

### Effective Transaction Date

- The effective date is `posted_date` when present; otherwise it is `authorized_date`.
- All-time evaluation counts matching cached transactions even if both dates are absent.
- Rolling and fixed windows exclude a transaction when both dates are absent because window membership cannot be established.

### Date Windows

- **All available history (`all_time`):** no date predicate; “all” means every matching transaction currently retained in the local cache, subject to the parent product's provider-history limits.
- **Rolling (`rolling`):** `days` is an integer from 1 through 730. “Last N days” is inclusive of the host computer's current calendar date. A five-day window evaluated on August 22 includes August 18 through August 22.
- **Fixed (`fixed`):** `start_date` and `end_date` are required ISO dates and both boundaries are inclusive. `start_date` must be less than or equal to `end_date`.
- The evaluation service accepts an explicit `as_of_date` internally so rolling-window tests are deterministic; production requests use the host's current local date, consistent with the app's single-owner local deployment.

### Alert Activation

- An alert instance is derived for one rule and one card when `match_count >= threshold`.
- `pending_count` is the number of matching transactions in `match_count` whose current `pending` value is true.
- An alert deactivates automatically when the current match count falls below the threshold, the window advances, the rule is disabled/deleted, or its card is no longer targeted.
- Alerts sort by the existing card order, then oldest rule creation time, then rule ID for deterministic ties.

## 8. Core User Journeys

### Create an All-Time Rule

1. The owner opens `/transaction-limitations` from the application navigation.
2. The page explains that limits are informational and cannot block transactions.
3. The owner enters `Paze`, threshold `10`, selects all cards, selects all available history, and saves.
4. The saved rule appears in the management list and can be edited, disabled, or deleted.
5. On `/dashboard`, each card with at least 10 matching cached transactions shows its own alert; cards below 10 show no alert for that rule.

### Create a Rolling Rule

1. The owner enters `dunkin’ donuts`, threshold `5`, selects all cards, selects “Last N days,” enters `5`, and saves.
2. The rule evaluates the host's current date plus the previous four dates.
3. Each qualifying card shows an alert with total and pending match counts plus “last 5 days.”

### Create a Fixed-Date Rule

1. The owner chooses selected cards and a fixed start/end range.
2. The form rejects an end date before the start date without submitting.
3. Each selected qualifying card shows an alert with the inclusive date range.

### Edit or Disable a Rule

1. The owner edits any rule field or disables the rule.
2. The server validates the merged rule atomically.
3. Dashboard alert data is invalidated and refetched; stale alert instances disappear without a full-page reload.

## 9. Functional Requirements

### 9.1 Rule Management

- **FR-LIM-RULE-001:** The application shall expose a protected `/transaction-limitations` route and navigation entry.
- **FR-LIM-RULE-002:** The page shall explain that transaction limits are informational alerts and cannot block card activity.
- **FR-LIM-RULE-003:** The owner shall be able to list, create, edit, enable/disable, and delete rules.
- **FR-LIM-RULE-004:** Rule writes shall require the existing authenticated session, allowed Origin, and CSRF token.
- **FR-LIM-RULE-005:** The server shall generate IDs, normalized keywords, and timestamps; clients shall not set them.
- **FR-LIM-RULE-006:** The server shall validate all cross-field invariants after merging a PATCH request with the stored rule.
- **FR-LIM-RULE-007:** Selected card IDs shall be deduplicated and verified as active cards owned by the authenticated owner.
- **FR-LIM-RULE-008:** A rule owned by another owner or an unknown rule ID shall not be readable or mutable through the authenticated owner's requests.
- **FR-LIM-RULE-009:** Deleting a rule shall remove its card associations and derived alerts immediately.
- **FR-LIM-RULE-010:** Disconnecting a selected card shall not delete the rule; the page shall show when a selected-card rule has no remaining target cards.

### 9.2 Matching and Counts

- **FR-LIM-MATCH-001:** Evaluation shall read only local SQLite tables and shall never call Plaid or a bank.
- **FR-LIM-MATCH-002:** Rule matching shall reuse the existing normalized literal-substring search contract.
- **FR-LIM-MATCH-003:** Evaluation shall include pending transactions in `match_count`.
- **FR-LIM-MATCH-004:** Evaluation shall return `pending_count` separately for every active alert.
- **FR-LIM-MATCH-005:** Evaluation shall group by rule and card before comparing count to threshold.
- **FR-LIM-MATCH-006:** One enabled all-card rule shall evaluate newly connected active credit cards without modifying the rule.
- **FR-LIM-MATCH-007:** Modified and removed cached transactions shall affect the next alert evaluation without repair jobs or stored counter reconciliation.

### 9.3 Date Windows

- **FR-LIM-WIN-001:** All-time rules shall evaluate every matching transaction retained in the local cache without a date predicate.
- **FR-LIM-WIN-002:** Rolling rules shall support 1–730 inclusive calendar days using the effective transaction date.
- **FR-LIM-WIN-003:** A rolling window shall include both its calculated start date and its `as_of_date`.
- **FR-LIM-WIN-004:** Fixed rules shall require inclusive `start_date` and `end_date` values with `start_date <= end_date`.
- **FR-LIM-WIN-005:** Rolling and fixed rules shall exclude transactions without an effective date.
- **FR-LIM-WIN-006:** All-time, rolling, and fixed support shall be introduced in successive, separate commits; no commit shall add more than one date-window variant.

### 9.4 Dashboard Alerts

- **FR-LIM-ALERT-001:** The dashboard shall request active alert instances independently of the submitted transaction-search query.
- **FR-LIM-ALERT-002:** A card shall display an alert for each targeted rule whose current count is greater than or equal to its threshold.
- **FR-LIM-ALERT-003:** An alert shall show the rule keyword, current match count, threshold, pending count, and human-readable window.
- **FR-LIM-ALERT-004:** When `pending_count` is zero, the alert shall explicitly say `0 pending`; pending status shall not rely on color alone.
- **FR-LIM-ALERT-005:** Dashboard search terms shall neither filter nor alter limitation alerts.
- **FR-LIM-ALERT-006:** Failure to load alerts shall show a scoped, retryable message while leaving cached transaction cards and search usable.
- **FR-LIM-ALERT-007:** The frontend shall refetch alerts on dashboard mount, window focus, at most every 60 seconds while visible, and after successful rule writes.
- **FR-LIM-ALERT-008:** A dashboard with no active alerts shall not reserve an empty alert region inside card panels.

### 9.5 Management Experience

- **FR-LIM-UX-001:** The form shall reveal only fields applicable to the selected card scope and window variant.
- **FR-LIM-UX-002:** All-card scope shall display that future connected cards are included automatically.
- **FR-LIM-UX-003:** Selected-card scope shall require at least one active card before submission.
- **FR-LIM-UX-004:** Validation errors shall be associated with fields and summarized for assistive technology.
- **FR-LIM-UX-005:** Saving, updating, toggling, and deleting shall expose pending state and prevent duplicate submissions.
- **FR-LIM-UX-006:** Delete shall require confirmation naming the rule keyword.
- **FR-LIM-UX-007:** The page shall provide an explicit empty state with a create-rule action.
- **FR-LIM-UX-008:** The dashboard and management page shall pass the existing axe smoke-test standard and remain usable at the parent PRD breakpoints.

## 10. API Contract

All JSON follows the repository's existing `snake_case` convention and stable `{ "code", "message" }` error body.

### Endpoints

| Method | Path | Success | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/transaction-limitations` | `200 TransactionLimitationListResponse` | List owner rules plus active cards available to the form. |
| `POST` | `/api/transaction-limitations` | `201 TransactionLimitationResponse` | Create one rule. Unsafe to retry without confirming the first request failed. |
| `PATCH` | `/api/transaction-limitations/{rule_id}` | `200 TransactionLimitationResponse` | Partially update one rule, then validate the merged result. |
| `DELETE` | `/api/transaction-limitations/{rule_id}` | `204` | Delete one rule and its associations. |
| `GET` | `/api/transaction-limit-alerts` | `200 TransactionLimitAlertListResponse` | Return only currently active per-card alert instances. |

List pagination is deliberately omitted in v1 because this private single-owner product is expected to hold tens, not thousands, of rules. The service and response envelope must remain extensible so cursor fields can be added without changing existing rule objects if measured usage invalidates that assumption.

### Window Input Union

```python
class AllTimeWindow(BaseModel):
    type: Literal["all_time"]


class RollingWindow(BaseModel):
    type: Literal["rolling"]
    days: int = Field(ge=1, le=730)


class FixedWindow(BaseModel):
    type: Literal["fixed"]
    start_date: date
    end_date: date


TransactionWindow = Annotated[
    AllTimeWindow | RollingWindow | FixedWindow,
    Field(discriminator="type"),
]
```

### Create Example

```json
{
  "keyword": "dunkin’ donuts",
  "threshold": 5,
  "card_scope": "all_cards",
  "card_ids": [],
  "window": {
    "type": "rolling",
    "days": 5
  },
  "is_enabled": true
}
```

### Active Alert Example

```json
{
  "alerts": [
    {
      "rule_id": "0e0f2d37-2225-4456-a6aa-272f9c6f0954",
      "keyword": "dunkin’ donuts",
      "threshold": 5,
      "card": {
        "id": "card-1",
        "connection_id": "conn-1",
        "bank": "capital-one",
        "bank_display_name": "Capital One",
        "name": "Venture",
        "official_name": "Capital One Venture",
        "mask": "4812",
        "state": "ready",
        "last_successful_sync_at": "2026-08-22T13:00:00Z"
      },
      "match_count": 6,
      "pending_count": 2,
      "window": {
        "type": "rolling",
        "days": 5,
        "effective_start_date": "2026-08-18",
        "effective_end_date": "2026-08-22"
      }
    }
  ],
  "evaluated_at": "2026-08-22T13:15:00Z",
  "as_of_date": "2026-08-22",
  "cache_as_of": "2026-08-22T13:00:00Z"
}
```

### Validation and Errors

- `422 REQUEST_INVALID`: malformed field, threshold outside range, invalid window fields, end before start, scope/card mismatch, inactive card, or card not owned by the owner.
- `404 TRANSACTION_LIMITATION_NOT_FOUND`: unknown or non-owned rule ID on PATCH/DELETE.
- `401 AUTH_REQUIRED`, `403 CSRF_INVALID`, and `403 ORIGIN_INVALID`: existing authentication protections.
- `500` responses must not expose rule keywords, transaction descriptions, SQL, or internal exception text.

## 11. Data Model

### `transaction_limitations`

| Column | Type / constraint |
| --- | --- |
| `id` | UUID string primary key |
| `owner_id` | FK `owners.id`, indexed, cascade delete |
| `keyword` | string(100), non-empty trimmed display value |
| `normalized_keyword` | string(100), non-empty, server-generated |
| `threshold` | integer, check `1 <= threshold <= 10000` |
| `card_scope` | string enum check: `all_cards`, `selected_cards` |
| `window_type` | string enum check: `all_time`, `rolling`, `fixed` |
| `rolling_days` | nullable integer, check null or `1 <= rolling_days <= 730` |
| `start_date` | nullable date |
| `end_date` | nullable date |
| `is_enabled` | non-null Boolean, default true |
| `created_at`, `updated_at` | existing timezone-aware timestamp convention |

Table checks enforce valid window column combinations: all-time has no window values, rolling has only `rolling_days`, and fixed has only both dates with start no later than end.

### `transaction_limitation_cards`

| Column | Type / constraint |
| --- | --- |
| `limitation_id` | FK `transaction_limitations.id`, cascade delete |
| `card_account_id` | FK `card_accounts.id`, cascade delete |

The pair is the primary key. `all_cards` rules have no association rows. Application validation—not the join table alone—enforces that `selected_cards` has at least one card at write time.

No alert table is created in v1.

## 12. Architecture and Data Flow

1. The management page reads rules and active card choices from `GET /api/transaction-limitations`.
2. Pydantic validates request shape; the rule service normalizes the keyword, merges PATCH state, validates ownership/cross-field invariants, and commits the rule plus card associations atomically.
3. The dashboard requests `GET /api/transaction-limit-alerts` independently of transaction search.
4. The evaluation service loads enabled owner rules and executes one grouped count query per rule—not per card—using the existing FTS5/escaped-short-query strategy, owner/card predicates, and the variant's date predicate.
5. The service filters grouped rows with `match_count >= threshold`, includes `pending_count`, and returns deterministic active alert instances.
6. The dashboard joins alerts to existing card groups by `card.id` and renders them inside the relevant card panel.

This O(number of enabled rules) query model is appropriate for a single owner with a small rule set. Performance must be measured with 100 enabled rules and 100,000 cached transactions. Materialized counts may be proposed in a future ADR only if the performance target is missed; they are not a pre-emptive v1 dependency.

## 13. Non-Functional Requirements

- **NFR-LIM-001 Local-first:** Alert evaluation succeeds without network access and performs no provider calls.
- **NFR-LIM-002 Performance:** With 100 enabled rules, eight active cards, and 100,000 cached transactions, `GET /api/transaction-limit-alerts` shall complete in under 500 ms at p95 on the supported local deployment after a warm SQLite page cache.
- **NFR-LIM-003 Query shape:** Evaluation shall issue at most one count query per enabled rule plus bounded rule/card metadata queries; it shall never issue one query per rule-card pair.
- **NFR-LIM-004 Security:** Every rule read/write is owner-scoped; mutating routes retain session, CSRF, and Origin protections.
- **NFR-LIM-005 Privacy:** Logs shall not contain keywords, card names/masks, transaction text, or rule request bodies.
- **NFR-LIM-006 Accessibility:** Both feature surfaces shall pass the existing axe smoke test, use text in addition to color, and support keyboard-only CRUD.
- **NFR-LIM-007 Resilience:** Alert API failure shall not prevent transaction search or cached card rendering.
- **NFR-LIM-008 Compatibility:** The change shall add endpoints and fields without changing existing search endpoint behavior.
- **NFR-LIM-009 Determinism:** Date tests inject `as_of_date`; result ordering has explicit stable ties.

## 14. Success Criteria and Acceptance Examples

The feature is complete when all conditions below pass.

### Example A: Paze Across Any Date

Given two active cards where card A has 10 matching `Paze` transactions and card B has 9, and an enabled all-card/all-time rule with threshold 10:

- Card A has exactly one active alert showing `10 matches`, the configured threshold, and its pending count.
- Card B has no alert for the rule.
- Adding a matching transaction to card B makes its alert appear on the next evaluation.
- Removing a matching transaction from card A makes its alert disappear on the next evaluation.

### Example B: Dunkin’ Donuts in the Last Five Days

Given `as_of_date = 2026-08-22`, a rolling five-day rule for `dunkin’ donuts`, and one card with matches on August 18, 19, 20, 21, and 22:

- All five boundary-inclusive matches count.
- A match on August 17 does not count.
- The card alerts when threshold is 5.
- If two of the five are pending, the alert shows `5 matches · 2 pending`.

### Example C: Fixed Inclusive Dates

Given a fixed window from `2026-07-01` through `2026-07-31`:

- Matches on July 1 and July 31 count.
- Matches on June 30 and August 1 do not count.
- A transaction without posted or authorized date does not count.

### Overall Definition of Done

- All functional and non-functional requirements map to implementation tasks and tests.
- All-time, rolling, and fixed window support land in separate successive commits.
- Migration upgrade and downgrade tests pass.
- Backend service and API tests cover ownership, validation, literal matching, card fan-out, pending counts, threshold equality, and each date boundary.
- Frontend tests cover CRUD, card selection, all window forms, alert rendering, empty/error states, pending copy, and accessibility.
- The generated OpenAPI document and TypeScript types match the implemented schemas.
- An end-to-end test creates a rule, observes a qualifying dashboard card alert, edits/disables it, and observes its removal.
- `make check` and the focused end-to-end flow pass after the pre-existing baseline failure in `tests/test_static_app.py::test_api_routes_never_fall_through_to_the_spa` is resolved or explicitly waived by the owner.

## 15. Tech Stack and Commands

### Tech Stack

- Python 3.12, FastAPI 0.116+, Pydantic, SQLAlchemy 2, Alembic, SQLite/FTS5.
- React 19, TypeScript 5.7, Vite 6, TanStack Query 5.
- pytest/pytest-asyncio, Vitest/Testing Library/MSW, Playwright, axe-core.
- No new runtime dependency is required or approved by this PRD.

### Commands

```bash
# Apply migrations
make migrate

# Focused backend tests
uv run --directory backend pytest tests/migrations/test_transaction_limitations.py tests/services/test_limitation_service.py tests/api/test_limitations.py -q

# Focused frontend tests
pnpm --dir frontend test -- src/limitations/transaction-limitations.test.tsx src/dashboard/transaction-limit-alerts.test.tsx

# Regenerate the OpenAPI contract and TypeScript types
pnpm --dir frontend generate:api

# Full repository gate
make check

# End-to-end flow
pnpm --dir frontend e2e -- transaction-limitations.spec.ts

# Development server
make dev

# Production-like local server
make serve
```

## 16. Project Structure

```text
backend/app/models.py                         # Rule and rule-card persistence models
backend/app/schemas.py                        # Typed rule/window/alert API contracts
backend/app/services/limitation_service.py    # Rule CRUD and query-time evaluation
backend/app/api/limitations.py                # Protected REST endpoints
backend/alembic/versions/0003_*.py            # Rule schema migration
backend/tests/{migrations,services,api}/       # Backend feature tests
frontend/src/limitations/                     # Management page, form, list, API helpers
frontend/src/dashboard/                       # Per-card alert presentation
frontend/src/api/{openapi.json,generated.ts}  # Generated contract artifacts
frontend/e2e/transaction-limitations.spec.ts  # Owner flow
docs/features/transaction-limitations/        # PRD
docs/superpowers/plans/                       # Implementation plan
```

## 17. Code Style

Follow current repository conventions: Python type hints and immutable service result dataclasses; Pydantic at API boundaries; React function components; generated API types rather than handwritten response duplicates; explicit accessible labels; snake_case JSON.

```python
@dataclass(frozen=True)
class ActiveTransactionLimitAlert:
    rule_id: str
    card: CardRow
    keyword: str
    threshold: int
    match_count: int
    pending_count: int
    window: EvaluatedWindow


async def evaluate_active_alerts(
    self,
    owner_id: str,
    *,
    as_of_date: date | None = None,
) -> list[ActiveTransactionLimitAlert]:
    """Derive active per-card alerts from the current local cache."""
```

## 18. Testing Strategy

- **Migration tests:** tables, indexes, foreign keys, check constraints, upgrade/downgrade, and cascade behavior.
- **Service tests:** normalization parity, threshold equality, independent card grouping, all-card dynamism, selected-card ownership, pending totals, all three windows, null dates, disabled rules, and transaction mutation/removal correctness.
- **API tests:** authentication, CSRF/Origin, typed CRUD contracts, PATCH merge validation, not-found isolation, and alert response metadata.
- **Frontend tests:** progressive form fields, validation, mutation pending states, query invalidation, scoped dashboard failure, per-card alerts, literal copy, zero pending, and axe.
- **Contract test:** regenerate OpenAPI and ensure the tracked artifacts are clean.
- **Performance test:** deterministic synthetic local dataset with 100 rules and 100,000 transactions; record warm-cache p95 outside the default correctness suite if it makes CI unstable.
- **End-to-end test:** create → dashboard alert → edit/disable → alert removed.

## 19. Boundaries

### Always Do

- Reuse `normalize_query` and existing FTS/escaped literal matching behavior.
- Scope all rule/card access through the authenticated owner.
- Treat alerts as derived state and include pending matches.
- Validate cross-field rule invariants on create and after PATCH merge.
- Use migrations for schema changes and regenerate API artifacts after contracts change.
- Implement with tests first and run focused checks before each atomic commit.
- Keep all-time, rolling, and fixed window work in separate successive commits.

### Ask First

- Add any runtime dependency.
- Change existing transaction search semantics or the `search_text` index.
- Materialize alerts or add a background evaluation job.
- Add a configured owner timezone instead of the local host calendar.
- Introduce external notifications or alert history.
- Change the parent PRD's transaction retention or provider scope.

### Never Do

- Claim that a rule blocks or controls card transactions.
- Combine counts from different cards for threshold evaluation.
- Call Plaid during rule reads or alert evaluation.
- Log rule keywords or matching transaction text.
- Trust client-supplied owner IDs, normalized keywords, counts, or alert state.
- Remove or weaken authentication, CSRF, Origin, accessibility, or existing search tests.

## 20. Assumptions to Validate After Launch

- **Must be true:** Per-card count alerts save enough repeated searching/counting to remain useful. Validate through continued owner usage before expanding the rule language.
- **Should be true:** Query-time evaluation remains below the 500 ms p95 target at the documented local scale. Measure before considering materialization.
- **Might be true:** The owner eventually wants external delivery or alert history. Do not build either until dashboard alert usage demonstrates the need.

No product decision remains blocking for implementation. Any change to the approved semantics requires updating this PRD before code.
