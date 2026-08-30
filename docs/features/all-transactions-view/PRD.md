# All Transactions View PRD

- **Status:** Proposed for review
- **Date:** August 30, 2026
- **Owner:** Transaction Aggregator product owner
- **Related product requirements:** `docs/PRD.md`

## Summary

Add an **All transactions** view to the dashboard alongside the existing **All cards** view. An accessible two-option toggle sits next to the fleet summary that reports the number of cards and banks. The new view presents transactions from every active credit card in one globally sorted, paginated table, including a bank column and a masked card-number column for every row.

The existing card grid remains the default and continues to behave exactly as it does today. Both views use the same submitted search term and read only from the local SQLite cache.

## Problem and User Value

The card grid is useful when the owner wants card-by-card context, but it makes chronological review across the entire card portfolio difficult. The owner must scan several independently sorted and paginated lists to reconstruct a single timeline.

The All transactions view provides one chronological ledger across all connected cards. Bank and masked-card columns retain the account context that would otherwise be lost when card panels are flattened.

## Goals

- Let the owner switch between All cards and All transactions without leaving the dashboard.
- Keep All cards as the default view and preserve its current behavior.
- Show transactions from every active credit card in one semantic table.
- Identify each transaction by bank and masked card number without exposing a full primary account number (PAN).
- Apply the existing explicit-submit search behavior and literal matching semantics in both views.
- Globally sort and paginate the table without loading or merging every transaction in the browser.
- Preserve authentication, owner isolation, local-cache-only reads, responsive behavior, and accessibility.

## Non-goals

- Replacing or removing the card grid.
- Storing, retrieving, or displaying a full card number.
- Adding transaction filters, sorting controls, bulk actions, export, editing, categorization, or reconciliation.
- Changing transaction synchronization, Plaid calls, connection management, or the database schema.
- Showing active transaction-limitation alert banners in the table; those remain grouped by card in All cards.
- Persisting a preferred dashboard view in the database or local storage.

## Users and Primary Flows

### Primary user

The only user is the authenticated application owner.

### View transactions across all cards

1. The owner opens `/dashboard` and sees the existing All cards view.
2. Next to the fleet summary (for example, `8 cards · 4 banks`), the owner selects **All transactions**.
3. The URL becomes `/dashboard?view=transactions` while any submitted `q` parameter is preserved.
4. The dashboard shows one table containing the newest cached transactions across every active card.
5. Each row identifies the transaction date, merchant or description, masked card number, bank, amount, pending/posted status, and alert action.
6. The owner selects **Load more transactions** to append the next globally sorted page.

### Search in either view

1. The owner enters a merchant or statement keyword and submits with Enter or the Search button.
2. Only the active view fetches results for the submitted query.
3. In All transactions, the table shows every matching transaction across all active cards in global date order.
4. Switching views preserves the submitted query and updates the results presentation without adding another search-history entry.
5. Clearing search returns the active view to recent cached transactions.

## Requirements

### View selection

- **AV-VIEW-001:** The dashboard shall render an accessible two-option toggle labeled **All cards** and **All transactions** next to the fleet summary text that lists the active card and bank counts.
- **AV-VIEW-002:** Exactly one toggle option shall be selected and programmatically exposed as selected at all times.
- **AV-VIEW-003:** All cards shall be the default when the `view` query parameter is absent, empty, or unsupported.
- **AV-VIEW-004:** Selecting All transactions shall set `view=transactions`; selecting All cards shall remove the `view` parameter. Both actions shall preserve a non-empty submitted `q` parameter and browser back/forward behavior.
- **AV-VIEW-005:** Changing views shall not submit a new search-history entry or issue a request for the inactive view.
- **AV-VIEW-006:** The fleet summary shall continue to report all active cards and represented banks, independent of the current search result count.

### Aggregate data and API

- **AV-API-001:** `GET /api/transactions` shall require the authenticated owner session and return only transactions belonging to that owner's active cards under active bank connections.
- **AV-API-002:** The endpoint shall read only from the local database and shall never call Plaid or another bank service.
- **AV-API-003:** The endpoint shall accept optional `q`, `cursor`, and `limit` query parameters. `q` shall use the existing transaction-search normalization and literal-substring matching rules. `limit` shall default to 50 and accept values from 1 through 50 inclusive.
- **AV-API-004:** The response shall include the submitted query after trimming, total matching transaction count, active card count, represented bank count, rows, `next_cursor`, `has_more`, and `cache_as_of`.
- **AV-API-005:** Each row shall include the existing transaction display fields plus the owning card's existing `CardResponse`, which supplies the bank identifier, bank display name, card name, and mask.
- **AV-API-006:** Rows shall be globally sorted by posted date descending, falling back to authorized date, then by transaction ID descending for deterministic ties. Transactions with neither date shall appear after dated transactions and remain deterministically ordered by transaction ID descending.
- **AV-API-007:** Pagination shall use an opaque signed cursor bound to the normalized query, last sort date, and last transaction ID. A malformed, tampered, or query-mismatched cursor shall return HTTP 400 with code `CURSOR_INVALID`.
- **AV-API-008:** An invalid limit or a query longer than the route's accepted maximum shall return the existing HTTP 422 validation response.
- **AV-API-009:** `card_count` and `bank_count` shall describe the owner's full active fleet even when the query matches no transactions.
- **AV-API-010:** `cache_as_of` shall retain the current dashboard meaning: the oldest non-null successful synchronization time among active cards, or null when no active card has synchronized.

