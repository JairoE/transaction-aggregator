# Saved Transaction Aggregates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show USD purchases, refunds, and net total for an ad-hoc transaction search and for saved, all-history per-card dashboard aggregates without changing transaction-alert behavior.

**Architecture:** Deliver two reviewable slices. Slice A adds one shared USD-summary calculation and exposes it through the existing search flows without increasing their query count. Slice B persists lightweight saved definitions in separate tables, evaluates each definition with one query grouped by card, and displays the results independently from alerts.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async with SQLite and Alembic, React 19, TanStack Query, TypeScript, Vitest, pytest.

**Spec:** `docs/features/saved-transaction-aggregates/PRD.md`

## Global Constraints

- Version 1 evaluates all available history and USD transactions only.
- Positive transaction amounts are purchases and negative amounts are refunds.
- Include pending USD matches in purchases, refunds, net total, USD match count, and USD pending count.
- Keep the existing all-currency `total_matches` search field unchanged.
- A saved aggregate has no threshold, triggered state, date window, or enable/disable state.
- Preserve all existing transaction-limitation tables, APIs, URLs, and dashboard alert behavior.
- A saved-aggregate request failure must not prevent cards, transactions, or alerts from rendering.
- Generate `frontend/src/api/openapi.json` and `frontend/src/api/generated.ts` after changing backend schemas or routes.

---

## File map

| File | Responsibility |
| --- | --- |
| `backend/app/services/transaction_summary.py` | Own the shared USD summary type, SQL expressions, and row conversion. |
| `backend/app/services/search_service.py` | Replace count-only search queries with summary queries. |
| `backend/app/schemas.py` | Define the shared summary and saved-aggregate wire contracts. |
| `backend/app/api/search.py` | Serialize ad-hoc search summaries. |
| `backend/alembic/versions/0010_transaction_aggregates.py` | Persist lightweight saved definitions and card selections. |
| `backend/app/models.py` | Define `TransactionAggregate` and `TransactionAggregateCard`. |
| `backend/app/services/aggregate_service.py` | Own saved-definition CRUD and grouped per-card evaluation. |
| `backend/app/api/aggregates.py` | Expose owner-scoped CRUD and evaluated saved results. |
| `backend/app/main.py` | Register the aggregate router. |
| `backend/tests/services/test_search_service.py` | Prove complete, pagination-independent ad-hoc totals. |
| `backend/tests/api/test_search.py` | Prove the ad-hoc summary response contract. |
| `backend/tests/migrations/test_transaction_aggregates.py` | Prove storage constraints and cascades. |
| `backend/tests/services/test_aggregate_service.py` | Prove CRUD scope and saved USD evaluation. |
| `backend/tests/api/test_aggregates.py` | Prove authentication, CSRF, ownership, and response contracts. |
| `frontend/src/dashboard/TransactionAggregateSummary.tsx` | Render purchases, refunds, net, and USD counts for both feature slices. |
| `frontend/src/dashboard/format.ts` | Format positive refunds and negative net totals correctly. |
| `frontend/src/dashboard/api.ts` | Export generated ad-hoc summary types. |
| `frontend/src/dashboard/CardPanel.tsx` | Render an ad-hoc per-card summary for a submitted query. |
| `frontend/src/dashboard/AllTransactionsTable.tsx` | Render the combined ad-hoc summary for a submitted query. |
| `frontend/src/dashboard/searchCache.ts` | Version grouped-search entries so pre-summary data is removed safely. |
| `frontend/src/dashboard/allTransactionsCache.ts` | Validate and retain the new combined summary in persisted responses. |
| `frontend/src/aggregates/api.ts` | Provide typed saved-definition and evaluation requests. |
| `frontend/src/aggregates/TransactionAggregateForm.tsx` | Collect keyword and card scope only. |
| `frontend/src/aggregates/TransactionAggregateList.tsx` | Edit and delete saved definitions. |
| `frontend/src/limitations/TransactionLimitationsPage.tsx` | Host the separate saved-aggregate management section. |
| `frontend/src/dashboard/SavedTransactionAggregates.tsx` | Render saved summaries for one card. |
| `frontend/src/dashboard/CardGrid.tsx` | Carry saved results with each card group. |
| `frontend/src/dashboard/DashboardPage.tsx` | Fetch saved results and merge them by card without coupling failures. |
| `frontend/src/styles.css` | Style neutral, responsive summary modules. |

## Stable interfaces

