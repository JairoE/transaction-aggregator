import type { TransactionAggregateSummaryResponse } from './api'
import { formatUsdAggregate } from './format'

export interface TransactionAggregateSummaryProps {
  summary: TransactionAggregateSummaryResponse
  historyLabel?: string
}

export function TransactionAggregateSummary({
  summary,
  historyLabel,
}: TransactionAggregateSummaryProps) {
  const matchWord = summary.usd_match_count === 1 ? 'match' : 'matches'
  const details = [
    `${summary.usd_match_count} USD ${matchWord}`,
    summary.usd_pending_count > 0 ? `${summary.usd_pending_count} pending` : null,
    historyLabel,
  ].filter(Boolean)

  return (
    <div className="transaction-aggregate-summary" aria-label="USD transaction aggregate">
      <dl className="transaction-aggregate-summary__metrics">
        <div>
          <dt>Purchases</dt>
          <dd>{formatUsdAggregate(summary.purchases_cents)}</dd>
        </div>
        <div>
          <dt>Refunds</dt>
          <dd>{formatUsdAggregate(summary.refunds_cents)}</dd>
        </div>
        <div>
          <dt>Net</dt>
          <dd>{formatUsdAggregate(summary.net_total_cents)}</dd>
        </div>
      </dl>
      <p className="transaction-aggregate-summary__details">{details.join(' · ')}</p>
    </div>
  )
}
