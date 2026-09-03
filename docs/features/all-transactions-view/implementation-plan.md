# All Transactions View Implementation Plan

**Goal:** Add an accessible dashboard toggle and a globally sorted, paginated table of cached transactions across every active credit card.

**Architecture:** Extend the existing `SearchService` and search router with one owner-scoped aggregate read endpoint backed by the same local transaction-match predicate and signed-cursor pattern as grouped search. The React dashboard will select exactly one query path from a URL-backed view state, keep the existing card grid intact, and render aggregate pages through a dedicated semantic table with a view-specific session cache.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy 2 async, SQLite/FTS5, React 19, TypeScript, TanStack Query, React Router, Vitest, Testing Library, MSW, axe-core, Playwright, OpenAPI TypeScript

**Spec:** `docs/features/all-transactions-view/PRD.md`

## Global Constraints

The following constraints are copied verbatim from the PRD:

- The existing card grid remains the default and continues to behave exactly as it does today.
- Both views use the same submitted search term and read only from the local SQLite cache.
- Full PAN data shall never be requested, stored, logged, or rendered.
- Search shall still execute only on explicit submit or Enter; typing alone and switching views shall not write search history.
- Existing routes and response contracts for `/api/transactions/search` and `/api/cards/{card_id}/transactions` shall remain backward compatible.
- No database migration or data backfill is required.

## Assumptions Resolved for This Plan

The plan implements the PRD's proposed v1 answers unless the owner changes them during review:

1. `•••• {mask}` satisfies the card-number column; no full PAN exists in the system.
2. All cards is the default. Only the URL stores view selection: `view=transactions` selects the table and absence of `view` selects cards.
3. The table includes the existing Set alert transaction action.
4. The table is newest-first and not user-sortable in v1.

## File Structure

### Backend

| Path | Change | Responsibility |
| --- | --- | --- |
| `backend/app/services/search_service.py` | Modify | Add aggregate result types, query-bound signed cursor support, fleet metadata, owner-scoped count, and globally ordered page query while reusing `normalize_query` and `transaction_match_filter`. |
| `backend/app/schemas.py` | Modify | Add `AllTransactionRow` and `AllTransactionsResponse` wire models. |
| `backend/app/api/search.py` | Modify | Serialize aggregate rows and expose authenticated `GET /api/transactions`. |
| `backend/tests/services/test_search_service.py` | Modify | Prove owner isolation, active-card filtering, search semantics, global ordering, null-date pagination, counts, freshness, and cursor validation. |
| `backend/tests/api/test_search.py` | Modify | Prove the HTTP contract, authentication, validation, stable errors, and cache-only behavior. |

### Frontend

| Path | Change | Responsibility |
| --- | --- | --- |
| `frontend/src/api/openapi.json` | Regenerate | Record the aggregate endpoint and response schemas. |
| `frontend/src/api/generated.ts` | Regenerate | Supply generated `AllTransactionRow` and `AllTransactionsResponse` TypeScript contracts. |
| `frontend/src/dashboard/api.ts` | Modify | Export aggregate types, constants, and `fetchAllTransactions(query, cursor, limit)`. |
| `frontend/src/dashboard/all-transactions-api.test.ts` | Create | Verify query trimming/encoding, cursor forwarding, limit clamping, and error propagation through the shared client. |
| `frontend/src/dashboard/allTransactionsCache.ts` | Create | Persist and hydrate owner/query-scoped last-known-good aggregate results in session storage. |
| `frontend/src/dashboard/allTransactionsCache.test.ts` | Create | Prove owner, query, and view isolation plus corrupt/expired payload rejection. |
| `frontend/src/dashboard/DashboardViewToggle.tsx` | Create | Render the accessible All cards/All transactions segmented control. |
| `frontend/src/dashboard/AllTransactionsTable.tsx` | Create | Render semantic rows, masked card/bank columns, states, alert actions, and continuation control. |
| `frontend/src/dashboard/DashboardPage.tsx` | Modify | Parse URL view state, enable only the active query, manage aggregate pagination/cache, preserve `q`, and choose card grid or table copy/rendering. |
| `frontend/src/dashboard/all-transactions-view.test.tsx` | Create | Exercise dashboard toggle, URL/history behavior, active-query selection, rows, pagination, empty/error states, offline cache, and accessibility. |
| `frontend/src/test/dashboardFixtures.ts` | Modify | Add aggregate response builders and MSW handlers with globally ordered multi-bank rows and continuation pages. |
| `frontend/src/styles.css` | Modify | Style the fleet-summary/toggle row, segmented control, responsive table, row secondary content, states, and contained mobile overflow. |
| `frontend/e2e/transaction-flow.spec.ts` | Modify | Cover the real dashboard toggle, table identity columns, search continuity, pagination, keyboard operation, and 280-pixel containment. |

