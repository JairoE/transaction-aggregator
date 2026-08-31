import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '../test/server'
import { renderAppAt } from '../test/renderApp'
import { runAxeSmokeTest } from '../test/axe'
import { authenticatedSessionHandler } from '../test/handlers'
import {
  DASHBOARD_CARDS,
  aggregateNextPage,
  allTransactionsHandler,
  emptyAllTransactionsResponse,
  pazeFirstCardNextPage,
  pazeSearchResponse,
  pazeAllTransactionsResponse,
  recentAllTransactionsResponse,
  searchHandler,
  recentSearchResponse,
} from '../test/dashboardFixtures'

async function renderDashboard(path = '/dashboard') {
  const utils = renderAppAt(path)
  await screen.findByRole('heading', { name: /your credit cards|all transactions|search results/i })
  return utils
}

describe('All transactions dashboard view', () => {
  beforeEach(() => {
    server.use(authenticatedSessionHandler(), searchHandler(() => recentSearchResponse()))
  })

  it('keeps All cards selected by default and never calls the aggregate endpoint', async () => {
    const aggregateRequests: string[] = []
    server.use(
      searchHandler(() => recentSearchResponse()),
      allTransactionsHandler((query) => {
        aggregateRequests.push(query)
        return recentAllTransactionsResponse()
      }),
    )

    await renderDashboard()

    expect(screen.getByRole('button', { name: 'All cards' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'All transactions' })).toHaveAttribute('aria-pressed', 'false')
    expect(aggregateRequests).toEqual([])
  })

  it('uses only the aggregate endpoint in the table view, preserves q, and renders pinned headers', async () => {
    const searchRequests: string[] = []
    const aggregateRequests: string[] = []
    server.use(
      searchHandler(() => recentSearchResponse(), (query) => searchRequests.push(query)),
      allTransactionsHandler((query) => {
        aggregateRequests.push(query)
        return pazeAllTransactionsResponse()
      }),
    )

    await renderDashboard('/dashboard?q=Paze&view=transactions')

    expect(await screen.findByRole('table', { name: /transactions across all cards/i })).toBeInTheDocument()
    expect(searchRequests).toEqual([])
    expect(aggregateRequests).toEqual(['Paze'])
    expect([...screen.getAllByRole('columnheader')].map((header) => header.textContent)).toEqual([
      'Date', 'Merchant', 'Card number', 'Bank', 'Amount', 'Status', 'Actions',
    ])
    expect(screen.getByRole('region', { name: /scrollable transactions table/i })).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'All cards' }))
    expect(window.location.search).toBe('?q=Paze')
  })

  it('renders global row identity, amount, status, unavailable mask, date fallback, and alert action safely', async () => {
    server.use(
      allTransactionsHandler(() => {
        const response = recentAllTransactionsResponse()
        response.rows[1].card = { ...response.rows[1].card, mask: null }
        return response
      }),
    )

    await renderDashboard('/dashboard?view=transactions')

    const rows = await screen.findAllByRole('row')
    expect(rows[1]).toHaveTextContent(/Aug 21.*Capital One Newest Purchase.*•••• 4812.*Capital One.*\$48\.12.*Posted/i)
    expect(rows[2]).toHaveTextContent(/Aug 20.*Chase Pending Purchase.*Unavailable.*Chase.*\+\$12\.50.*Pending/i)
    expect(rows[3]).toHaveTextContent(/Aug 19.*Citi Authorized Purchase/i)
    expect(rows[4]).toHaveTextContent(/Date unavailable.*Wells Fargo Unknown Date/i)
    expect(within(rows[2]).getByLabelText('Card number unavailable')).toHaveTextContent('Unavailable')
    expect(within(rows[1]).getByLabelText(/charged/i)).toHaveTextContent('$48.12')
    expect(within(rows[1]).getByRole('link', { name: /set alert for capital one newest purchase/i })).toHaveAttribute(
      'href',
      `/transaction-limitations?keyword=${encodeURIComponent('Capital One Newest Purchase')}&card_id=${encodeURIComponent(DASHBOARD_CARDS[0].id)}`,
    )
  })

  it('redacts PAN-like sequences from live aggregate display fields and alert links', async () => {
    server.use(
      allTransactionsHandler(() => {
        const response = recentAllTransactionsResponse()
        response.rows[0] = {
          transaction: {
            ...response.rows[0].transaction,
            merchant_name: 'Merchant 4111  1111  1111  1111',
            category: 'Category 5555-5555-5555-4444',
          },
          card: {
            ...response.rows[0].card,
            name: 'Card 4000\t0000\t0000\t0002',
            bank_display_name: 'Bank 6011\u00a01111\u00a01111\u00a01117',
          },
        }
        return response
      }),
    )

    await renderDashboard('/dashboard?view=transactions')

    const row = (await screen.findAllByRole('row'))[1]
    expect(row).toHaveTextContent(/Merchant \[card number redacted\]/i)
    expect(row).toHaveTextContent(/Category \[card number redacted\]/i)
    expect(row).toHaveTextContent(/Card \[card number redacted\]/i)
    expect(row).toHaveTextContent(/Bank \[card number redacted\]/i)
    expect(row.textContent).not.toMatch(/(?:\d[\s-]*){13,19}/)
    expect(within(row).getByRole('link', { name: /set alert/i }).getAttribute('href')).not.toMatch(
      /(?:\d[\s%-]*){13,19}/,
    )
  })

  it('appends one next page, disables its action while pending, retains rows after failure, and retries', async () => {
    let continuationAttempts = 0
    let releaseContinuation: (() => void) | undefined
    const pendingContinuation = new Promise<void>((resolve) => {
      releaseContinuation = resolve
    })
    server.use(
      http.get('/api/transactions', async ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor')
        if (!cursor) {
          return HttpResponse.json(recentAllTransactionsResponse())
        }
        continuationAttempts += 1
        if (continuationAttempts === 1) {
          await pendingContinuation
          return HttpResponse.json({ ...aggregateNextPage(), has_more: true, next_cursor: 'aggregate-third-page' })
        }
        return HttpResponse.json({ code: 'REQUEST_FAILED', message: 'Temporary failure.' }, { status: 500 })
      }),
    )
    const user = userEvent.setup()
    await renderDashboard('/dashboard?view=transactions')

    await screen.findByText('Capital One Newest Purchase')
    const loadMore = screen.getByRole('button', { name: /load more transactions/i })
    await user.click(loadMore)
    expect(loadMore).toBeDisabled()
    releaseContinuation?.()
    expect(await screen.findByText('Wells Fargo Later Purchase')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /load more transactions/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load more transactions. Try again.')
    expect(screen.getByText('Capital One Newest Purchase')).toBeInTheDocument()
    expect(screen.getByText('Wells Fargo Later Purchase')).toBeInTheDocument()
  })

  it('discards a continuation response after the owner switches views', async () => {
    let releaseContinuation: (() => void) | undefined
    const pendingContinuation = new Promise<void>((resolve) => {
      releaseContinuation = resolve
    })
    server.use(
      allTransactionsHandler(() => recentAllTransactionsResponse()),
      http.get('/api/transactions', async ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor')
        if (!cursor) return HttpResponse.json(recentAllTransactionsResponse())
        await pendingContinuation
        return HttpResponse.json(aggregateNextPage())
      }),
    )
    const user = userEvent.setup()
    await renderDashboard('/dashboard?view=transactions')

    await user.click(await screen.findByRole('button', { name: /load more transactions/i }))
    await user.click(screen.getByRole('button', { name: 'All cards' }))
    await user.click(screen.getByRole('button', { name: 'All transactions' }))
    releaseContinuation?.()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /load more transactions/i })).toBeEnabled()
      expect(screen.queryByText('Wells Fargo Later Purchase')).not.toBeInTheDocument()
    })
  })

  it('discards a card continuation response after submitting a different query', async () => {
    let releaseContinuation: (() => void) | undefined
    const pendingContinuation = new Promise<void>((resolve) => {
      releaseContinuation = resolve
    })
    server.use(
      searchHandler((query) => (query === 'Paze' ? pazeSearchResponse() : recentSearchResponse())),
      http.get('/api/cards/:cardId/transactions', async ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor')
        if (cursor) {
          await pendingContinuation
          return HttpResponse.json(pazeFirstCardNextPage())
        }
        return HttpResponse.json(pazeFirstCardNextPage())
      }),
    )
    const user = userEvent.setup()
    await renderDashboard()

    await user.type(screen.getByRole('searchbox', { name: /search transactions/i }), 'Paze{Enter}')
    const targetRegion = screen.getByRole('region', { name: /capital one card ending in 4812/i })
    await user.click(within(targetRegion).getByRole('button', { name: /load more/i }))
    await user.type(screen.getByRole('searchbox', { name: /search transactions/i }), 'Juniper{Enter}')
    await screen.findByText(/every matching transaction remains grouped/i)
    await screen.findAllByText('Capital One Everyday Purchase')

    releaseContinuation?.()
    await waitFor(() => expect(screen.queryByText('Paze Checkout 2')).not.toBeInTheDocument())
  })

  it('discards a card continuation response after switching away and back', async () => {
    let releaseContinuation: (() => void) | undefined
    const pendingContinuation = new Promise<void>((resolve) => {
      releaseContinuation = resolve
    })
    server.use(
      searchHandler((query) => (query === 'Paze' ? pazeSearchResponse() : recentSearchResponse())),
      allTransactionsHandler(() => recentAllTransactionsResponse()),
      http.get('/api/cards/:cardId/transactions', async () => {
        await pendingContinuation
        return HttpResponse.json(pazeFirstCardNextPage())
      }),
    )
    const user = userEvent.setup()
    await renderDashboard()

    await user.type(screen.getByRole('searchbox', { name: /search transactions/i }), 'Paze{Enter}')
    const targetRegion = screen.getByRole('region', { name: /capital one card ending in 4812/i })
    await user.click(within(targetRegion).getByRole('button', { name: /load more/i }))
    await user.click(screen.getByRole('button', { name: 'All transactions' }))
    await user.click(screen.getByRole('button', { name: 'All cards' }))
    releaseContinuation?.()

    await waitFor(() => expect(screen.queryByText('Paze Checkout 2')).not.toBeInTheDocument())
  })

  it('resets aggregate rows on an explicit new search without writing history during a view change', async () => {
    const aggregateRequests: string[] = []
    server.use(
      allTransactionsHandler((query) => {
        aggregateRequests.push(query)
        return query === 'Paze' ? pazeAllTransactionsResponse() : recentAllTransactionsResponse()
      }),
    )
    const user = userEvent.setup()
    await renderDashboard('/dashboard?view=transactions')
    await screen.findByText('Capital One Newest Purchase')

    await user.type(screen.getByRole('searchbox', { name: /search transactions/i }), 'Paze{Enter}')
    expect(await screen.findByRole('row', { name: /Paze aggregate 1/i })).toBeInTheDocument()
    expect(screen.queryByText('Capital One Newest Purchase')).not.toBeInTheDocument()
    expect(window.localStorage).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: 'All cards' }))
    expect(window.location.search).toBe('?q=Paze')
    expect(window.localStorage).toHaveLength(1)
    expect(aggregateRequests).toEqual(['', 'Paze'])
  })

  it('defaults unsupported views to All cards', async () => {
    server.use(searchHandler(() => recentSearchResponse()))
    await renderDashboard('/dashboard?view=not-a-view')
    expect(screen.getByRole('button', { name: 'All cards' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows no-card, blank/search-empty, and initial-error retry states', async () => {
    server.use(allTransactionsHandler(() => ({ ...emptyAllTransactionsResponse(), card_count: 0, bank_count: 0 })))
    const noCards = await renderDashboard('/dashboard?view=transactions')
    expect(await screen.findByText(/No active cards are available/i)).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'All transactions' })).getByRole('link', { name: /manage connections/i })).toHaveAttribute('href', '/connections')
    noCards.unmount()

    server.use(allTransactionsHandler(() => emptyAllTransactionsResponse()))
    const { unmount } = await renderDashboard('/dashboard?view=transactions')
    expect(await screen.findByText('No cached transactions are available yet.')).toBeInTheDocument()
    unmount()

    server.use(allTransactionsHandler(() => emptyAllTransactionsResponse('Paze')))
    const searchEmpty = await renderDashboard('/dashboard?q=Paze&view=transactions')
    expect(await screen.findByText('No transactions match the submitted query.')).toBeInTheDocument()
    searchEmpty.unmount()

    let attempt = 0
    server.use(http.get('/api/transactions', () => {
      attempt += 1
      return attempt === 1
        ? HttpResponse.json({ code: 'REQUEST_FAILED', message: 'Temporary failure.' }, { status: 500 })
        : HttpResponse.json({ ...recentAllTransactionsResponse(), query: 'retry-query' })
    }))
    const user = userEvent.setup()
    await renderDashboard('/dashboard?q=retry-query&view=transactions')
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load transactions. Try again.')
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Capital One Newest Purchase')).toBeInTheDocument()
  })

  it('hydrates offline only from the matching owner and submitted-query cache', async () => {
    let requests = 0
    server.use(allTransactionsHandler((query) => {
      requests += 1
      return query === 'Paze' ? pazeAllTransactionsResponse() : recentAllTransactionsResponse()
    }))
    const onlineResult = await renderDashboard('/dashboard?q=Paze&view=transactions')
    expect(await screen.findByRole('row', { name: /Paze aggregate 1/i })).toBeInTheDocument()
    onlineResult.unmount()

    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
    try {
      const sameScope = await renderDashboard('/dashboard?q=Paze&view=transactions')
      expect(await screen.findByRole('row', { name: /Paze aggregate 1/i })).toBeInTheDocument()
      expect(requests).toBe(1)
      sameScope.unmount()

      server.use(http.get('/api/auth/session', () => HttpResponse.json({
        owner: { id: 'owner-2', email: 'other@example.com' },
        csrf_token: 'second-owner-csrf-token-0123456789',
      })))
      await renderDashboard('/dashboard?q=Paze&view=transactions')
      expect(screen.queryByRole('row', { name: /Paze aggregate 1/i })).not.toBeInTheDocument()
      expect(requests).toBe(1)
    } finally {
      delete (navigator as { onLine?: boolean }).onLine
    }
  })

  it('keeps the aggregate table accessible', async () => {
    server.use(allTransactionsHandler(() => recentAllTransactionsResponse()))
    const { container } = await renderDashboard('/dashboard?view=transactions')
    await screen.findByRole('table')
    await runAxeSmokeTest(container)
  })

  it('marks the initial retry unavailable while offline and does not request on click', async () => {
    let attempts = 0
    server.use(http.get('/api/transactions', () => {
      attempts += 1
      return HttpResponse.json({ code: 'REQUEST_FAILED', message: 'Temporary failure.' }, { status: 500 })
    }))
    await renderDashboard('/dashboard?view=transactions')
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not load transactions/i)
    expect(attempts).toBe(1)

    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
    try {
      Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
      fireEvent(window, new Event('offline'))
      const retry = screen.getByRole('button', { name: 'Retry' })
      await waitFor(() => expect(retry).toBeDisabled())
      await userEvent.setup().click(retry)
      expect(attempts).toBe(1)
    } finally {
      delete (navigator as { onLine?: boolean }).onLine
    }
  })
})