```python
@dataclass(frozen=True)
class TransactionSummary:
    usd_match_count: int
    usd_pending_count: int
    purchases_cents: int
    refunds_cents: int
    net_total_cents: int


# SearchService keeps the existing all-currency count beside the USD summary.
SearchSummary = tuple[int, TransactionSummary]


@dataclass(frozen=True)
class AggregateRuleResult:
    aggregate: TransactionAggregate
    card_ids: list[str]


@dataclass(frozen=True)
class AggregateListResult:
    aggregates: list[AggregateRuleResult]
    cards: list[CardRow]


@dataclass(frozen=True)
class SavedAggregateEvaluation:
    aggregate_id: str
    keyword: str
    card: CardRow
    summary: TransactionSummary


@dataclass(frozen=True)
class SavedAggregateResult:
    aggregates: list[SavedAggregateEvaluation]
    evaluated_at: datetime
    cache_as_of: datetime | None


class TransactionAggregateService:
    async def list_aggregates(self, owner_id: str) -> AggregateListResult: ...
    async def create_aggregate(
        self, owner_id: str, payload: CreateTransactionAggregateRequest
    ) -> AggregateRuleResult: ...
    async def update_aggregate(
        self,
        owner_id: str,
        aggregate_id: str,
        payload: UpdateTransactionAggregateRequest,
    ) -> AggregateRuleResult: ...
    async def delete_aggregate(self, owner_id: str, aggregate_id: str) -> None: ...
    async def evaluate_saved_aggregates(self, owner_id: str) -> SavedAggregateResult: ...
```

```text
CardTransactionGroup.usd_summary: TransactionAggregateSummaryResponse
AllTransactionsResponse.usd_summary: TransactionAggregateSummaryResponse
GroupedSearchResponse: no root summary; each group owns its per-card summary
Existing total_matches: unchanged and includes every matching currency

GET    /api/transaction-aggregates
POST   /api/transaction-aggregates
PATCH  /api/transaction-aggregates/{aggregate_id}
DELETE /api/transaction-aggregates/{aggregate_id}
GET    /api/saved-transaction-aggregates
```

```ts
export const SAVED_TRANSACTION_AGGREGATES_QUERY_KEY =
  ['saved-transaction-aggregates'] as const

export function fetchTransactionAggregates(): Promise<TransactionAggregateListResponse>
export function createTransactionAggregate(
  input: CreateTransactionAggregateRequest,
): Promise<TransactionAggregateResponse>
export function updateTransactionAggregate(
  aggregateId: string,
  input: UpdateTransactionAggregateRequest,
): Promise<TransactionAggregateResponse>
export function deleteTransactionAggregate(aggregateId: string): Promise<void>
export function fetchSavedTransactionAggregates(): Promise<SavedTransactionAggregateListResponse>
```

## Slice A: Ad-hoc search summaries

### Task 1: Add shared summary calculation and search contracts

**Files:**
- Create: `backend/app/services/transaction_summary.py`
- Modify: `backend/app/services/search_service.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/api/search.py`
- Test: `backend/tests/services/test_search_service.py`
- Test: `backend/tests/api/test_search.py`

**Consumes:** Existing `normalize_query`, `transaction_match_filter`, grouped card search, aggregate transaction search, and all-currency `total_matches`.

**Produces:** `TransactionSummary`, `TransactionAggregateSummaryResponse`, `CardTransactionGroup.usd_summary`, and `AllTransactionsResponse.usd_summary`.

- [ ] **Step 1: Write failing service tests for complete USD summaries.**

  Seed more matching rows than the page limit: USD purchases of `12000` and `500`, a USD refund of `-2000`, and a CAD purchase of `9000`. Mark the `500` purchase pending. For `per_card_limit=1`, assert one visible row but `usd_match_count == 3`, `usd_pending_count == 1`, `purchases_cents == 12500`, `refunds_cents == 2000`, and `net_total_cents == 10500`. Assert existing `total_matches == 4`.

  ```python
  result = await service.search(owner.id, query="Paze", per_card_limit=1)
  assert len(result.groups[0].transactions) == 1
  assert result.groups[0].usd_summary == TransactionSummary(
      usd_match_count=3,
      usd_pending_count=1,
      purchases_cents=12_500,
      refunds_cents=2_000,
      net_total_cents=10_500,
  )
  assert result.total_matches == 4
  ```

- [ ] **Step 2: Run the selected tests and verify red.**

  ```bash
  uv run --directory backend pytest tests/services/test_search_service.py -k summary -q
  ```

  Expected: fail because search result types do not expose `usd_summary`.

