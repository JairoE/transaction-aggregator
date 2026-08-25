import { afterEach, describe, expect, it } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '../test/server'
import { renderAppAt } from '../test/renderApp'
import { runAxeSmokeTest } from '../test/axe'
import {
  authenticatedSessionHandler,
  connectionsHandler,
  makeConnectionsResponse,
  TEST_CSRF_TOKEN,
  TEST_OWNER,
} from '../test/handlers'
import { DASHBOARD_CARDS, recentSearchResponse, searchHandler } from '../test/dashboardFixtures'
import { formatExactTimestamp } from './format'
import { persistSearchResult } from './searchCache'

function findCard(name: string): HTMLElement {
  const heading = screen.getByRole('heading', { name })
  const card = heading.closest('.bank-card')
  if (!card) {
    throw new Error(`Could not find a .bank-card ancestor for heading "${name}"`)
  }
  return card as HTMLElement
}

async function renderDashboard() {
  const utils = renderAppAt('/dashboard')
  await screen.findByRole('heading', { name: /your credit cards/i })
  await screen.findByRole('region', {
    name: new RegExp(`ending in ${DASHBOARD_CARDS[0].mask}`, 'i'),
  })
  return utils
}

function regionFor(mask: string) {
  return screen.getByRole('region', { name: new RegExp(`ending in ${mask}`, 'i') })
}

/** Flips `navigator.onLine` and fires the matching window event, exactly as
 * a real browser does when connectivity changes. */
function setNetworkOnline(online: boolean) {
  Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: online })
  window.dispatchEvent(new Event(online ? 'online' : 'offline'))
}

