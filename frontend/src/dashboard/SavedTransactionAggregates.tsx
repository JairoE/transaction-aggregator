import { useId } from 'react'
import type { SavedTransactionAggregateResponse } from '../aggregates/api'
import { TransactionAggregateSummary } from './TransactionAggregateSummary'

interface Props {
  aggregates: SavedTransactionAggregateResponse[]
}

export function SavedTransactionAggregates({ aggregates }: Props) {
  const headingId = useId()
  if (aggregates.length === 0) return null

  return (
    <section className="saved-transaction-aggregates" aria-labelledby={headingId}>
      <header className="saved-transaction-aggregates__header">
        <h3 id={headingId}>Saved aggregates</h3>
        <span
          className="saved-transaction-aggregates__info"
          aria-hidden="true"
        >
          i
        </span>
        <span className="sr-only">
          USD totals include pending transactions from all available history.
        </span>
      </header>
      <div className="saved-transaction-aggregates__items">
        {aggregates.map((aggregate) => (
          <article
            className="saved-transaction-aggregate"
            aria-label={`${aggregate.keyword} saved aggregate`}
            key={aggregate.aggregate_id}
          >
            <h4>{aggregate.keyword}</h4>
            <TransactionAggregateSummary summary={aggregate.summary} historyLabel="All history" />
          </article>
        ))}
      </div>
    </section>
  )
}