- [ ] **Step 3: Implement the shared summary module.**

  Define `TransactionSummary`, `transaction_summary_columns()`, and `transaction_summary_from_row(row)`. Build the five SQL values with `sum(case(...))` and `coalesce(..., 0)`: USD row count, pending USD row count, positive USD amount sum, absolute negative USD amount sum, and signed USD amount sum. Keep this module free of owner, pagination, and saved-definition behavior.

- [ ] **Step 4: Replace existing count queries with summary queries.**

  Change `SearchService._count(card_id, normalized)` to `_summary(card_id, normalized) -> SearchSummary`. Its statement selects `func.count()` for the existing all-currency count alongside the five shared USD columns, then returns `(all_currency_count, usd_summary)`. Update both `search()` and `card_transactions()` to keep the first value as `CardGroup.match_count` and add the second as `CardGroup.usd_summary`. In `all_transactions()`, replace the existing count-only aggregate statement with the same combined statement. Do not add a third query per card.

- [ ] **Step 5: Add exact response fields and API tests.**

  Add `TransactionAggregateSummaryResponse` with the five stable fields. Add non-null `usd_summary` to `CardTransactionGroup` and `AllTransactionsResponse`; do not add a root summary to `GroupedSearchResponse`. Assert empty matches serialize five zeroes and mixed-currency searches preserve the existing all-currency count.

- [ ] **Step 6: Verify and commit Slice A backend.**

  ```bash
  uv run --directory backend pytest tests/services/test_search_service.py tests/api/test_search.py -q
  git add backend/app/services/transaction_summary.py backend/app/services/search_service.py backend/app/schemas.py backend/app/api/search.py backend/tests/services/test_search_service.py backend/tests/api/test_search.py
  git diff --staged --check
  git commit -m "feat: summarize matching transaction totals"
  ```

### Task 2: Display ad-hoc summaries