### Product documentation

| Path | Change | Responsibility |
| --- | --- | --- |
| `docs/PRD.md` | Modify | Link the approved feature PRD and scope the existing card-grid requirements to All cards. |
| `README.md` | Modify | Describe both dashboard views and link the feature PRD. |

No model, Alembic, synchronization, connection, card-grid, card-panel, or transaction-limitation file needs a behavioral change.

## Stable Interfaces

These names and contracts remain fixed unless the PRD changes first.

### Backend domain types

```python
@dataclass(frozen=True)
class AllTransactionRow:
    transaction: TransactionRow
    card: CardRow


@dataclass(frozen=True)
class AllTransactionsResult:
    query: str
    total_matches: int
    card_count: int
    bank_count: int
    rows: list[AllTransactionRow]
    next_cursor: str | None
    has_more: bool
    cache_as_of: datetime | None


class AggregateCursorCodec:
    def encode(
        self,
        normalized_query: str,
        sort_date: str | None,
        row_id: str,
    ) -> str: ...

    def decode(
        self,
        cursor: str,
        expected_normalized_query: str,
    ) -> tuple[str | None, str]: ...


class SearchService:
    async def all_transactions(
        self,
        owner_id: str,
        query: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> AllTransactionsResult: ...
```

`AggregateCursorCodec` signs a compact payload containing normalized query (`q`), sort date (`d`), and row ID (`i`). Decode compares `q` with `hmac.compare_digest`; malformed payloads, invalid signatures, missing fields, or mismatched queries raise the existing `AppError("CURSOR_INVALID", "That page link is no longer valid.", 400)`.

### HTTP API

```text
GET /api/transactions?q=<0..200 chars>&limit=<1..50>&cursor=<opaque>
```

```python
class AllTransactionRow(BaseModel):
    transaction: TransactionMatch
    card: CardResponse


class AllTransactionsResponse(BaseModel):
    query: str
    total_matches: int
    card_count: int
    bank_count: int
    rows: list[AllTransactionRow]
    next_cursor: str | None
    has_more: bool
    cache_as_of: datetime | None
```

Errors use current middleware and FastAPI validation contracts:

- No owner session: HTTP 401.
- `limit < 1`, `limit > 50`, or `q` longer than 200 characters: HTTP 422.
- Invalid, tampered, or query-mismatched cursor: HTTP 400 with `code = "CURSOR_INVALID"`.

### Frontend API

```ts
export type AllTransactionRow = components['schemas']['AllTransactionRow']
export type AllTransactionsResponse = components['schemas']['AllTransactionsResponse']

export const DEFAULT_ALL_TRANSACTIONS_LIMIT = 50

export function fetchAllTransactions(
  query: string,
  cursor: string | null,
  limit: number = DEFAULT_ALL_TRANSACTIONS_LIMIT,
): Promise<AllTransactionsResponse>
```

### URL state

```text
/dashboard                         => All cards, blank query
/dashboard?q=Paze                  => All cards, submitted query
/dashboard?view=transactions       => All transactions, blank query
/dashboard?view=transactions&q=Paze => All transactions, submitted query
```

