import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'
import { ApiError, apiClient } from '../api/client'
import type { components } from '../api/generated'
import { CheckIcon, DotIcon, ExternalLinkIcon, WarningIcon } from '../shell/icons'
import { useOnlineStatus } from '../shell/useOnlineStatus'
import { BANKS_BY_SLUG } from './banks'
import { ConnectionNotice, toConnectionAction } from './ConnectionNotice'
import { DemoBankDialog } from './DemoBankDialog'
import { continuationExpiry, clearLinkContinuation, saveLinkContinuation } from './linkContinuation'
import { PlaidLinkLauncher } from './PlaidLinkLauncher'

type BankConnectionResponse = components['schemas']['BankConnectionResponse']
type LinkTokenResponse = components['schemas']['LinkTokenResponse']

const GENERIC_ERROR_MESSAGE = 'Something went wrong. Try again.'

export type BankCardPhase =
  | { kind: 'idle' }
  | { kind: 'confirm-trial-slot' }
  | { kind: 'requesting-link' }
  | { kind: 'awaiting-approval'; mode: 'new' | 'update'; linkToken: string }
  | { kind: 'finishing' }
  | { kind: 'disconnecting' }
  | { kind: 'error'; message: string }

type Phase = BankCardPhase

export interface BankConnectionCardProps {
  bank: BankConnectionResponse
  ownerId: string
  usesDemoBank: boolean
  onAnnounce: (message: string) => void
  onChanged: () => void
}