**Files:**
- Create: `frontend/src/dashboard/TransactionAggregateSummary.tsx`
- Modify: `frontend/src/dashboard/format.ts`
- Modify: `frontend/src/dashboard/format.test.ts`
- Modify: `frontend/src/dashboard/api.ts`
- Modify: `frontend/src/dashboard/CardPanel.tsx`
- Modify: `frontend/src/dashboard/AllTransactionsTable.tsx`
- Modify: `frontend/src/dashboard/searchCache.ts`
- Create: `frontend/src/dashboard/searchCache.test.ts`
- Modify: `frontend/src/dashboard/allTransactionsCache.ts`
- Modify: `frontend/src/dashboard/allTransactionsCache.test.ts`
- Modify: `frontend/src/dashboard/dashboard.test.tsx`
- Modify: `frontend/src/dashboard/all-transactions-view.test.tsx`
- Modify: `frontend/src/api/openapi.json`
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/styles.css`

**Consumes:** Task 1 API fields.

**Produces:** One reusable summary component used by ad-hoc and saved results.

- [ ] **Step 1: Regenerate contracts and write failing formatting tests.**

  ```bash
  pnpm --dir frontend generate:api
  ```

  Add `formatUsdAggregate(cents: number): string` tests asserting `10000 -> "$100.00"` and `-10000 -> "-$100.00"`. Refunds pass their already-positive magnitude to this formatter.

- [ ] **Step 2: Write failing dashboard tests.**

  In card view with query `Paze`, assert the card summary displays `Purchases $125.00`, `Refunds $20.00`, `Net $105.00`, and `3 USD matches · 1 pending`. In all-transactions view, assert the combined summary renders only when a non-empty query is submitted.

- [ ] **Step 3: Write failing cache compatibility tests.**

  Store an unversioned pre-summary grouped response under the existing `ta:search-cache:` prefix and assert the new reader removes it. Store an all-transactions response with `usd_summary` and assert all five fields survive sanitization and retrieval; store a version-1 response without the field and assert it is discarded.

- [ ] **Step 4: Implement the formatter and shared presentation component.**

  Use `Intl.NumberFormat(locale(), { style: 'currency', currency: 'USD' })` on `cents / 100` without `Math.abs`, so negative net totals retain their sign. Implement `TransactionAggregateSummary` with semantic labels for purchases, refunds, net, USD match count, and pending count.

- [ ] **Step 5: Render ad-hoc summaries and version persisted response shapes.**

  Render `group.usd_summary` in `CardPanel` only when `useSearchQuery()` is non-empty. Pass and render `AllTransactionsResponse.usd_summary` in `AllTransactionsTable` only for a non-empty submitted query. Keep the grouped-search storage prefix unchanged, add `CACHE_VERSION = 2` to stored entries, and reject/remove entries without that version so logout cleanup still covers the same namespace. Increment `allTransactionsCache.ts` `CACHE_VERSION` to `2`, validate all five summary fields as finite numbers, and return the sanitized summary with the response. Preserve transaction pagination and existing result-count copy.

- [ ] **Step 6: Verify and commit Slice A frontend.**

  ```bash
  pnpm --dir frontend test src/dashboard/format.test.ts src/dashboard/dashboard.test.tsx src/dashboard/all-transactions-view.test.tsx src/dashboard/searchCache.test.ts src/dashboard/allTransactionsCache.test.ts
  pnpm --dir frontend build
  git add frontend/src/dashboard/TransactionAggregateSummary.tsx frontend/src/dashboard/format.ts frontend/src/dashboard/format.test.ts frontend/src/dashboard/api.ts frontend/src/dashboard/CardPanel.tsx frontend/src/dashboard/AllTransactionsTable.tsx frontend/src/dashboard/dashboard.test.tsx frontend/src/dashboard/all-transactions-view.test.tsx frontend/src/dashboard/searchCache.ts frontend/src/dashboard/searchCache.test.ts frontend/src/dashboard/allTransactionsCache.ts frontend/src/dashboard/allTransactionsCache.test.ts frontend/src/api/openapi.json frontend/src/api/generated.ts frontend/src/styles.css
  git diff --staged --check
  git commit -m "feat: display search aggregate summaries"
  ```

## Slice B: Saved dashboard aggregates

### Task 3: Persist saved definitions

**Files:**
- Create: `backend/alembic/versions/0010_transaction_aggregates.py`
- Create: `backend/tests/migrations/test_transaction_aggregates.py`
- Modify: `backend/app/models.py`

**Produces:** All-history saved definitions with all-card or selected-card scope.

- [ ] **Step 1: Write failing migration tests.**

  Test a valid all-card definition, a valid selected-card association, rejection of unknown card scopes, uniqueness of aggregate/card pairs, and owner/aggregate/card delete cascades.

  ```python
  connection.execute(
      "INSERT INTO transaction_aggregates "
      "(id, owner_id, keyword, normalized_keyword, card_scope, created_at, updated_at) "
      "VALUES (?, ?, ?, ?, ?, ?, ?)",
      ("aggregate-1", "owner-1", "Paze", "paze", "all_cards", NOW, NOW),
  )
  with pytest.raises(sqlite3.IntegrityError):
      connection.execute(
          "UPDATE transaction_aggregates SET card_scope = 'unknown' "
          "WHERE id = 'aggregate-1'"
      )
  ```

- [ ] **Step 2: Run the migration tests and verify red.**

  ```bash
  uv run --directory backend pytest tests/migrations/test_transaction_aggregates.py -q
  ```

  Expected: fail because the new tables do not exist.

- [ ] **Step 3: Add the migration and ORM models.**

  Create `transaction_aggregates` with `id`, `owner_id`, `keyword`, `normalized_keyword`, `card_scope`, and timestamps. Create `transaction_aggregate_cards` with `(aggregate_id, card_account_id)` as its composite primary key. Add the existing card-scope check and cascading foreign keys. Add owner/card relationships following the current limitation association-object pattern. Do not add threshold, metric, window, or enabled columns.

- [ ] **Step 4: Verify and commit persistence.**

  ```bash
  uv run --directory backend pytest tests/migrations/test_transaction_aggregates.py tests/migrations/test_transaction_limitations.py -q
  git add backend/alembic/versions/0010_transaction_aggregates.py backend/app/models.py backend/tests/migrations/test_transaction_aggregates.py
  git diff --staged --check
  git commit -m "feat: persist saved transaction aggregates"
  ```

### Task 4: Add saved-definition CRUD and grouped evaluation

**Files:**
- Create: `backend/app/services/aggregate_service.py`
- Create: `backend/app/api/aggregates.py`
- Create: `backend/tests/services/test_aggregate_service.py`
- Create: `backend/tests/api/test_aggregates.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`

**Consumes:** Task 1 summary expressions and Task 3 models.

**Produces:** The five saved-aggregate endpoints and every stable backend result type.

- [ ] **Step 1: Write failing CRUD and evaluation service tests.**

  Cover keyword normalization, card-ID deduplication, selected-card ownership rejection, zero-valued target cards, and owner isolation. Seed Paze transactions across two target cards and assert one all-card definition produces one result per card. Include USD purchases, a USD refund, a pending USD purchase, and a matching CAD transaction.

  ```python
  result = await service.evaluate_saved_aggregates(owner.id)
  assert [item.card.id for item in result.aggregates] == [first.id, second.id]
  assert result.aggregates[0].summary.net_total_cents == 10_500
  assert result.aggregates[1].summary == TransactionSummary(0, 0, 0, 0, 0)
  ```

- [ ] **Step 2: Run the selected service tests and verify red.**

  ```bash
  uv run --directory backend pytest tests/services/test_aggregate_service.py -q
  ```

- [ ] **Step 3: Define exact CRUD and evaluation contracts.**

  Define `CreateTransactionAggregateRequest` with `keyword: str`, `card_scope`, and `card_ids`; define the partial update variant; constrain keyword to 1–100 characters and card IDs to at most 100. Define `TransactionAggregateResponse`, `TransactionAggregateListResponse`, `SavedTransactionAggregateResponse`, and `SavedTransactionAggregateListResponse` using the stable types above.

- [ ] **Step 4: Implement CRUD and one grouped query per definition.**

  Normalize keywords with `normalize_query`, validate selected cards against the owner, and keep mutations owner-scoped. For evaluation, execute one matching SQL statement per saved definition, use the shared summary columns, and `GROUP BY Transaction.card_account_id`. Convert returned rows with `transaction_summary_from_row`, then fill missing target card IDs with `TransactionSummary(0, 0, 0, 0, 0)`. Do not execute one query per definition/card pair.

- [ ] **Step 5: Add route tests and register the router.**

  Test authentication on all five routes, CSRF on POST/PATCH/DELETE, cross-owner 404 behavior, invalid selected cards, and the exact evaluated response. Register `backend/app/api/aggregates.py` in `backend/app/main.py`.

- [ ] **Step 6: Verify and commit saved backend behavior.**

  ```bash
  uv run --directory backend pytest tests/services/test_aggregate_service.py tests/api/test_aggregates.py tests/migrations/test_transaction_aggregates.py -q
  git add backend/app/schemas.py backend/app/services/aggregate_service.py backend/app/api/aggregates.py backend/app/main.py backend/tests/services/test_aggregate_service.py backend/tests/api/test_aggregates.py
  git diff --staged --check
  git commit -m "feat: evaluate saved transaction aggregates"
  ```

### Task 5: Add saved-aggregate management

**Files:**
- Create: `frontend/src/aggregates/api.ts`
- Create: `frontend/src/aggregates/TransactionAggregateForm.tsx`
- Create: `frontend/src/aggregates/TransactionAggregateList.tsx`
- Create: `frontend/src/aggregates/transaction-aggregates.test.tsx`
- Modify: `frontend/src/limitations/TransactionLimitationsPage.tsx`
- Modify: `frontend/src/api/openapi.json`
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/styles.css`

