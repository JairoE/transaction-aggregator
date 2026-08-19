import { Link } from 'react-router-dom'
import { WarningIcon } from '../shell/icons'
import type { components } from '../api/generated'
import { formatExactTimestamp } from './format'

type BankConnectionResponse = components['schemas']['BankConnectionResponse']

/** Connection states worth summarizing here — everything the per-bank
 * `ConnectionNotice` (on the Connections page) would also flag. `ready`,
 * `syncing`, and `disconnected` (never-connected) are deliberately excluded. */
const ATTENTION_STATES = new Set(['stale', 'needs_reconnect', 'consent_expired', 'provider_degraded'])

export interface CacheStatusBannerProps {
  banks: BankConnectionResponse[]
  /** The dashboard's own cache freshness, from the search response. */
  cacheAsOf: string | null
  isOnline: boolean
}

function OfflineIcon() {
  return (
    <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        d="M3 3l14 14M5.5 8a9 9 0 0110.7.9M8.3 11a4.8 4.8 0 014.6 1"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="10" cy="15" r="0.9" fill="currentColor" stroke="none" />
    </svg>
  )
}

/**
 * A single summary strip above the card grid. It may *summarize* trouble
 * ("2 of 4 banks need attention") but it never stands in for the cards
 * themselves — `DashboardPage` always renders `CardGrid` from the same data
 * regardless of what this banner shows, so a failing bank can never hide a
 * healthy one's cards or transactions.
 */
export function CacheStatusBanner({ banks, cacheAsOf, isOnline }: CacheStatusBannerProps) {
  const attentionBanks = banks.filter((bank) => ATTENTION_STATES.has(bank.state))
  const needsAttention = attentionBanks.length > 0

  if (isOnline && !needsAttention) {
    return null
  }

  return (
    <div className="cache-status-banner" role="status">
      {!isOnline && (
        <p className="cache-status-banner__line cache-status-banner__line--offline">
          <OfflineIcon />
          <span>
            Offline · cached {cacheAsOf ? formatExactTimestamp(cacheAsOf) : 'data unavailable'}
          </span>
        </p>
      )}
      {needsAttention && (
        <p className="cache-status-banner__line cache-status-banner__line--attention">
          <WarningIcon />
          <span>
            {attentionBanks.length} of {banks.length} banks need attention.{' '}
            <Link to="/connections">Review connections</Link>
          </span>
        </p>
      )}
    </div>
  )
}
