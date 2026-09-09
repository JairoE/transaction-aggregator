# Saved Transaction Aggregates

## Goal

Let an owner inspect purchases, refunds, and net total for a transaction keyword
either while searching or as a saved, recurring card-panel summary on the
dashboard. This is informational reporting, not alerting.

## User outcomes

- Searching `Paze` shows monetary totals for the full result set, not only the
  transactions currently visible in a paginated list.
- An owner can save `Paze` or `Dunkin` with an all-card or selected-card scope.
- Each applicable dashboard card shows the saved aggregate independently, so
  one all-card aggregate can show different totals on different cards.
- A summary always shows purchases, refunds, net total, and matching-transaction
  count. Pending matches are included and labelled in supporting copy.

## Definitions and constraints

- Version 1 totals include only USD transactions. Summary counts are named and
  labelled as USD counts so they are not confused with the existing ad-hoc
  `total_matches`, which includes matching transactions in every currency.
- Charges are positive `amount_cents`; refunds are negative `amount_cents`.
  `purchases_cents` is the sum of positive matching amounts.
  `refunds_cents` is the positive absolute value of matching negative amounts.
  `net_total_cents = purchases_cents - refunds_cents`.
- Pending USD transactions are included in all four values and `pending_count`
  records how many of the matching transactions are pending.
- A saved aggregate is never an alert: it has no threshold, no triggered state,
  and no warning styling.
- Existing transaction-limit alerts, their data, URLs, and behavior remain
  unchanged.

## Dashboard behavior

- In card view, render saved aggregate modules below the card art and above the
  transaction list. Show `Saved aggregates` only when that card has at least
  one applicable result.
- Show each module as: keyword; purchases; refunds; net; and supporting copy
  such as `10 matches · 2 pending · All history`.
- An empty matching result still renders for a selected/applicable card as
  `$0.00` values and `0 matches`, so the saved request remains visible.
- In an ad-hoc search, show the same breakdown for each card’s complete result
  set and a combined breakdown in the all-transactions view.
- Display refunds as positive magnitudes and negative net totals as `-$100.00`.
- If the saved-aggregate request fails, continue rendering cards, transactions,
  and transaction-limit alerts; show the aggregate error independently.

## Management behavior

- Add a `Saved aggregates` section to the existing transaction-limitations
  management route. It has a dedicated create/edit form and list; it does not
  overload the alert threshold form.
- The form collects keyword, card scope, and selected cards when applicable.
- Owners can create, edit, and delete only their own saved aggregates.

## API and data model

- Store saved definitions in `transaction_aggregates` and selections in
  `transaction_aggregate_cards`, separate from `transaction_limitations`.
- Expose owner-scoped CRUD at `/api/transaction-aggregates` and evaluated
  dashboard results at `/api/saved-transaction-aggregates`.
- Extend search responses with a USD aggregate summary. Search pagination does
  not affect these totals.

## Out of scope

- Currency conversion or mixed-currency rollups.
- Rolling or fixed date windows and pause/enable controls.
- Push notifications, thresholds, or scheduled jobs.
- Downloadable reports and charts.
