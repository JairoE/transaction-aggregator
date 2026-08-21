import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { CheckIcon } from './icons'

const STEPS = [
  { step: 1, label: 'Sign in', description: 'Secure owner access' },
  { step: 2, label: 'Connect banks', description: 'Add your card accounts' },
  { step: 3, label: 'View cards', description: 'Review recent activity' },
  { step: 4, label: 'Search Paze', description: 'Find any transaction' },
] as const

export interface AppShellActionLink {
  label: string
  to: string
}

export interface AppShellProps {
  currentStep: 1 | 2 | 3 | 4
  statusPillText: string
  actionLink?: AppShellActionLink
  children: ReactNode
}

/**
 * Chrome present on every screen: a shared header plus a four-step journey
 * rail that keeps the current place visible beside the page content.
 */
export function AppShell({ currentStep, statusPillText, actionLink, children }: AppShellProps) {
  const { logout } = useAuth()

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__brand">
          <span className="app-header__logo" aria-hidden="true" />
          <div>
            <p className="app-header__title">Transaction Aggregator</p>
            <p className="app-header__subtitle">Private · Local-first</p>
          </div>
        </div>
        <div className="app-header__status">
          <span className="status-pill">{statusPillText}</span>
          {actionLink && (
            <Link className="app-header__link" to={actionLink.to}>
              {actionLink.label}
            </Link>
          )}
          <button type="button" className="app-header__sign-out" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      </header>
      <div className="app-shell__layout">
        <aside className="journey-rail" aria-label="Setup progress">
          <div className="journey-rail__intro">
            <p className="journey-rail__eyebrow">Your workflow</p>
            <h2>Find it faster.</h2>
            <p>Four focused steps from secure sign-in to any transaction.</p>
          </div>
          <ol className="journey-steps">
            {STEPS.map(({ step, label, description }) => {
              const isComplete = step < currentStep
              const isCurrent = step === currentStep
              const stateClass = isComplete
                ? 'is-complete'
                : isCurrent
                  ? 'is-current'
                  : 'is-upcoming'

              return (
                <li
                  key={step}
                  className={`journey-step ${stateClass}`}
                  aria-current={isCurrent ? 'step' : undefined}
                >
                  <span className="journey-step__marker" aria-hidden="true">
                    {isComplete ? <CheckIcon /> : String(step).padStart(2, '0')}
                  </span>
                  <span className="journey-step__copy">
                    {isComplete && <span className="sr-only">Completed: </span>}
                    {isCurrent && <span className="sr-only">Current: </span>}
                    <strong>{label}</strong>
                    <span className="journey-step__description">{description}</span>
                  </span>
                </li>
              )
            })}
          </ol>
          <p className="journey-rail__privacy">Private by design · Your data stays yours</p>
        </aside>
        <div className="app-shell__content">{children}</div>
      </div>
    </div>
  )
}
