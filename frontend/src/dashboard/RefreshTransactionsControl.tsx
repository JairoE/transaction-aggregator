import { Link } from 'react-router-dom'
import type { UseTransactionRefreshResult } from './useTransactionRefresh'

interface RefreshTransactionsControlProps {
  refresh: UseTransactionRefreshResult
  isOnline: boolean
}

export function RefreshTransactionsControl({
  refresh,
  isOnline,
}: RefreshTransactionsControlProps) {
  const { run } = refresh
  const changes = (run?.summary.added ?? 0) + (run?.summary.modified ?? 0)
  const unsupported = run?.targets.some(
    (target) => target.state === 'automatic_updates_only',
  )

  let result: React.ReactNode = null
  if (!isOnline) {
    result = 'Connect to the internet to check for new transactions.'
  } else if (refresh.foregroundTimedOut) {
    result = 'This check is still running in the background. You can keep using the dashboard.'
  } else if (run?.state === 'succeeded') {
    result = changes > 0
      ? `${changes} new or updated ${changes === 1 ? 'transaction' : 'transactions'} found.`
      : unsupported
        ? 'Your banks use automatic updates only. The cached transactions were checked.'
        : 'Transactions are up to date. Banks may still be processing recent activity.'
  } else if (run?.state === 'partial' || run?.state === 'failed') {
    result = (
      <>
        The check finished with connections needing attention.{' '}
        <Link to="/connections">Manage connections</Link>
      </>
    )
  } else if (refresh.error) {
    result = 'The check could not be started. Your existing transactions are still available.'
  }

  return (
    <section className="transaction-refresh" aria-label="Transaction freshness">
      <div className="transaction-refresh__action">
        <div>
          <h2>Latest transactions</h2>
          <p>Ask connected banks for available updates, then check the local cache.</p>
        </div>
        <button
          type="button"
          className="transaction-refresh__button"
          disabled={!isOnline || refresh.isStarting || refresh.isActive}
          onClick={refresh.start}
        >
          {(refresh.isStarting || refresh.isActive) && (
            <span className="transaction-refresh__spinner" aria-hidden="true" />
          )}
          {refresh.isStarting || refresh.isActive
            ? 'Checking…'
            : 'Check for new transactions'}
        </button>
      </div>

      {run && refresh.isActive && (
        <div className="transaction-refresh__progress">
          <progress
            aria-label={`${run.summary.completed} of ${run.summary.total} connections checked`}
            max={Math.max(1, run.summary.total)}
            value={run.summary.completed}
          />
          <span>
            Checking {run.summary.completed} of {run.summary.total} connections…
          </span>
        </div>
      )}

      <p className="transaction-refresh__status">
        {result}
      </p>
      <span className="sr-only" role="status" aria-live="polite">
        {refresh.announcement}
      </span>
    </section>
  )
}
