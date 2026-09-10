import { useState } from 'react'
import { TransactionList } from './TransactionList'
import { useSearchQuery } from './SearchContext'
import type { DashboardCardGroup } from './CardGrid'
import { TransactionLimitAlerts } from './TransactionLimitAlerts'
import { CreditCardOutline } from './CreditCardOutline'
import { TransactionAggregateSummary } from './TransactionAggregateSummary'
import { SavedTransactionAggregates } from './SavedTransactionAggregates'

const TRANSACTION_VIEWPORT_HEIGHT = 260

export interface CardPanelProps {
  group: DashboardCardGroup
  onLoadMore: () => void
}

export function CardPanel({ group, onLoadMore }: CardPanelProps) {
  const query = useSearchQuery()
  const hasQuery = query.trim().length > 0
  const [isExpanded, setIsExpanded] = useState(true)
  const {
    card,
    transactions,
    match_count: matchCount,
    has_more: hasMore,
    isLoadingMore,
    limitationAlerts,
    savedAggregates,
  } = group
  const contentId = `card-panel-content-${card.id}`
  const action = isExpanded ? 'Collapse' : 'Expand'

  return (
    <section
      className={`card-panel${isExpanded ? '' : ' card-panel--collapsed'}`}
      aria-label={`${card.bank_display_name} card ending in ${card.mask ?? 'unknown'}`}
    >
      <header className="card-panel__header">
        <h3 className="card-panel__title">
          <button
            type="button"
            className="card-panel__toggle"
            aria-expanded={isExpanded}
            aria-controls={contentId}
            aria-label={`${action} ${card.name}`}
            onClick={() => setIsExpanded((expanded) => !expanded)}
          >
            <span>{card.name}</span>
            <span className="disclosure-indicator" aria-hidden="true">
              {isExpanded ? '−' : '+'}
            </span>
          </button>
        </h3>
      </header>
      <div className="card-panel__content" id={contentId} hidden={!isExpanded}>
        <div className="card-panel__status-row">
          <span className="status-chip">
            {hasQuery ? `${matchCount} ${matchCount === 1 ? 'match' : 'matches'}` : 'Synced'}
          </span>
        </div>
        <CreditCardOutline
          bank={card.bank}
          bankDisplayName={card.bank_display_name}
          cardName={card.name}
          mask={card.mask}
        />

        <SavedTransactionAggregates aggregates={savedAggregates} />

        {hasQuery && <TransactionAggregateSummary summary={group.usd_summary} />}

        <TransactionLimitAlerts alerts={limitationAlerts} />

        {transactions.length === 0 ? (
          <p className="card-panel__empty">
            {hasQuery
              ? 'No matching transactions on this card.'
              : 'No cached transactions on this card yet.'}
          </p>
        ) : (
          <TransactionList cardId={card.id} transactions={transactions} height={TRANSACTION_VIEWPORT_HEIGHT} />
        )}

        {hasMore && (
          <button
            type="button"
            className="card-panel__load-more"
            onClick={onLoadMore}
            disabled={isLoadingMore}
            aria-busy={isLoadingMore}
          >
            {isLoadingMore ? 'Loading…' : 'Load more'}
          </button>
        )}
      </div>
    </section>
  )
}