The implementation must construct `URLSearchParams` from the current values so changing one key preserves the other. Unsupported `view` values are treated as All cards and may remain in the URL until the owner selects an option.

## Dependency Order

```text
aggregate service + HTTP contract
  └── generated TypeScript + fetch/cache layer
        └── URL toggle + table integration
              └── responsive/E2E verification
                    └── durable product-document links
```

## Task 1: Add the Owner-Scoped Aggregate Transactions API

**Commit:** `feat: add aggregate transactions endpoint`

**Files:**

- Modify: `backend/app/services/search_service.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/api/search.py`
- Test: `backend/tests/services/test_search_service.py`
- Test: `backend/tests/api/test_search.py`

**Interfaces consumed:** `BankConnection`, `CardAccount`, `Transaction`, `CardRow`, `TransactionRow`, `normalize_query`, `transaction_match_filter`, existing HMAC/base64 helpers, `OwnerDep`, `SearchService`, `CardResponse`, and `TransactionMatch`.

**Interfaces produced:** `AllTransactionRow`, `AllTransactionsResult`, `AggregateCursorCodec`, `SearchService.all_transactions`, Pydantic `AllTransactionRow`/`AllTransactionsResponse`, and `GET /api/transactions`.

### Step 1.1: Write failing service tests

Add focused tests with explicit fixtures/assertions:

- `test_all_transactions_returns_one_global_newest_first_page` inserts interleaved transactions across at least three cards and asserts `(posted_date or authorized_date, id)` descending across card boundaries.
- `test_all_transactions_counts_the_full_fleet_when_search_has_no_matches` asserts zero rows/total but eight cards/four banks.
- `test_all_transactions_paginates_dated_and_null_date_rows_without_duplicates` uses `limit=2`, walks every cursor, and compares concatenated IDs to a one-shot ordered expectation.
- `test_all_transactions_cursor_is_signed_and_bound_to_query` tampers a cursor and replays a valid `Paze` cursor with `Juniper`; both raise `CURSOR_INVALID`.
- `test_all_transactions_excludes_other_owner_inactive_card_and_removed_connection_rows` inserts one row in each excluded scope and asserts none appear.
- `test_all_transactions_cache_as_of_uses_oldest_active_card_sync` asserts the current freshness meaning.

Run:

```bash
uv run --directory backend pytest tests/services/test_search_service.py -q -k all_transactions
```

Expected red: collection or execution fails because `SearchService.all_transactions`, aggregate result types, and cursor codec do not exist.

### Step 1.2: Implement the minimum aggregate service

- Reuse `list_cards(owner_id)` for fleet count, distinct bank count, and cache freshness.
- Build one SQL statement joining `Transaction -> CardAccount -> BankConnection`, scoped by owner, active connection lifecycle, and active card.
- Apply `transaction_match_filter(normalize_query(query))` to both count and page statements.
- Sort by `coalesce(posted_date, authorized_date) DESC`, then `Transaction.id DESC`, with null dates last.
- Fetch `limit + 1`, return the first `limit`, and sign the last visible row into a query-bound cursor only when another row exists.
- Map each database pair to `AllTransactionRow(transaction=_to_row(transaction), card=...)` without calling Plaid.

### Step 1.3: Add failing API tests

Add tests that assert:

- Anonymous `GET /api/transactions` returns 401.
- The demo owner receives globally ordered `rows`, `total_matches`, eight cards, four banks, and the exact response keys.
- `q=Paze` returns ten matches and each row has a nested transaction/card with bank and mask.
- `limit=0`, `limit=51`, and a 201-character query return 422.
- A malformed cursor returns 400/`CURSOR_INVALID`.
- Aggregate reads do not increase fake Plaid request counts.
- Existing grouped-search and per-card contract tests still pass unchanged.

Run:

