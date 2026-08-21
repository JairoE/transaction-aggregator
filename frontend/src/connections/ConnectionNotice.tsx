import { WarningIcon } from '../shell/icons'
import type { components } from '../api/generated'
import { formatExactTimestamp } from '../dashboard/format'

type BankConnectionResponse = components['schemas']['BankConnectionResponse']

/**
 * Mirrors `backend/app/services/connection_health.py`'s `ConnectionState`.
 * The OpenAPI export widens `BankConnectionResponse.state` to plain
 * `string` (the backend field itself is untyped `str`), so this module is
 * the frontend's one place that re-narrows it defensively.
 */
export type ConnectionState =
  | 'ready'
  | 'syncing'
  | 'stale'
  | 'needs_reconnect'
  | 'consent_expired'
  | 'provider_degraded'
  | 'disconnected'

export type ConnectionAction = 'none' | 'sync' | 'reconnect' | 'renew_consent'

const KNOWN_STATES: ReadonlySet<string> = new Set<ConnectionState>([
  'ready',
  'syncing',
  'stale',
  'needs_reconnect',
  'consent_expired',
  'provider_degraded',
  'disconnected',
])

const KNOWN_ACTIONS: ReadonlySet<string> = new Set<ConnectionAction>([
  'none',
  'sync',
  'reconnect',
  'renew_consent',
])

/** Falls back to `disconnected` for any value the frontend doesn't
 * recognize, rather than throwing or silently mis-rendering. */
export function toConnectionState(value: string): ConnectionState {
  return KNOWN_STATES.has(value) ? (value as ConnectionState) : 'disconnected'
}

/** Falls back to `none` (render nothing) for any value the frontend
 * doesn't recognize. */
export function toConnectionAction(value: string): ConnectionAction {
  return KNOWN_ACTIONS.has(value) ? (value as ConnectionAction) : 'none'
}

const ACTION_LABEL: Record<Exclude<ConnectionAction, 'none'>, string> = {
  sync: 'Sync now',
  reconnect: 'Reconnect',
  renew_consent: 'Renew access',
}

/** States that need the owner to act (re-authenticate/re-consent) rather
 * than just waiting out a transient issue — styled and announced more
 * urgently than a plain "stale" or "degraded" notice. */
const DANGER_STATES = new Set<ConnectionState>(['needs_reconnect', 'consent_expired'])

export interface ConnectionNoticeProps {
  bank: BankConnectionResponse
  /** True when the action would fail regardless (e.g. offline). */
  disabled: boolean
  /** True while this card already has a request in flight. */
  busy: boolean
  onAction: () => void
}

/**
 * Per-connection inline notice: the backend's own owner-safe `message`
 * (rendered verbatim — never rephrased here) plus the one action that
 * resolves it. `action` alone decides whether anything renders: every
 * state that needs attention (`stale`, `needs_reconnect`,
 * `consent_expired`, `provider_degraded`) carries a non-`none` action from
 * the backend classifier, while `ready`, `syncing`, and `disconnected` all
 * carry `none` — so this renders nothing for exactly those three states.
 */
export function ConnectionNotice({ bank, disabled, busy, onAction }: ConnectionNoticeProps) {
  const state = toConnectionState(bank.state)
  const action = toConnectionAction(bank.action)

  if (action === 'none') {
    return null
  }

  const tone = DANGER_STATES.has(state) ? 'danger' : 'warning'

  return (
    <div
      className={`connection-notice connection-notice--${tone}`}
      role={tone === 'danger' ? 'alert' : 'status'}
    >
      <WarningIcon />
      <div className="connection-notice__body">
        <p className="connection-notice__message">{bank.message}</p>
        {bank.cache_as_of && (
          <p className="connection-notice__timestamp">
            Cached {formatExactTimestamp(bank.cache_as_of)}
          </p>
        )}
      </div>
      <button
        type="button"
        className="connection-notice__action"
        onClick={onAction}
        disabled={disabled || busy}
      >
        {busy ? 'Working…' : ACTION_LABEL[action]}
      </button>
    </div>
  )
}