### Table behavior

- **AV-TABLE-001:** All transactions shall render a semantic table with visible columns in this order: Date, Merchant, Card number, Bank, Amount, Status, and Actions.
- **AV-TABLE-002:** Card number cells shall display only `•••• {mask}`. When the mask is unavailable, the visible value shall be `Unavailable` and the accessible label shall state that the card number is unavailable. Full PAN data shall never be requested, stored, logged, or rendered.
- **AV-TABLE-003:** Bank cells shall display `card.bank_display_name`; the card name may appear as secondary text in the Card number cell to distinguish cards that share a mask.
- **AV-TABLE-004:** Date, merchant/description, original-description highlighting, category fallback, signed amount, pending state, and Set alert behavior shall use the existing card-row formatting and semantics.
- **AV-TABLE-005:** The table shall show 50 rows initially. When `has_more` is true, **Load more transactions** shall fetch the next page, append it without duplicates, retain current rows while loading, and prevent duplicate concurrent requests.
- **AV-TABLE-006:** A submitted search shall reset aggregate pagination to the first page. Switching away and back may reuse the query cache but shall never append pages from a different query.
- **AV-TABLE-007:** A blank-query empty state shall say that no cached transactions are available yet. A non-blank zero-match state shall say that no transactions match the submitted query. A fleet with no active cards shall direct the owner to Manage connections.
- **AV-TABLE-008:** Initial-load failure shall show a table-specific retryable error without hiding the fleet summary, search control, view toggle, cache status, or existing card-view cache. A next-page failure shall retain loaded rows and allow the owner to retry Load more transactions.
- **AV-TABLE-009:** The table shall remain a semantic table on narrow screens inside a labeled horizontal-scroll region; page content outside that region shall not overflow the viewport.
- **AV-TABLE-010:** The table, toggle, load-more action, empty states, errors, pending state, and masked-card labels shall pass the existing axe smoke test and be usable by keyboard alone.

### Existing behavior preservation

- **AV-COMPAT-001:** All cards shall retain its current grouped results, independent per-card pagination, transaction-limit alerts, and zero-match card panels.
- **AV-COMPAT-002:** Search shall still execute only on explicit submit or Enter; typing alone and switching views shall not write search history.
- **AV-COMPAT-003:** The dashboard shall continue to work from last-known-good browser cache when the browser is offline. All transactions shall use a cache namespace distinct from the existing grouped-search cache and shall never hydrate one query or view from another.
- **AV-COMPAT-004:** Existing routes and response contracts for `/api/transactions/search` and `/api/cards/{card_id}/transactions` shall remain backward compatible.

## UX and Content

The fleet summary and toggle form one responsive header row:

```text
8 cards · 4 banks                         [All cards] [All transactions]
```

At narrow widths, the toggle wraps below the fleet summary while remaining left-aligned and fully visible. The control uses a group label of `Dashboard view`; its selected option is indicated by text, contrast, and programmatic state rather than color alone.

All cards keeps the existing heading and supporting copy. All transactions uses:

- Blank query heading: `All transactions`
- Blank query supporting copy: `Review cached transactions across every connected card.`
- Submitted query heading: `Search results`
- Submitted query supporting copy: `Every matching transaction is combined in one table.`

Table content uses the existing amount and date formatters. The Merchant cell shows merchant name or normalized description as its primary label. For a submitted query, a distinct original description is secondary and receives the same safe literal highlighting used by card rows; without a query, category is secondary when available.

## Data and API Contract

### Request

```http
GET /api/transactions?q=Paze&limit=50&cursor=<opaque-signed-cursor>
```

### Response

```json
{
  "query": "Paze",
  "total_matches": 10,
  "card_count": 8,
  "bank_count": 4,
  "rows": [
    {
      "transaction": {
        "id": "transaction-id",
        "card_id": "card-id",
        "merchant_name": "Paze Checkout",
        "description": "PAZE CHECKOUT PURCHASE",
        "original_description": "POS PURCHASE PAZE CHECKOUT",
        "category": "Shopping",
        "amount_cents": 1999,
        "currency_code": "USD",
        "authorized_date": "2026-08-17",
        "posted_date": "2026-08-18",
        "pending": false
      },
      "card": {
        "id": "card-id",
        "connection_id": "connection-id",
        "bank": "capital-one",
        "bank_display_name": "Capital One",
        "name": "Capital One Rewards Card",
        "official_name": null,
        "mask": "4812",
        "state": "ready",
        "last_successful_sync_at": "2026-08-19T12:00:00Z"
      }
    }
  ],
  "next_cursor": "opaque-signed-cursor-or-null",
  "has_more": true,
  "cache_as_of": "2026-08-19T12:00:00Z"
}
```