```bash
uv run --directory backend pytest tests/api/test_search.py -q -k 'all_transactions or search_returns or card_endpoint'
```

Expected red: `/api/transactions` returns 404 because the route and response models do not exist.

### Step 1.4: Add schemas, serializer, and route

- Define the two Pydantic models exactly as pinned above and export them from `schemas.py`.
- Add an aggregate serializer that reuses the existing transaction/card field mapping.
- Register `GET /api/transactions` before no catch-all route is involved; FastAPI exact static matching keeps `/api/transactions/search` backward compatible.
- Let FastAPI validate `q` at 200 characters and `limit` at 1–50.

### Step 1.5: Verify backend green and commit

Run:

```bash
uv run --directory backend pytest tests/services/test_search_service.py tests/api/test_search.py -q
```

Expected green: all selected service and API tests pass, including existing grouped and per-card cases.

Then:

```bash
git add backend/app/services/search_service.py backend/app/schemas.py backend/app/api/search.py backend/tests/services/test_search_service.py backend/tests/api/test_search.py
git diff --staged --check
git commit -m "feat: add aggregate transactions endpoint"
```

## Task 2: Generate the Client Contract and Add Aggregate Fetch/Cache Boundaries

**Commit:** `feat: add aggregate transaction client data layer`

**Files:**

- Regenerate: `frontend/src/api/openapi.json`
- Regenerate: `frontend/src/api/generated.ts`
- Modify: `frontend/src/dashboard/api.ts`
- Create: `frontend/src/dashboard/all-transactions-api.test.ts`
- Create: `frontend/src/dashboard/allTransactionsCache.ts`
- Create: `frontend/src/dashboard/allTransactionsCache.test.ts`

**Interfaces consumed:** Task 1 OpenAPI contract, shared `apiClient`, browser `sessionStorage`, current owner ID, submitted query, and `AllTransactionsResponse`.

**Interfaces produced:** Generated aggregate types, `DEFAULT_ALL_TRANSACTIONS_LIMIT`, `fetchAllTransactions`, and owner/query-scoped `readPersistedAllTransactionsResult`/`persistAllTransactionsResult` helpers.

### Step 2.1: Regenerate the contract

Run:

```bash
pnpm --dir frontend generate:api
```

Expected change: OpenAPI JSON and generated TypeScript include `/api/transactions`, `AllTransactionRow`, and `AllTransactionsResponse`. Do not hand-edit generated files.

### Step 2.2: Write failing fetch-helper tests

Use MSW to capture the aggregate request and assert:

- Blank query sends no `q`, null cursor sends no `cursor`, and default limit is 50.
- `Paze`, a cursor, and limit 25 are URL encoded/forwarded exactly.
- Limits `0` and `500` clamp to 1 and 50.
- The shared client propagates the existing structured API error.

Run:

```bash
pnpm --dir frontend test -- all-transactions-api.test.ts
```

Expected red: import failure because `fetchAllTransactions` and its limit constant are not exported.

### Step 2.3: Add the fetch helper

Add generated aliases and `fetchAllTransactions(query, cursor, limit)`. Follow the existing no-cross-realm-`AbortSignal` decision in `api.ts`; query-key isolation, not aborting `fetch`, prevents stale active-view rendering.

### Step 2.4: Write failing cache tests

Test a fixed clock and session storage:

- Round-trip a merged aggregate response for one owner/query.
- Distinguish owner A from owner B and `Paze` from blank/`Juniper`.
- Never read a grouped-search cache key.
- Reject malformed JSON, wrong schema/version, and entries older than the existing dashboard cache TTL.

Run:

```bash
pnpm --dir frontend test -- allTransactionsCache.test.ts
```

Expected red: module-not-found because `allTransactionsCache.ts` does not exist.

### Step 2.5: Implement cache helpers and verify green

Mirror `searchCache.ts` conventions but use a distinct versioned key prefix such as `transaction-aggregator:all-transactions:v1`. Store only fields required to hydrate a valid `AllTransactionsResponse`, keyed by owner ID and normalized submitted-query key.