**Consumes:** Task 4 CRUD contracts.

**Produces:** A separate management section with create, edit, and delete actions.

- [ ] **Step 1: Regenerate API contracts and write a failing management test.**

  ```bash
  pnpm --dir frontend generate:api
  ```

  Use local MSW handlers in `transaction-aggregates.test.tsx`. Submit a selected-card Paze aggregate and assert the POST body is exactly:

  ```tsx
  expect(requestBody).toEqual({
    keyword: 'Paze',
    card_scope: 'selected_cards',
    card_ids: ['card-1'],
  })
  ```

  Assert no threshold, metric, window, or enabled controls are rendered.

- [ ] **Step 2: Run the management test and verify red.**

  ```bash
  pnpm --dir frontend test src/aggregates/transaction-aggregates.test.tsx
  ```

- [ ] **Step 3: Implement typed requests, form, and list.**

  Add the five frontend request helpers from the stable interface. Build `TransactionAggregateForm` with accessible keyword, all-card/selected-card, and card checkbox controls. Build `TransactionAggregateList` with edit and confirmed-delete controls. Add both under a distinct `Saved aggregates` heading on the existing transaction-limitations management page.

- [ ] **Step 4: Add focused behavior and accessibility coverage.**

  Test create, edit prefill, selected-card validation, delete confirmation, mutation invalidation of definition and evaluated-result query keys, and one axe check. Keep fixtures local to this test file until another file needs the same setup.