export function BankConnectionCard({
  bank,
  ownerId,
  usesDemoBank,
  onAnnounce,
  onChanged,
}: BankConnectionCardProps) {
  const meta = BANKS_BY_SLUG[bank.bank]
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const previouslyFocused = useRef<HTMLElement | null>(null)
  const isOnline = useOnlineStatus()
  const connectionAction = toConnectionAction(bank.action)

  const restoreFocus = useCallback(() => {
    previouslyFocused.current?.focus?.()
    previouslyFocused.current = null
  }, [])

  const requestLinkToken = useCallback(
    async (mode: 'new' | 'update', confirmTrialSlot: boolean) => {
      setPhase({ kind: 'requesting-link' })
      try {
        const response =
          mode === 'new'
            ? await apiClient.request<LinkTokenResponse>('/api/connections/link-token', {
                method: 'POST',
                body: JSON.stringify({
                  bank: bank.bank,
                  confirm_trial_slot: confirmTrialSlot,
                }),
              })
            : await apiClient.request<LinkTokenResponse>(
                `/api/connections/${bank.connection_id}/update-token`,
                { method: 'POST' },
              )

        if (!usesDemoBank) {
          saveLinkContinuation(ownerId, {
            bank: bank.bank,
            linkToken: response.link_token,
            expiresAt: continuationExpiry(),
          })
        }
        previouslyFocused.current = document.activeElement as HTMLElement | null
        setPhase({ kind: 'awaiting-approval', mode: response.mode, linkToken: response.link_token })
      } catch (caught) {
        if (caught instanceof ApiError && caught.code === 'TRIAL_SLOT_UNCONFIRMED') {
          setPhase({ kind: 'confirm-trial-slot' })
          return
        }
        setPhase({
          kind: 'error',
          message: caught instanceof ApiError ? caught.message : GENERIC_ERROR_MESSAGE,
        })
      }
    },
    [bank.bank, bank.connection_id, ownerId, usesDemoBank],
  )

  const finishExchange = useCallback(
    async (publicToken: string, institutionId?: string, institutionName?: string) => {
      setPhase({ kind: 'finishing' })
      try {
        await apiClient.request('/api/connections/exchange', {
          method: 'POST',
          body: JSON.stringify({
            bank: bank.bank,
            public_token: publicToken,
            institution_id: institutionId ?? meta.demoInstitutionId,
            institution_name: institutionName ?? meta.displayName,
          }),
        })
        setPhase({ kind: 'idle' })
        restoreFocus()
        onChanged()
      } catch (caught) {
        setPhase({
          kind: 'error',
          message: caught instanceof ApiError ? caught.message : GENERIC_ERROR_MESSAGE,
        })
      }
    },
    [bank.bank, meta.demoInstitutionId, meta.displayName, onChanged, restoreFocus],
  )

  /** Triggers a sync and returns to idle — used both to finish a
   * successful update-mode reconnect/consent-renewal (real or demo) and as
   * the direct "Sync now" action for a merely stale or degraded bank. */
  const triggerSync = useCallback(async () => {
    setPhase({ kind: 'finishing' })
    try {
      if (bank.connection_id) {
        await apiClient.request(`/api/connections/${bank.connection_id}/sync`, {
          method: 'POST',
        })
      }
      setPhase({ kind: 'idle' })
      restoreFocus()
      onChanged()
    } catch (caught) {
      setPhase({
        kind: 'error',
        message: caught instanceof ApiError ? caught.message : GENERIC_ERROR_MESSAGE,
      })
    }
  }, [bank.connection_id, onChanged, restoreFocus])

  function handleConnectClick() {
    void requestLinkToken('new', false)
  }

  function handleConfirmTrialSlot() {
    void requestLinkToken('new', true)
  }

  function handleReconnectClick() {
    void requestLinkToken('update', false)
  }

  /** Dispatches the `ConnectionNotice` action button to whichever flow the
   * backend-classified `action` calls for. */
  function handleNoticeAction() {
    if (connectionAction === 'sync') {
      void triggerSync()
    } else if (connectionAction === 'reconnect' || connectionAction === 'renew_consent') {
      void requestLinkToken('update', false)
    }
  }

  function handleCancelApproval() {
    if (!usesDemoBank) {
      clearLinkContinuation(ownerId)
    }
    setPhase({ kind: 'idle' })
    restoreFocus()
  }

  function handleDemoApprove() {
    if (phase.kind !== 'awaiting-approval') {
      return
    }
    if (phase.mode === 'update') {
      void triggerSync()
      return
    }
    void finishExchange(`public-demo-${bank.bank}`)
  }

  function handlePlaidSuccess(publicToken: string, institutionId: string, institutionName: string) {
    clearLinkContinuation(ownerId)
    if (phase.kind === 'awaiting-approval' && phase.mode === 'update') {
      void triggerSync()
      return
    }
    void finishExchange(publicToken, institutionId, institutionName)
  }

  function handlePlaidExit() {
    clearLinkContinuation(ownerId)
    setPhase({ kind: 'idle' })
    restoreFocus()
  }

  async function handleDisconnect() {
    if (!bank.connection_id) {
      return
    }
    setPhase({ kind: 'disconnecting' })
    try {
      await apiClient.request(`/api/connections/${bank.connection_id}`, {
        method: 'DELETE',
      })
      setPhase({ kind: 'idle' })
      onChanged()
    } catch (caught) {
      setPhase({
        kind: 'error',
        message: caught instanceof ApiError ? caught.message : GENERIC_ERROR_MESSAGE,
      })
    }
  }

  const { chipText, chipIcon, statusLine } = describeStatus(bank, phase)

  useEffect(() => {
    onAnnounce(`${meta.displayName}: ${statusLine}`)
  }, [statusLine, meta.displayName, onAnnounce])

  const busy =
    phase.kind === 'requesting-link' ||
    phase.kind === 'awaiting-approval' ||
    phase.kind === 'finishing'

  return (
    <div className="bank-card">
      <div className="bank-card__header">
        <span className="bank-avatar" aria-hidden="true">
          {meta.initials}
        </span>
        <div className="bank-card__identity">
          <h2>{meta.displayName}</h2>
          <p className="bank-card__status-line">{statusLine}</p>
        </div>
        <span className="status-chip">
          {chipIcon}
          <span>{chipText}</span>
        </span>
      </div>

      <ConnectionNotice
        bank={bank}
        disabled={!isOnline}
        busy={busy}
        onAction={handleNoticeAction}
      />

      {phase.kind === 'error' && (
        <p role="alert" className="bank-card__error">
          {phase.message}
        </p>
      )}

      {phase.kind === 'confirm-trial-slot' && (
        <div className="trial-confirm" role="status">
          <p>
            Connecting a real bank permanently uses one of your 10 Plaid Trial Item
            slots.
          </p>
          <div className="trial-confirm__actions">
            <button
              type="button"
              className="primary-button"
              onClick={handleConfirmTrialSlot}
              disabled={!isOnline}
            >
              Confirm &amp; continue
            </button>
            <button type="button" onClick={() => setPhase({ kind: 'idle' })}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="bank-card__actions">
        {!bank.connected && (
          <button
            type="button"
            className="primary-button"
            onClick={handleConnectClick}
            disabled={busy || phase.kind === 'confirm-trial-slot' || !isOnline}
          >
            {busy ? (
              'Connecting…'
            ) : (
              <>
                <span>Connect {meta.displayName}</span>
                <ExternalLinkIcon />
              </>
            )}
          </button>
        )}
        {bank.connected && (
          <>
            <button type="button" disabled className="bank-card__connected-button">
              <CheckIcon />
              <span>Connected</span>
            </button>
            {connectionAction === 'none' && (
              <button
                type="button"
                onClick={handleReconnectClick}
                disabled={busy || phase.kind === 'disconnecting' || !isOnline}
              >
                Reconnect
              </button>
            )}
            <button
              type="button"
              onClick={() => void handleDisconnect()}
              disabled={busy || phase.kind === 'disconnecting' || !isOnline}
            >
              {phase.kind === 'disconnecting' ? 'Disconnecting…' : 'Disconnect'}
            </button>
          </>
        )}
      </div>

      {phase.kind === 'awaiting-approval' && usesDemoBank && (
        <DemoBankDialog bank={bank.bank} onApprove={handleDemoApprove} onCancel={handleCancelApproval} />
      )}
      {phase.kind === 'awaiting-approval' && !usesDemoBank && (
        <PlaidLinkLauncher
          linkToken={phase.linkToken}
          onSuccess={handlePlaidSuccess}
          onExit={handlePlaidExit}
        />
      )}
    </div>
  )
}

export function describeStatus(
  bank: BankConnectionResponse,
  phase: Phase,
): { chipText: string; chipIcon: ReactElement; statusLine: string } {
  if (
    phase.kind === 'requesting-link' ||
    phase.kind === 'awaiting-approval' ||
    phase.kind === 'finishing'
  ) {
    return {
      chipText: 'Connecting…',
      chipIcon: <DotIcon />,
      statusLine: phase.kind === 'finishing' ? 'Loading transactions…' : 'Connecting…',
    }
  }
  if (phase.kind === 'disconnecting') {
    return { chipText: 'Not connected', chipIcon: <DotIcon />, statusLine: 'Disconnecting…' }
  }
  if (bank.last_error_code) {
    return {
      chipText: 'Needs attention',
      chipIcon: <WarningIcon />,
      statusLine: 'We could not finish connecting. Try reconnecting.',
    }
  }
  if (bank.connected) {
    return {
      chipText: 'Connected',
      chipIcon: <CheckIcon />,
      statusLine:
        bank.card_count > 0
          ? `${bank.card_count} credit card${bank.card_count === 1 ? '' : 's'} loaded`
          : 'Loading accounts…',
    }
  }
  return { chipText: 'Not connected', chipIcon: <DotIcon />, statusLine: 'Ready to connect' }
}