describe('connection recovery states', () => {
  // TanStack Query's default `networkMode: 'online'` pauses every query
  // (including ones unrelated to this file's fixtures) whenever its global
  // `onlineManager` believes the browser is offline. Restore real
  // connectivity after every test, even a failing one, so one test setting
  // `navigator.onLine = false` can never strand a later test on "Loading…".
  afterEach(() => {
    act(() => {
      setNetworkOnline(true)
    })
  })

  it('shows needs_reconnect with a Reconnect action that calls update-token, not exchange, for ITEM_LOGIN_REQUIRED', async () => {
    let updateTokenCalls = 0
    let exchangeCalls = 0
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(
        makeConnectionsResponse([
          {
            bank: 'chase',
            connected: true,
            connection_id: 'conn-chase-1',
            card_count: 2,
            institution_name: 'Chase',
            state: 'needs_reconnect',
            action: 'reconnect',
            message: 'This bank needs you to sign in again to keep syncing.',
            last_error_code: 'ITEM_LOGIN_REQUIRED',
          },
        ]),
      ),
      http.post('/api/connections/:connectionId/update-token', () => {
        updateTokenCalls += 1
        return HttpResponse.json({
          link_token: 'link-update-chase',
          bank: 'chase',
          mode: 'update',
          consumes_trial_slot: false,
          production_item_count: 0,
          production_item_limit: 10,
        })
      }),
      http.post('/api/connections/exchange', () => {
        exchangeCalls += 1
        return HttpResponse.json(
          { code: 'UNEXPECTED', message: 'exchange should not be called for a reconnect' },
          { status: 500 },
        )
      }),
      http.post('/api/connections/:connectionId/sync', () =>
        HttpResponse.json(
          {
            job_id: 'job-1',
            connection_id: 'conn-chase-1',
            state: 'queued',
            trigger: 'manual',
            refresh_requested: true,
          },
          { status: 202 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    const card = findCard('Chase')
    expect(
      within(card).getByText(/this bank needs you to sign in again/i),
    ).toBeInTheDocument()

    await user.click(within(card).getByRole('button', { name: /^reconnect$/i }))

    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /approve & return/i }))

    await waitFor(() => expect(updateTokenCalls).toBe(1))
    expect(exchangeCalls).toBe(0)
  })

  it('shows consent_expired with a Renew access action', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(
        makeConnectionsResponse([
          {
            bank: 'citi',
            connected: true,
            connection_id: 'conn-citi-1',
            card_count: 1,
            institution_name: 'Citi',
            state: 'consent_expired',
            action: 'renew_consent',
            message: 'Your access permission is expiring. Renew it to keep syncing.',
            consent_expiration_at: '2026-08-20T00:00:00Z',
          },
        ]),
      ),
      http.post('/api/connections/:connectionId/update-token', () =>
        HttpResponse.json({
          link_token: 'link-update-citi',
          bank: 'citi',
          mode: 'update',
          consumes_trial_slot: false,
          production_item_count: 0,
          production_item_limit: 10,
        }),
      ),
    )
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    const card = findCard('Citi')
    expect(
      within(card).getByText(/your access permission is expiring/i),
    ).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: /renew access/i })).toBeInTheDocument()
  })

  it('keeps cached search results visible and the search input enabled while a bank is provider_degraded', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(
        makeConnectionsResponse([
          {
            bank: 'wells-fargo',
            connected: true,
            connection_id: 'conn-wf-1',
            card_count: 2,
            institution_name: 'Wells Fargo',
            state: 'provider_degraded',
            action: 'sync',
            message:
              'This bank is temporarily unavailable. Cached transactions are still searchable and syncing will retry automatically.',
          },
        ]),
      ),
      searchHandler(() => recentSearchResponse()),
    )
    await renderDashboard()

    for (const card of DASHBOARD_CARDS) {
      expect(regionFor(card.mask ?? '')).toBeInTheDocument()
    }
    expect(screen.getByRole('searchbox', { name: /search transactions/i })).toBeEnabled()
    expect(await screen.findByText(/1 of 4 banks need attention/i)).toBeInTheDocument()
  })

  it('does not hide the other three banks or their transactions when one bank fails', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(
        makeConnectionsResponse([
          {
            bank: 'citi',
            connected: true,
            connection_id: 'conn-citi-1',
            card_count: 2,
            institution_name: 'Citi',
            state: 'needs_reconnect',
            action: 'reconnect',
            message: 'This bank needs you to sign in again to keep syncing.',
            last_error_code: 'ITEM_LOGIN_REQUIRED',
          },
        ]),
      ),
      searchHandler(() => recentSearchResponse()),
    )
    await renderDashboard()

    for (const card of DASHBOARD_CARDS) {
      const region = regionFor(card.mask ?? '')
      expect(within(region).getAllByRole('listitem').length).toBeGreaterThan(0)
    }
  })

  it('labels a bank stale with its exact cache timestamp when data is older than 60 minutes', async () => {
    const staleTimestamp = new Date(Date.now() - 90 * 60 * 1000).toISOString()
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(
        makeConnectionsResponse([
          {
            bank: 'capital-one',
            connected: true,
            connection_id: 'conn-co-1',
            card_count: 2,
            institution_name: 'Capital One',
            state: 'stale',
            action: 'sync',
            message: 'Showing cached transactions. Sync to check for new activity.',
            cache_as_of: staleTimestamp,
          },
        ]),
      ),
    )
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    const card = findCard('Capital One')
    expect(within(card).getByText(/showing cached transactions/i)).toBeInTheDocument()
    expect(
      within(card).getByText(`Cached ${formatExactTimestamp(staleTimestamp)}`),
    ).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: /sync now/i })).toBeInTheDocument()
  })

  it('keeps cached results visible and labels them offline once navigator.onLine goes false', async () => {
    server.use(authenticatedSessionHandler(), searchHandler(() => recentSearchResponse()))
    await renderDashboard()

    for (const card of DASHBOARD_CARDS) {
      expect(regionFor(card.mask ?? '')).toBeInTheDocument()
    }

    act(() => {
      setNetworkOnline(false)
    })

    expect(await screen.findByText(/offline · cached/i)).toBeInTheDocument()
    for (const card of DASHBOARD_CARDS) {
      expect(regionFor(card.mask ?? '')).toBeInTheDocument()
    }
    expect(screen.getByRole('searchbox', { name: /search transactions/i })).toBeEnabled()
  })

  it('disables Sync, Connect, Reconnect, and Disconnect controls while offline', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(
        makeConnectionsResponse([
          {
            bank: 'capital-one',
            connected: true,
            connection_id: 'conn-co-1',
            card_count: 2,
            institution_name: 'Capital One',
            state: 'stale',
            action: 'sync',
            message: 'Showing cached transactions. Sync to check for new activity.',
            cache_as_of: new Date(Date.now() - 90 * 60 * 1000).toISOString(),
          },
          {
            bank: 'chase',
            connected: true,
            connection_id: 'conn-chase-1',
            card_count: 2,
            institution_name: 'Chase',
          },
        ]),
      ),
    )
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    act(() => {
      setNetworkOnline(false)
    })

    const capitalOneCard = findCard('Capital One')
    expect(within(capitalOneCard).getByRole('button', { name: /sync now/i })).toBeDisabled()

    const chaseCard = findCard('Chase')
    expect(within(chaseCard).getByRole('button', { name: /^reconnect$/i })).toBeDisabled()
    expect(within(chaseCard).getByRole('button', { name: /disconnect/i })).toBeDisabled()

    const wellsFargoCard = findCard('Wells Fargo')
    expect(
      within(wellsFargoCard).getByRole('button', { name: /connect wells fargo/i }),
    ).toBeDisabled()
  })

  it('reconnect success re-enables sync and the bank returns to syncing then ready', async () => {
    let callCount = 0
    server.use(
      authenticatedSessionHandler(),
      http.get('/api/connections', () => {
        callCount += 1
        if (callCount === 1) {
          return HttpResponse.json(
            makeConnectionsResponse([
              {
                bank: 'chase',
                connected: true,
                connection_id: 'conn-chase-1',
                card_count: 2,
                institution_name: 'Chase',
                state: 'needs_reconnect',
                action: 'reconnect',
                message: 'This bank needs you to sign in again to keep syncing.',
                last_error_code: 'ITEM_LOGIN_REQUIRED',
              },
            ]),
          )
        }
        if (callCount === 2) {
          return HttpResponse.json(
            makeConnectionsResponse([
              {
                bank: 'chase',
                connected: true,
                connection_id: 'conn-chase-1',
                card_count: 2,
                institution_name: 'Chase',
                state: 'syncing',
                action: 'none',
                message: 'Loading transactions…',
                last_error_code: null,
              },
            ]),
          )
        }
        return HttpResponse.json(
          makeConnectionsResponse([
            {
              bank: 'chase',
              connected: true,
              connection_id: 'conn-chase-1',
              card_count: 2,
              institution_name: 'Chase',
              state: 'ready',
              action: 'none',
              message: 'Up to date.',
              last_error_code: null,
              cache_as_of: '2026-08-19T12:00:00Z',
            },
          ]),
        )
      }),
      http.post('/api/connections/:connectionId/update-token', () =>
        HttpResponse.json({
          link_token: 'link-update-chase',
          bank: 'chase',
          mode: 'update',
          consumes_trial_slot: false,
          production_item_count: 0,
          production_item_limit: 10,
        }),
      ),
      http.post('/api/connections/:connectionId/sync', () =>
        HttpResponse.json(
          {
            job_id: 'job-1',
            connection_id: 'conn-chase-1',
            state: 'queued',
            trigger: 'manual',
            refresh_requested: true,
          },
          { status: 202 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    const card = findCard('Chase')
    await user.click(within(card).getByRole('button', { name: /^reconnect$/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /approve & return/i }))

    await waitFor(
      () => {
        expect(
          within(findCard('Chase')).queryByText(/this bank needs you to sign in again/i),
        ).not.toBeInTheDocument()
        expect(callCount).toBeGreaterThanOrEqual(3)
      },
      { timeout: 4000 },
    )
  })

  it("omits a removed connection's cached transactions instead of showing them as stale", async () => {
    // Seed sessionStorage as if a prior session had already cached a search
    // result that still includes Wells Fargo's cards.
    const staleSnapshot = recentSearchResponse()
    persistSearchResult(TEST_OWNER.id, '', staleSnapshot)

    // Since then, the Wells Fargo connection was removed: the backend no
    // longer returns its cards at all. Gate the live response so the test
    // can observe the *hydrated* (stale, sessionStorage-backed) render
    // before the live fetch resolves — proving this exercises hydration,
    // not just "the live response happens to omit Wells Fargo."
    const freshSnapshot = recentSearchResponse()
    freshSnapshot.groups = freshSnapshot.groups.filter((group) => group.card.bank !== 'wells-fargo')
    freshSnapshot.card_count = freshSnapshot.groups.length

    const gate: { release: (() => void) | null } = { release: null }
    const gatePromise = new Promise<void>((resolve) => {
      gate.release = resolve
    })
    server.use(
      authenticatedSessionHandler(),
      searchHandler(async () => {
        await gatePromise
        return freshSnapshot
      }),
    )

    renderAppAt('/dashboard')
    await screen.findByRole('heading', { name: /your credit cards/i })

    // Hydrated from sessionStorage, before the live fetch resolves: the
    // stale snapshot (including both Wells Fargo cards) is what's on screen.
    expect(screen.getAllByRole('region', { name: /wells fargo/i }).length).toBeGreaterThan(0)

    gate.release?.()

    // Once the live fetch settles, the removed connection's cards are gone
    // — never left behind as if merely "stale".
    await waitFor(() => {
      expect(screen.queryByRole('region', { name: /wells fargo/i })).not.toBeInTheDocument()
    })
    for (const card of DASHBOARD_CARDS.filter((entry) => entry.bank !== 'wells-fargo')) {
      expect(regionFor(card.mask ?? '')).toBeInTheDocument()
    }
  })

  it('never persists the CSRF token or session data to sessionStorage', async () => {
    server.use(authenticatedSessionHandler(), searchHandler(() => recentSearchResponse()))
    await renderDashboard()
    await screen.findByText(/showing recent cached transactions on every card/i)

    await waitFor(() => expect(window.sessionStorage.length).toBeGreaterThan(0))

    for (let index = 0; index < window.sessionStorage.length; index += 1) {
      const key = window.sessionStorage.key(index)
      expect(key).not.toBeNull()
      const value = window.sessionStorage.getItem(key as string) ?? ''
      expect(key as string).not.toContain(TEST_CSRF_TOKEN)
      expect(value).not.toContain(TEST_CSRF_TOKEN)
    }
  })

  it('has no detectable accessibility violations on the dashboard when a bank is degraded', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(
        makeConnectionsResponse([
          {
            bank: 'wells-fargo',
            connected: true,
            connection_id: 'conn-wf-1',
            card_count: 2,
            institution_name: 'Wells Fargo',
            state: 'provider_degraded',
            action: 'sync',
            message:
              'This bank is temporarily unavailable. Cached transactions are still searchable and syncing will retry automatically.',
          },
        ]),
      ),
      searchHandler(() => recentSearchResponse()),
    )
    const { container } = await renderDashboard()
    await screen.findByText(/1 of 4 banks need attention/i)

    await runAxeSmokeTest(container)
  })
})