- [ ] **Step 5: Verify and commit saved management.**

  ```bash
  pnpm --dir frontend test src/aggregates/transaction-aggregates.test.tsx
  pnpm --dir frontend build
  git add frontend/src/aggregates frontend/src/limitations/TransactionLimitationsPage.tsx frontend/src/api/openapi.json frontend/src/api/generated.ts frontend/src/styles.css
  git diff --staged --check
  git commit -m "feat: manage saved transaction aggregates"
  ```

### Task 6: Render saved aggregates without coupling dashboard failures

**Files:**
- Create: `frontend/src/dashboard/SavedTransactionAggregates.tsx`
- Create: `frontend/src/dashboard/saved-transaction-aggregates.test.tsx`
- Modify: `frontend/src/dashboard/CardGrid.tsx`
- Modify: `frontend/src/dashboard/CardPanel.tsx`
- Modify: `frontend/src/dashboard/DashboardPage.tsx`
- Modify: `frontend/src/styles.css`

**Consumes:** Task 2 `TransactionAggregateSummary` and Task 4 evaluated saved results.

**Produces:** Neutral per-card saved modules matching the approved mock.

- [ ] **Step 1: Write failing card-placement and formatting tests.**

  Mock Paze for card 1 and Dunkin for card 2. Assert each appears only on its target card with purchases, positive-magnitude refunds, signed net, and `USD matches` supporting copy. Assert an all-card definition produces separate modules, a zero-match target remains visible, and a `-10000` net renders as `-$100.00`.

- [ ] **Step 2: Write a failing error-isolation test.**

  Return HTTP 500 from `/api/saved-transaction-aggregates`. Assert all card names, cached transaction rows, and an independently returned transaction-limit alert remain visible; assert a saved-aggregate error status is rendered outside the card transaction lists.

- [ ] **Step 3: Run the dashboard tests and verify red.**

  ```bash
  pnpm --dir frontend test src/dashboard/saved-transaction-aggregates.test.tsx
  ```

- [ ] **Step 4: Implement the saved query and per-card merge.**

  Fetch saved results in card view with the alert query’s 60-second interval and focus refetch behavior. Group successful results by `card.id`, add `savedAggregates` to `DashboardCardGroup`, and render `SavedTransactionAggregates` below the card art and before alerts/transactions. On query failure, pass empty saved results to card groups and render only the independent error status.

- [ ] **Step 5: Verify and commit the dashboard slice.**

  ```bash
  pnpm --dir frontend test src/dashboard/saved-transaction-aggregates.test.tsx src/dashboard/dashboard.test.tsx src/dashboard/transaction-limit-alerts.test.tsx
  pnpm --dir frontend build
  git add frontend/src/dashboard/SavedTransactionAggregates.tsx frontend/src/dashboard/saved-transaction-aggregates.test.tsx frontend/src/dashboard/CardGrid.tsx frontend/src/dashboard/CardPanel.tsx frontend/src/dashboard/DashboardPage.tsx frontend/src/styles.css
  git diff --staged --check
  git commit -m "feat: display saved transaction aggregates"
  ```

### Task 7: Full verification

**Files:** No planned modifications.

- [ ] **Step 1: Build the frontend before backend static-app tests.**

  ```bash
  pnpm --dir frontend build
  ```

- [ ] **Step 2: Run all backend and frontend tests.**

  ```bash
  uv run --directory backend pytest -q
  pnpm --dir frontend test
  ```

- [ ] **Step 3: Manually verify the product flow.**

  Search Paze and confirm per-card summaries plus the combined all-transactions summary. Create an all-card Paze aggregate and a selected-card Dunkin aggregate; confirm each dashboard card receives only its applicable modules. Confirm a saved-aggregate API failure leaves cards, transactions, and alerts usable.

- [ ] **Step 4: Confirm the worktree is clean.**

  ```bash
  git diff --check
  git status --short
  ```

  Expected: no uncommitted files and no whitespace errors.

## Plan self-review

- Spec coverage: Tasks 1–2 implement ad-hoc summaries; Tasks 3–6 implement saved all-history definitions, management, grouped evaluation, and isolated dashboard rendering; Task 7 verifies integration.
- Scope: rolling/fixed windows, enable/disable state, search-to-form shortcuts, currency conversion, alerts, charts, exports, and scheduler jobs are excluded.
- Query shape: grouped search replaces count-only work with summary work; all-transactions replaces its count query; saved evaluation runs once per definition and groups by card.
- Interface consistency: `TransactionSummary` and every result type used by later tasks are defined in the stable-interface section; response placement and USD count names are exact.
- Placeholder scan: the plan contains no incomplete commands, undefined implementation markers, or conditional staging placeholders.