Run:

```bash
pnpm --dir frontend test -- all-transactions-api.test.ts allTransactionsCache.test.ts
pnpm --dir frontend typecheck
```

Expected green: both focused suites and TypeScript pass.

Then:

```bash
git add frontend/src/api/openapi.json frontend/src/api/generated.ts frontend/src/dashboard/api.ts frontend/src/dashboard/all-transactions-api.test.ts frontend/src/dashboard/allTransactionsCache.ts frontend/src/dashboard/allTransactionsCache.test.ts
git diff --staged --check
git commit -m "feat: add aggregate transaction client data layer"
```

## Task 3: Integrate the URL-Backed Toggle and All Transactions Table

**Commit:** `feat: add all transactions dashboard view`

**Files:**

- Create: `frontend/src/dashboard/DashboardViewToggle.tsx`
- Create: `frontend/src/dashboard/AllTransactionsTable.tsx`
- Modify: `frontend/src/dashboard/DashboardPage.tsx`
- Create: `frontend/src/dashboard/all-transactions-view.test.tsx`
- Modify: `frontend/src/test/dashboardFixtures.ts`

**Interfaces consumed:** `useSearchParams`, `fetchTransactionSearch`, `fetchAllTransactions`, aggregate cache helpers, `SearchBar`, `CacheStatusBanner`, `SearchQueryProvider`, `formatShortDate`, `formatAmount`, `describeAmount`, `highlightText`, and generated row/card types.

**Interfaces produced:** `DashboardViewToggle`, `AllTransactionsTable`, active-view query selection, aggregate continuation state, and the PRD-defined copy/states.

### Step 3.1: Add failing dashboard integration tests

Create aggregate MSW fixtures with rows interleaved across Capital One, Chase, Citi, and Wells Fargo. Add tests that prove:

- Default load selects All cards and does not call `/api/transactions`.
- Selecting All transactions sets `view=transactions`, preserves `q`, renders the exact seven table headers, and does not fetch `/api/transactions/search` for that view.
- All transaction rows render globally ordered date, merchant, `•••• 4812`, Capital One, amount semantics, pending/posted text, and Set alert URL.
- A null mask visibly reads `Unavailable` and has an accessible unavailable-card-number label.
- Load more appends the second page once, disables while pending, and retains rows after a continuation error.
- Submitting a different query resets rows/cursor; toggling views preserves the query without another search-history write.
- Unsupported `view` values show All cards.
- No-card, blank empty, search empty, initial error/retry, and continuation error copy match the PRD.
- A successful aggregate result hydrates offline only for the same owner and query.
- The complete All transactions dashboard passes `runAxeSmokeTest`.

Run:

```bash
pnpm --dir frontend test -- all-transactions-view.test.tsx
```

Expected red: the toggle/table modules and aggregate dashboard behavior do not exist.

### Step 3.2: Implement the view toggle

- Render a labeled two-button group with `aria-label="Dashboard view"` and `aria-pressed` on each option.
- Accept `view: 'cards' | 'transactions'` and `onChange(view)`; keep URL mutation in `DashboardPage`.
- Put the toggle and fleet summary in one `.dashboard-page__view-row` so their adjacency is structural and testable.

### Step 3.3: Implement active-view data flow

- Parse `view=transactions`; all other values resolve to cards.
- Preserve current `q` when setting/removing `view`, and preserve `view` when submitting/clearing `q`.
- Enable the grouped query only for cards and the aggregate first-page query only for transactions; both remain disabled under the existing offline condition and hydrate their own session cache.
- Use one aggregate continuation mutation keyed by the current submitted query. On success, deduplicate by transaction ID before appending; on query/view change, discard stale page state.
- Derive fleet summary from the active successful/last-known-good response: grouped data supplies cards/banks as today; aggregate data supplies `card_count`/`bank_count` directly.
- Keep transaction-limit alert retrieval/rendering unchanged for All cards and do not render its banners inside the table.

