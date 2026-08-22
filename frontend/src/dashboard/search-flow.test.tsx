import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server } from '../test/server'
import { renderAppAt } from '../test/renderApp'
import { authenticatedSessionHandler } from '../test/handlers'
import {
  DASHBOARD_CARDS,
  pazeSearchResponse,
  recentSearchResponse,
  searchHandler,
} from '../test/dashboardFixtures'

async function renderDashboard() {
  const utils = renderAppAt('/dashboard')
  await screen.findByRole('heading', { name: /your credit cards/i })
  return utils
}

describe('explicit search submission flow', () => {
  beforeEach(() => {
    server.use(authenticatedSessionHandler())
  })

  it('issues no search request while typing — only on Enter or the Search button', async () => {
    const requestedQueries: string[] = []
    server.use(
      searchHandler((query) => (query ? pazeSearchResponse() : recentSearchResponse()), (query) =>
        requestedQueries.push(query),
      ),
    )
    const user = userEvent.setup()
    await renderDashboard()
    expect(requestedQueries).toEqual([''])

    const input = screen.getByRole('searchbox', { name: /search transactions/i })
    await user.type(input, 'Paze')
    expect(requestedQueries).toEqual([''])

    await user.click(screen.getByRole('button', { name: /^search$/i }))
    await screen.findByText(/10 matches for/i)
    expect(requestedQueries).toEqual(['', 'Paze'])
  })

  it('submits on Enter and renders the exact grouped match summary', async () => {
    server.use(searchHandler((query) => (query ? pazeSearchResponse() : recentSearchResponse())))
    const user = userEvent.setup()
    await renderDashboard()

    const input = screen.getByRole('searchbox', { name: /search transactions/i })
    await user.type(input, 'Paze{Enter}')

    expect(
      await screen.findByText('10 matches for “Paze” across 8 cards'),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /search results/i })).toBeInTheDocument()
  })

  it('submits on clicking the Search button too', async () => {
    server.use(searchHandler((query) => (query ? pazeSearchResponse() : recentSearchResponse())))
    const user = userEvent.setup()
    await renderDashboard()

    await user.type(screen.getByRole('searchbox', { name: /search transactions/i }), 'Paze')
    await user.click(screen.getByRole('button', { name: /^search$/i }))

    expect(
      await screen.findByText('10 matches for “Paze” across 8 cards'),
    ).toBeInTheDocument()
  })

  it('persists only the submitted phrase and timestamp for this owner', async () => {
    server.use(searchHandler((query) => (query ? pazeSearchResponse() : recentSearchResponse())))
    const user = userEvent.setup()
    await renderDashboard()

    await user.type(screen.getByRole('searchbox', { name: /search transactions/i }), 'Paze{Enter}')
    await screen.findByText(/10 matches for/i)

    expect(window.localStorage).toHaveLength(1)
    const key = window.localStorage.key(0)
    expect(key).toBe('ta:search-history:owner-1')

    const raw = window.localStorage.getItem(key ?? '')
    expect(JSON.parse(raw ?? 'null')).toEqual([
      { query: 'Paze', searchedAt: expect.any(Number) },
    ])
    expect(raw).not.toContain('groups')
    expect(raw).not.toContain('transactions')
  })

  it('restores recent cached transactions on an empty submit', async () => {
    server.use(searchHandler((query) => (query ? pazeSearchResponse() : recentSearchResponse())))
    const user = userEvent.setup()
    await renderDashboard()

    const input = screen.getByRole('searchbox', { name: /search transactions/i })
    await user.type(input, 'Paze{Enter}')
    await screen.findByText(/10 matches for/i)

    await user.click(screen.getByRole('button', { name: /clear search/i }))

    await screen.findByText(/showing recent cached transactions on every card/i)
    expect(screen.getByRole('heading', { name: /your credit cards/i })).toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: /search transactions/i })).toHaveValue('')
  })

  it('clears an active search when the rail navigates to View cards', async () => {
    server.use(searchHandler((query) => (query ? pazeSearchResponse() : recentSearchResponse())))
    const user = userEvent.setup()
    await renderDashboard()

    await user.type(screen.getByRole('searchbox', { name: /search transactions/i }), 'Paze{Enter}')
    await screen.findByRole('heading', { name: /search results/i })

    await user.click(screen.getByRole('link', { name: /view cards/i }))

    expect(await screen.findByRole('heading', { name: /your credit cards/i })).toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: /search transactions/i })).toHaveValue('')
    expect(window.location.pathname).toBe('/dashboard')
    expect(window.location.search).toBe('')
  })

  it('cancels stale in-flight results — a slow first response never overwrites a newer search — and resets every cursor', async () => {
    // A mutable box (rather than a bare `let`) sidesteps a TypeScript
    // control-flow narrowing quirk where a `let` reassigned only inside a
    // Promise executor gets narrowed to `never` at later call sites once an
    // async arrow function elsewhere in the same scope is introduced.
    const gate: { release: (() => void) | null } = { release: null }
    const slowGate = new Promise<void>((resolve) => {
      gate.release = resolve
    })
    server.use(
      searchHandler(async (query) => {
        if (query === 'slowterm') {
          await slowGate
          return {
            query: 'slowterm',
            total_matches: 999,
            card_count: DASHBOARD_CARDS.length,
            cache_as_of: '2026-08-19T12:29:30Z',
            groups: pazeSearchResponse().groups,
          }
        }
        return query ? pazeSearchResponse() : recentSearchResponse()
      }),
    )
    const user = userEvent.setup()
    await renderDashboard()

    const input = screen.getByRole('searchbox', { name: /search transactions/i })
    await user.type(input, 'slowterm{Enter}')
    await user.clear(input)
    await user.type(input, 'Paze{Enter}')

    expect(await screen.findByText(/10 matches for/i)).toBeInTheDocument()

    gate.release?.()
    // Give the now-resolved stale request's microtask queue a turn.
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(screen.queryByText(/999 matches/i)).not.toBeInTheDocument()
    expect(screen.getByText('10 matches for “Paze” across 8 cards')).toBeInTheDocument()
  })
})
