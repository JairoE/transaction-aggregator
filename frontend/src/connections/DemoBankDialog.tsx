import { useEffect, useRef } from 'react'
import { CheckIcon, ShieldIcon } from '../shell/icons'
import { BANKS_BY_SLUG, type BankSlug } from './banks'

export interface DemoBankDialogProps {
  bank: BankSlug
  onApprove: () => void
  onCancel: () => void
}

/**
 * Simulated bank-hosted handoff, rendered instead of `react-plaid-link` when
 * the backend runs the deterministic local demo bank. Approving calls the
 * exchange endpoint directly with a fixed demo public token; nothing here
 * ever touches a real Plaid Link token.
 */
export function DemoBankDialog({ bank, onApprove, onCancel }: DemoBankDialogProps) {
  const meta = BANKS_BY_SLUG[bank]
  const dialogRef = useRef<HTMLDivElement>(null)
  const approveRef = useRef<HTMLButtonElement>(null)
  const headingId = `demo-dialog-heading-${bank}`

  useEffect(() => {
    approveRef.current?.focus()

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCancel()
        return
      }
      if (event.key !== 'Tab') {
        return
      }
      const focusable = dialogRef.current?.querySelectorAll<HTMLButtonElement>('button')
      if (!focusable || focusable.length === 0) {
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onCancel])

  return (
    <div className="demo-dialog-overlay">
      <div
        className="demo-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        ref={dialogRef}
      >
        <div className="demo-dialog__header">
          <span className="bank-avatar" aria-hidden="true">
            {meta.initials}
          </span>
          <p className="demo-dialog__eyebrow">Bank-hosted sign-in</p>
        </div>
        <h2 id={headingId}>Continue to {meta.displayName}</h2>
        <p>
          {meta.displayName} securely verifies your identity. Transaction Aggregator
          never receives your username or password.
        </p>
        <ul className="demo-dialog__checklist">
          <li>
            <CheckIcon />
            <span>Approve access to transaction history.</span>
          </li>
          <li>
            <CheckIcon />
            <span>Select both available credit cards.</span>
          </li>
          <li>
            <CheckIcon />
            <span>Return here after approval.</span>
          </li>
        </ul>
        <button
          type="button"
          ref={approveRef}
          className="demo-dialog__approve primary-button"
          onClick={onApprove}
        >
          <ShieldIcon />
          <span>Approve &amp; return</span>
        </button>
        <button type="button" className="demo-dialog__cancel" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}