### Step 3.4: Implement semantic table and states

- Render `<table>` with `<caption className="sr-only">Transactions across all cards</caption>`, `<thead>`, and `<tbody>`.
- Render Date, Merchant, Card number, Bank, Amount, Status, and Actions in the pinned order.
- Use existing safe highlighter and formatters. Display `Pending` or `Posted` as text; show `Date unavailable` for null dates.
- Show card name as secondary content under the mask, and create the existing Set alert URL with row card ID and merchant label.
- Put the table in a focusable/labeled scroll wrapper only when overflow is possible; render Load more and state messaging outside `<table>` but within the table section.

### Step 3.5: Verify frontend behavior green and commit

Run:

```bash
pnpm --dir frontend test -- dashboard.test.tsx all-transactions-view.test.tsx search-flow.test.tsx
pnpm --dir frontend typecheck
```

Expected green: new aggregate behavior and existing card/search regressions pass.

Then:

```bash
git add frontend/src/dashboard/DashboardViewToggle.tsx frontend/src/dashboard/AllTransactionsTable.tsx frontend/src/dashboard/DashboardPage.tsx frontend/src/dashboard/all-transactions-view.test.tsx frontend/src/test/dashboardFixtures.ts
git diff --staged --check
git commit -m "feat: add all transactions dashboard view"
```

## Task 4: Make the Table Responsive and Verify the Owner Journey

**Commit:** `feat: make all transactions table responsive`

**Files:**

- Modify: `frontend/src/styles.css`
- Modify/Test: `frontend/e2e/transaction-flow.spec.ts`
- Test: `frontend/src/dashboard/all-transactions-view.test.tsx`

**Interfaces consumed:** Existing color/spacing/radius tokens, `.dashboard-page`, page overflow helper, connected demo-bank journey, and accessible toggle/table DOM from Task 3.

**Interfaces produced:** Responsive toggle/table presentation and browser-level evidence for desktop, keyboard, search continuity, and 280-pixel containment.

### Step 4.1: Add failing browser assertions

Extend the existing owner transaction journey to:

- Select All transactions after the eight cards load.
- Assert the URL, seven headers, bank names, and all expected masked card values.
- Search `Paze`, verify ten aggregate matches remain in table view, and switch back to cards without losing `q`.
- Tab to and activate both view options by keyboard.
- At 280 pixels, select All transactions, assert the table scroll container's `scrollWidth >= clientWidth`, and reuse `expectNoHorizontalOverflow(page)` to prove overflow remains contained.

Run:

```bash
pnpm --dir frontend e2e --grep "owner connects four banks and searches every card at once|dashboard keeps every visible element inside a narrow mobile device"
```

Expected red before styling: the new narrow-table assertions report viewport escape or unusable toggle/table layout.

### Step 4.2: Add responsive and state styles

- Make `.dashboard-page__view-row` wrap with a consistent gap.
- Give the toggle a visible selected state, 44-pixel touch targets, keyboard focus ring, and non-color selection indicator.
- Style the table with a minimum readable width inside an `overflow-x: auto` container; never hide requested columns at narrow widths.
- Right-align amounts, keep identity/status text readable, and use existing muted/accent colors that meet WCAG AA.
- Style empty, error, retry, and continuation controls without affecting card-grid selectors.
- Respect the existing reduced-motion media query.

### Step 4.3: Verify browser and frontend green, then commit

Run:

```bash
pnpm --dir frontend test -- all-transactions-view.test.tsx dashboard.test.tsx
pnpm --dir frontend e2e --grep "owner connects four banks and searches every card at once|dashboard keeps every visible element inside a narrow mobile device"
pnpm --dir frontend build
```

Expected green: focused component/accessibility tests, both browser journeys, TypeScript, and production build pass.

Then:

```bash
git add frontend/src/styles.css frontend/e2e/transaction-flow.spec.ts frontend/src/dashboard/all-transactions-view.test.tsx
git diff --staged --check
git commit -m "feat: make all transactions table responsive"
```

## Task 5: Update Durable Product Documentation

**Commit:** `docs: document all transactions dashboard view`

**Files:**

- Modify: `docs/PRD.md`
- Modify: `README.md`

**Interfaces consumed:** Approved feature PRD and final user-visible labels/routes.

**Interfaces produced:** Product-level links and a non-contradictory dashboard description.

### Step 5.1: Add a failing documentation check

Run:

```bash
rg -n "all-transactions-view/PRD.md|All transactions" docs/PRD.md README.md
```

Expected red: neither durable document describes or links the feature yet.

### Step 5.2: Update documentation

- Link `docs/features/all-transactions-view/PRD.md` from the product PRD and README.
- Clarify that card grouping, independent card pagination, and zero-match visible panels apply to All cards.
- Add the alternate aggregate-table journey without copying the feature PRD's detailed contract.
- Preserve all security, provider, sync, and local-first requirements.

### Step 5.3: Verify and commit

Run:

```bash
rg -n "all-transactions-view/PRD.md|All transactions" docs/PRD.md README.md
git diff --check
```

Expected green: both files mention the view and at least one durable link resolves to the feature PRD.

Then:

```bash
git add docs/PRD.md README.md
git diff --staged --check
git commit -m "docs: document all transactions dashboard view"
```

## Final Verification Gate

Run from the repository root after Task 5:

```bash
make check
make e2e
git status --short
git log --oneline --decorate -6
```

Expected:

- Backend, frontend, preview-environment, typecheck, and production-build checks pass.
- The full Playwright suite passes, including aggregate desktop/mobile coverage.
- The working tree is clean.
- Five independently coherent implementation commits follow the planning commit(s).

Before every commit, inspect `git diff --staged`, run `git diff --staged --check`, and scan the staged diff for credential/token material. Do not modify `backend/.env`, `backend/data/`, build output, or installed dependencies.

## Requirement Coverage Matrix

| PRD requirements | Planned coverage |
| --- | --- |
| AV-VIEW-001–006 | Task 3 toggle/URL/query tests; Task 4 desktop/mobile browser tests |
| AV-API-001–002 | Task 1 owner-scope and no-Plaid service/API tests |
| AV-API-003–005 | Task 1 request/response/validation tests; Task 2 generated contract/helper tests |
| AV-API-006–010 | Task 1 global-order, null-date, cursor, fleet-count, and freshness tests |
| AV-TABLE-001–004 | Task 3 semantic-table, display, masking, formatting, and alert-link tests |
| AV-TABLE-005–006 | Task 3 continuation, deduplication, pending, error, and query-reset tests |
| AV-TABLE-007–008 | Task 3 no-card/empty/error/retry tests |
| AV-TABLE-009–010 | Task 3 axe/keyboard semantics; Task 4 280-pixel contained-overflow browser test |
| AV-COMPAT-001–002 | Task 3 existing dashboard/search regression suites and active-query/history assertions |
| AV-COMPAT-003 | Task 2 cache isolation tests; Task 3 offline hydration test |
| AV-COMPAT-004 | Task 1 existing grouped/per-card backend tests; Task 3 existing card dashboard tests |
| Observability and Privacy | Task 1 no-Plaid/owner-scope tests, Task 3 masked/null-mask tests, final staged-diff secret scan |
| Rollout and documentation | Task 2 generated artifact step, Task 5 product docs, no migration files in File Structure |

Every observable requirement maps to at least one automated or documentation check. The Non-goals require no implementation and act as scope-review constraints.

## Review Gate

Implementation must not begin until the owner reviews `docs/features/all-transactions-view/PRD.md`, confirms or changes the four proposed Open Questions, and explicitly authorizes this plan. If requirements change, update the PRD first, then revise the affected interfaces, tasks, tests, and coverage rows here before writing code.
