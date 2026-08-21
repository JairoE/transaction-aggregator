import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { CheckIcon } from '../shell/icons'
import { useAuth } from './AuthProvider'

const GENERIC_ERROR_MESSAGE = 'Something went wrong. Try again.'

export function LoginPage() {
  const { login, status } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (status === 'authenticated') {
      navigate('/connections', { replace: true })
    }
  }, [status, navigate])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(email, password)
      navigate('/connections', { replace: true })
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : GENERIC_ERROR_MESSAGE)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-page__intro">
        <p className="eyebrow">One search. Every card.</p>
        <h1>Find any credit-card transaction in seconds.</h1>
        <p>
          Connect Capital One, Chase, Citi, and Wells Fargo once, then search every
          credit card from a single, private dashboard.
        </p>
        <ul className="login-page__points">
          <li>
            <CheckIcon />
            <span>Bank credentials stay with your bank.</span>
          </li>
          <li>
            <CheckIcon />
            <span>Cached history remains searchable offline.</span>
          </li>
          <li>
            <CheckIcon />
            <span>Results stay separated by credit card.</span>
          </li>
        </ul>
      </section>
      <section className="login-page__form-card" aria-labelledby="login-heading">
        <h2 id="login-heading">Sign in to your dashboard</h2>
        <p>Your bank connections are protected behind this owner account.</p>
        <form onSubmit={(event) => void handleSubmit(event)} noValidate>
          <div className="form-field">
            <label htmlFor="login-email">Email</label>
            <input
              id="login-email"
              name="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          <div className="form-field">
            <label htmlFor="login-password">Password</label>
            <input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          {error && (
            <p role="alert" className="form-error">
              {error}
            </p>
          )}
          <button type="submit" className="primary-button" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </section>
    </main>
  )
}