The implementation shall name these wire models `AllTransactionRow` and `AllTransactionsResponse`. The existing generated OpenAPI JSON and TypeScript types remain the frontend contract source.

## Rules and Edge Cases

- A transaction belongs to exactly one card; the API joins that card and its active connection before owner filtering.
- Inactive cards and disconnected/tombstoned connections do not contribute rows, fleet counts, bank counts, or freshness.
- Multiple cards with the same last four digits are distinguished by the optional secondary card name and separate bank column.
- Bank count is the number of distinct active connection bank slugs represented by active cards, not the number of search-result banks.
- A pending transaction uses the same date fallback and sort rules as a posted transaction.
- Null-date rows remain available at the end of the result set and can be paginated.
- The API total is the count after owner, active-card, and submitted-query filters but before pagination.
- Cursor values are opaque to the browser. The browser replaces its loaded pages when `q` changes and only appends a page returned for the current query key.
- Unsupported `view` values degrade to All cards rather than showing an error.
- Search-history recording remains tied to explicit search submission, not query hydration, browser navigation, or view changes.

## Acceptance Criteria

- **AC-001 (AV-VIEW-001–006):** Given the dashboard has eight active cards across four banks, when it loads without a `view` parameter, then `8 cards · 4 banks` appears beside an accessible toggle with All cards selected; selecting All transactions updates the URL, preserves `q`, and browser Back restores the earlier view.
- **AC-002 (AV-API-001–002, AV-COMPAT-004):** Given two owners' cached data, when one owner calls `GET /api/transactions`, then only that owner's active-card rows are returned, Plaid is not called, and the existing grouped and per-card endpoints retain their contracts.
- **AC-003 (AV-API-003–010):** Given transactions across several cards with equal, null, posted, and authorized dates, when aggregate pages are requested, then all rows appear exactly once in deterministic global order, fleet counts remain query-independent, freshness is correct, and invalid cursors or limits return the specified errors.
- **AC-004 (AV-TABLE-001–004):** Given aggregate rows from multiple banks, when All transactions is selected, then a semantic table displays the required columns and each row shows the correct bank and masked last four without exposing a full PAN.
- **AC-005 (AV-TABLE-005–006):** Given more than 50 matching rows, when the owner loads more, then the next page appends once in order; changing the submitted query resets pagination and cannot mix results.
- **AC-006 (AV-TABLE-007–008):** Given no cards, no cached transactions, zero search matches, an initial error, or a continuation error, then the corresponding specific state appears and already loaded data remains usable where applicable.
- **AC-007 (AV-TABLE-009–010):** Given keyboard-only use, axe analysis, and a 280-pixel viewport, then the toggle and table remain operable, the table scroll is contained, labels convey selected/pending/unavailable states, and no page-level horizontal overflow occurs.
- **AC-008 (AV-COMPAT-001–003):** Given the owner switches between views, searches, goes offline after a successful load, or returns to All cards, then existing card behavior remains intact, typing/view changes do not write history, and each view/query hydrates only its own last-known-good cache.

## Observability and Privacy

- Existing request status/error logging applies to the new endpoint; transaction descriptions, search terms, card masks, cursor payloads, and financial amounts shall not be added to logs.
- The aggregate endpoint shall be identifiable by route and status code in existing request logs without introducing a new analytics service.
- No new client telemetry is required for this private single-owner feature.
- Only the existing last-four mask may cross the API boundary. Full card numbers and bank credentials remain unavailable to the application.
- Browser persistence uses the existing session-scoped, owner-keyed pattern and contains only data already returned to the authenticated browser.

## Rollout or Migration

- No database migration or data backfill is required.
- The feature ships as an additive dashboard option; All cards remains the default, so rollback consists of removing the new route, client query, toggle, and table without transforming stored data.
- The OpenAPI artifact and generated TypeScript types must be regenerated in the same change as the backend contract.
- Product documentation shall link this feature PRD and explain that the dashboard now offers both grouped-card and aggregate-table views.

## Open Questions

These are review-gate choices with proposed v1 answers; none should be silently changed during implementation:

1. **Does “credit card number” mean the masked last four digits?** Proposed: yes. The application does not and should not possess the full PAN.
2. **Should the selected view persist beyond the URL?** Proposed: no. All cards remains the default, while a bookmarked/shared `view=transactions` URL restores All transactions.
3. **Should the table retain the transaction-level Set alert shortcut?** Proposed: yes, in an Actions column, so switching views does not remove an existing transaction action.
4. **Should columns be user-sortable in v1?** Proposed: no. The table has one deterministic newest-first order; filtering and sorting controls are separate future features.
