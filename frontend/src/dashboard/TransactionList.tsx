import { useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Link } from 'react-router-dom'
import { describeAmount, formatAmount, formatShortDate } from './format'
import { highlightText } from './highlight'
import { useSearchQuery } from './SearchContext'
import type { TransactionMatch } from './api'

export interface TransactionListProps {
  cardId: string
  transactions: TransactionMatch[]
  height: number
}

/** Above this many rendered rows we virtualize; below it a plain list is
 * simpler and avoids any dependency on the (jsdom-unsupported) ResizeObserver
 * actually reporting real measurements. */
const VIRTUALIZATION_THRESHOLD = 50
const ESTIMATED_ROW_HEIGHT = 92

function TransactionRow({ cardId, transaction, query }: {
  cardId: string
  transaction: TransactionMatch
  query: string
}) {
  const merchantLabel = transaction.merchant_name || transaction.description
  const hasQuery = query.trim().length > 0
  const normalizedOriginal = transaction.original_description?.trim().toLowerCase()
  const showOriginalDescription =
    hasQuery && !!transaction.original_description && normalizedOriginal !== merchantLabel.trim().toLowerCase()
  const dateValue = transaction.authorized_date ?? transaction.posted_date

  return (
    <div className="transaction-row">
      <div className="transaction-row__line1">
        <span className="transaction-row__merchant">{highlightText(merchantLabel, query)}</span>
        <span
          className="transaction-row__amount"
          aria-label={describeAmount(transaction.amount_cents, transaction.currency_code)}
        >
          {formatAmount(transaction.amount_cents, transaction.currency_code)}
        </span>
      </div>
      {hasQuery
        ? showOriginalDescription && (
            <p className="transaction-row__secondary">
              {highlightText(transaction.original_description as string, query)}
            </p>
          )
        : transaction.category && <p className="transaction-row__secondary">{transaction.category}</p>}
      <p className="transaction-row__meta">
        {dateValue && <time dateTime={dateValue}>{formatShortDate(dateValue)}</time>}
        {transaction.pending && <span className="transaction-row__pending">Pending</span>}
        <Link
          className="transaction-row__alert-link"
          aria-label={`Set alert for ${merchantLabel}`}
          to={`/transaction-limitations?keyword=${encodeURIComponent(merchantLabel)}&card_id=${encodeURIComponent(cardId)}`}
        >
          Set alert
        </Link>
      </p>
    </div>
  )
}

export function TransactionList({ cardId, transactions, height }: TransactionListProps) {
  const query = useSearchQuery()
  const scrollRef = useRef<HTMLDivElement>(null)
  const shouldVirtualize = transactions.length > VIRTUALIZATION_THRESHOLD

  const virtualizer = useVirtualizer({
    count: transactions.length,
    getScrollElement: () => (shouldVirtualize ? scrollRef.current : null),
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    overscan: 6,
  })

  if (!shouldVirtualize) {
    return (
      <div className="transaction-list" style={{ height, overflowY: 'auto' }} ref={scrollRef}>
        <ul className="transaction-list__rows">
          {transactions.map((transaction) => (
            <li className="transaction-list__row" key={transaction.id}>
              <TransactionRow cardId={cardId} transaction={transaction} query={query} />
            </li>
          ))}
        </ul>
      </div>
    )
  }

  const virtualItems = virtualizer.getVirtualItems()

  return (
    <div className="transaction-list" style={{ height, overflowY: 'auto' }} ref={scrollRef}>
      <ul
        className="transaction-list__rows transaction-list__rows--virtual"
        style={{ height: virtualizer.getTotalSize(), position: 'relative' }}
      >
        {virtualItems.map((virtualRow) => {
          const transaction = transactions[virtualRow.index]
          return (
            <li
              className="transaction-list__row"
              key={transaction.id}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              <TransactionRow cardId={cardId} transaction={transaction} query={query} />
            </li>
          )
        })}
      </ul>
    </div>
  )
}
