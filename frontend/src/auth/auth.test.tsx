import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { server } from '../test/server'
import { renderAppAt } from '../test/renderApp'
import { runAxeSmokeTest } from '../test/axe'
import {
  authenticatedSessionHandler,
  connectionsHandler,
  loginFailureHandler,
  loginSuccessHandler,
  logoutHandler,
  makeConnectionsResponse,
} from '../test/handlers'
import { recentAllTransactionsResponse, recentSearchResponse, searchHandler } from '../test/dashboardFixtures'

describe('owner sign-in', () => {
  it('shows the owner sign-in form to an anonymous visitor', async () => {
    renderAppAt('/')

    expect(
      await screen.findByRole('heading', {
        name: /find any credit-card transaction in seconds/i,
      }),
    ).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /email/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /sign out/i })).not.toBeInTheDocument()
  })

  it('has no detectable accessibility violations on the sign-in view', async () => {
    const { container } = renderAppAt('/')
    await screen.findByRole('heading', { name: /find any credit-card transaction/i })

    await runAxeSmokeTest(container)
  })

  it('routes a valid login to the four connection cards', async () => {
    server.use(loginSuccessHandler(), connectionsHandler(makeConnectionsResponse()))
    const user = userEvent.setup()
    renderAppAt('/')

    await user.type(screen.getByRole('textbox', { name: /email/i }), 'owner@example.com')
    await user.type(screen.getByLabelText(/password/i), 'correct horse battery staple')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    expect(
      await screen.findByRole('heading', { name: /connect your credit cards/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Capital One' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Chase' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Citi' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Wells Fargo' })).toBeInTheDocument()
  })

  describe('failed login', () => {
    let consoleLogSpy: ReturnType<typeof vi.spyOn>
    let consoleErrorSpy: ReturnType<typeof vi.spyOn>
    let consoleWarnSpy: ReturnType<typeof vi.spyOn>

    beforeEach(() => {
      consoleLogSpy = vi.spyOn(console, 'log').mockImplementation(() => {})
      consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    })

    afterEach(() => {
      consoleLogSpy.mockRestore()
      consoleErrorSpy.mockRestore()
      consoleWarnSpy.mockRestore()
    })

    it('renders the generic API error and never logs the password', async () => {
      server.use(loginFailureHandler())
      const user = userEvent.setup()
      renderAppAt('/')

      const secretPassword = 'wrong-password-xyz'
      await user.type(screen.getByRole('textbox', { name: /email/i }), 'owner@example.com')
      await user.type(screen.getByLabelText(/password/i), secretPassword)
      await user.click(screen.getByRole('button', { name: /sign in/i }))

      expect(await screen.findByRole('alert')).toHaveTextContent(
        /email or password is incorrect/i,
      )

      for (const spy of [consoleLogSpy, consoleErrorSpy, consoleWarnSpy]) {
        for (const call of spy.mock.calls) {
          const serialized = call.map((arg) => String(arg)).join(' ')
          expect(serialized).not.toContain(secretPassword)
        }
      }
    })
  })

  it('signs the owner out and returns to the sign-in form', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(makeConnectionsResponse()),
      logoutHandler(),
    )
    const user = userEvent.setup()
    window.localStorage.setItem(
      'ta:search-history:owner-1',
      JSON.stringify([{ query: 'Paze', searchedAt: Date.now() }]),
    )
    window.sessionStorage.setItem(
      'transaction-aggregator:all-transactions:v1:owner-1:paze',
      JSON.stringify({ cached: 'owner-1 aggregate transactions' }),
    )
    window.sessionStorage.setItem(
      'transaction-aggregator:all-transactions:v1:owner-2:paze',
      JSON.stringify({ cached: 'owner-2 aggregate transactions' }),
    )
    renderAppAt('/connections')

    expect(
      await screen.findByRole('heading', { name: /connect your credit cards/i }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /sign out/i }))

    expect(
      await screen.findByRole('heading', { name: /find any credit-card transaction/i }),
    ).toBeInTheDocument()
    expect(window.localStorage.getItem('ta:search-history:owner-1')).toContain('Paze')
    expect(
      window.sessionStorage.getItem('transaction-aggregator:all-transactions:v1:owner-1:paze'),
    ).toBeNull()
    expect(
      window.sessionStorage.getItem('transaction-aggregator:all-transactions:v1:owner-2:paze'),
    ).toContain('owner-2 aggregate transactions')
  })

  it('disables sign out while the request is pending', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(makeConnectionsResponse()),
      http.post('/api/auth/logout', async () => {
        await delay(250)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    await user.click(screen.getByRole('button', { name: /sign out/i }))

    expect(screen.getByRole('button', { name: /signing out/i })).toBeDisabled()
    expect(
      await screen.findByRole('heading', { name: /find any credit-card transaction/i }),
    ).toBeInTheDocument()
  })

  it('announces a sign-out failure and keeps the owner signed in', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(makeConnectionsResponse()),
      http.post('/api/auth/logout', () =>
        HttpResponse.json(
          { code: 'LOGOUT_FAILED', message: 'Could not sign out.' },
          { status: 500 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    await user.click(screen.getByRole('button', { name: /sign out/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /we could not sign you out\. try again\./i,
    )
    expect(screen.getByRole('button', { name: /sign out/i })).toBeEnabled()
  })

  it('prunes expired search phrases when an owner session loads', async () => {
    server.use(authenticatedSessionHandler(), connectionsHandler(makeConnectionsResponse()))
    const eightDaysAgo = Date.now() - 8 * 24 * 60 * 60 * 1000
    window.localStorage.setItem(
      'ta:search-history:owner-1',
      JSON.stringify([{ query: 'expired phrase', searchedAt: eightDaysAgo }]),
    )

    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    expect(window.localStorage.getItem('ta:search-history:owner-1')).toBeNull()
  })

  it('does not render a previous owner aggregate result after auth invalidation and a new sign-in', async () => {
    let owner = 'owner-1'
    let aggregateAttempts = 0
    server.resetHandlers()
    server.use(
      http.get('/api/auth/session', () => HttpResponse.json({
        owner: { id: owner, email: `${owner}@example.com` },
        csrf_token: `${owner}-csrf-token-0123456789`,
      })),
      connectionsHandler(makeConnectionsResponse([{ bank: 'capital-one', connected: true, card_count: 1 }])),
      http.get('/api/transaction-limit-alerts', () => HttpResponse.json({
        alerts: [], evaluated_at: '2026-08-22T12:00:00Z', as_of_date: '2026-08-22', cache_as_of: null,
      })),
      searchHandler(() => recentSearchResponse()),
      http.get('/api/transactions', () => {
        aggregateAttempts += 1
        if (aggregateAttempts === 2) {
          return HttpResponse.json({ code: 'AUTH_REQUIRED', message: 'Sign in to continue.' }, { status: 401 })
        }
        return HttpResponse.json(recentAllTransactionsResponse())
      }),
      http.post('/api/auth/login', () => {
        owner = 'owner-2'
        return HttpResponse.json({
          owner: { id: owner, email: `${owner}@example.com` },
          csrf_token: `${owner}-csrf-token-0123456789`,
        })
      }),
    )

    const user = userEvent.setup()
    renderAppAt('/dashboard?view=transactions')
    expect(await screen.findByText('Capital One Newest Purchase')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'All cards' }))
    await user.click(screen.getByRole('button', { name: 'All transactions' }))
    expect(await screen.findByRole('heading', { name: /find any credit-card transaction/i })).toBeInTheDocument()

    await user.type(screen.getByRole('textbox', { name: /email/i }), 'owner-2@example.com')
    await user.type(screen.getByLabelText(/password/i), 'correct horse battery staple')
    await user.click(screen.getByRole('button', { name: /sign in/i }))
    await screen.findByRole('heading', { name: /connect your credit cards/i })
    await user.click(screen.getByRole('button', { name: /view cards/i }))
    await screen.findByRole('heading', { name: /your credit cards/i })
    try {
      Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
      fireEvent(window, new Event('offline'))
      await user.click(screen.getByRole('button', { name: 'All transactions' }))

      expect(aggregateAttempts).toBe(2)
      expect(screen.queryByText('Capital One Newest Purchase')).not.toBeInTheDocument()
    } finally {
      delete (navigator as { onLine?: boolean }).onLine
    }
  })
})
