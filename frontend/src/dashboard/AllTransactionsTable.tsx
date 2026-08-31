import { Link } from 'react-router-dom'
import { describeAmount, formatAmount, formatShortDate } from './format'
import { highlightText } from './highlight'
import type { AllTransactionRow } from './api'

const PAN_LIKE_SEQUENCE = /(?<![0-9])(?:[0-9][\s-]*){12,18}[0-9](?![\s-]*[0-9])/gu
const REDACTED_CARD_NUMBER = '[card number redacted]'

export interface AllTransactionsTableProps {
  query: string
  rows: AllTransactionRow[]
  cardCount: number
  hasMore: boolean
  isLoadingMore: boolean
  continuationError: boolean
  initialError: boolean
  canRetryInitial: boolean
  onRetryInitial: () => void
  onLoadMore: () => void
}

function cardMask(mask: string | null): string | null {
  return mask && /^\d{4}$/.test(mask) ? mask : null
}

function safeDisplayText(value: string): string {
  return value.replace(PAN_LIKE_SEQUENCE, REDACTED_CARD_NUMBER)
}

function TransactionTableRow({ row, query }: { row: AllTransactionRow; query: string }) {
  const { transaction, card } = row
  const merchantLabel = safeDisplayText(transaction.merchant_name || transaction.description)
  const dateValue = transaction.posted_date ?? transaction.authorized_date
  const originalDescription = transaction.original_description
    ? safeDisplayText(transaction.original_description.trim())
    : null
  const category = transaction.category ? safeDisplayText(transaction.category) : null
  const cardName = safeDisplayText(card.name)
  const bankDisplayName = safeDisplayText(card.bank_display_name)
  const showOriginalDescription =
    !!query &&
    !!originalDescription &&
    originalDescription.toLowerCase() !== merchantLabel.trim().toLowerCase()
  const mask = cardMask(card.mask)

  return (
    <tr>
      <td>{dateValue ? <time dateTime={dateValue}>{formatShortDate(dateValue)}</time> : 'Date unavailable'}</td>
      <td>
        <span>{highlightText(merchantLabel, query)}</span>
        {showOriginalDescription ? (
          <span className="all-transactions-table__secondary">
            {highlightText(originalDescription, query)}
          </span>
        ) : !query && category ? (
          <span className="all-transactions-table__secondary">{category}</span>
        ) : null}
      </td>
      <td>
        {mask ? (
          <span aria-label={`Card ending in ${mask}`}>•••• {mask}</span>
        ) : (
          <span aria-label="Card number unavailable">Unavailable</span>
        )}
        <span className="all-transactions-table__secondary">{cardName}</span>
      </td>
      <td>{bankDisplayName}</td>
      <td aria-label={describeAmount(transaction.amount_cents, transaction.currency_code)}>
        {formatAmount(transaction.amount_cents, transaction.currency_code)}
      </td>
      <td>{transaction.pending ? 'Pending' : 'Posted'}</td>
      <td>
        <Link
          aria-label={`Set alert for ${merchantLabel}`}
          to={`/transaction-limitations?keyword=${encodeURIComponent(merchantLabel)}&card_id=${encodeURIComponent(card.id)}`}
        >
          Set alert
        </Link>
      </td>
    </tr>
  )
}

/** The aggregate view's stateful table section; all untrusted text stays React-rendered. */
export function AllTransactionsTable({
  query,
  rows,
  cardCount,
  hasMore,
  isLoadingMore,
  continuationError,
  initialError,
  canRetryInitial,
  onRetryInitial,
  onLoadMore,
}: AllTransactionsTableProps) {
  if (initialError) {
    return (
      <section className="all-transactions-table" aria-label="All transactions">
        <p role="alert">We could not load transactions. Try again.</p>
        <button type="button" onClick={onRetryInitial} disabled={!canRetryInitial}>
          Retry
        </button>
      </section>
    )
  }

  if (cardCount === 0) {
    return (
      <section className="all-transactions-table" aria-label="All transactions">
        <p>
          No active cards are available. <Link to="/connections">Manage connections</Link> to add a card.
        </p>
      </section>
    )
  }

  if (rows.length === 0) {
    return (
      <section className="all-transactions-table" aria-label="All transactions">
        <p>{query ? 'No transactions match the submitted query.' : 'No cached transactions are available yet.'}</p>
      </section>
    )
  }

  return (
    <section className="all-transactions-table" aria-label="All transactions">
      <div
        className="all-transactions-table__scroll"
        role="region"
        tabIndex={0}
        aria-label="Scrollable transactions table"
      >
        <table>
          <caption className="sr-only">Transactions across all cards</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Merchant</th>
              <th scope="col">Card number</th>
              <th scope="col">Bank</th>
              <th scope="col">Amount</th>
              <th scope="col">Status</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <TransactionTableRow key={row.transaction.id} row={row} query={query} />
            ))}
          </tbody>
        </table>
      </div>
      {continuationError && <p role="alert">We could not load more transactions. Try again.</p>}
      {hasMore && (
        <button
          type="button"
          onClick={onLoadMore}
          disabled={isLoadingMore}
          aria-busy={isLoadingMore}
        >
          {isLoadingMore ? 'Loading more transactions…' : 'Load more transactions'}
        </button>
      )}
    </section>
  )
}
