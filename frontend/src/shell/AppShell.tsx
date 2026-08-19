import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'

const STEPS = [
  { step: 1, label: 'Sign in' },
  { step: 2, label: 'Connect banks' },
  { step: 3, label: 'View cards' },
  { step: 4, label: 'Search Paze' },
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
 * Chrome present on every signed-in screen: a four-step progress strip and
 * a header row with the brand mark and a right-aligned status pill.
 */
export function AppShell({ currentStep, statusPillText, actionLink, children }: AppShellProps) {
  const { logout } = useAuth()

  return (
    <div className="app-shell">
      <ol className="progress-strip" aria-label="Setup progress">
        {STEPS.map(({ step, label }) => {
          const completedOrCurrent = step <= currentStep
          return (
            <li
              key={step}
              className={
                completedOrCurrent ? 'progress-strip__step is-active' : 'progress-strip__step'
              }
              aria-current={step === currentStep ? 'step' : undefined}
            >
              <span className="progress-strip__bar" aria-hidden="true" />
              <span className="progress-strip__label">
                {step}. {label}
              </span>
            </li>
          )
        })}
      </ol>
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
      {children}
    </div>
  )
}
