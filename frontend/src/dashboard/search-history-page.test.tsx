import { beforeEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server } from '../test/server'
import { renderAppAt } from '../test/renderApp'
import { runAxeSmokeTest } from '../test/axe'
import { authenticatedSessionHandler } from '../test/handlers'
import { pazeSearchResponse, recentSearchResponse, searchHandler } from '../test/dashboardFixtures'

describe('search history page', () => {
  beforeEach(() => {
    server.use(
      authenticatedSessionHandler(),
      searchHandler((query) => (query ? pazeSearchResponse() : recentSearchResponse())),
    )
  })

  it('opens a saved phrase on the dashboard and reruns the search', async () => {
    const user = userEvent.setup()
    renderAppAt('/dashboard')
    await screen.findByRole('heading', { name: /your credit cards/i })

    const input = screen.getByRole('searchbox', { name: /search transactions/i })
    await user.type(input, 'Paze{Enter}')
    await screen.findByText(/10 matches for/i)

    await user.click(screen.getByRole('link', { name: /search history/i }))
    expect(await screen.findByRole('heading', { name: /^search history$/i })).toBeInTheDocument()
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: /Paze/i }))
    expect(await screen.findByRole('heading', { name: /search results/i })).toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: /search transactions/i })).toHaveValue('Paze')
    expect(window.location.pathname).toBe('/dashboard')
    expect(window.location.search).toBe('?q=Paze')
  })

  it('explains the seven-day phrase-only retention policy in its empty state', async () => {
    const { container } = renderAppAt('/search-history')

    expect(await screen.findByRole('heading', { name: /^search history$/i })).toBeInTheDocument()
    expect(screen.getByText(/stored in this browser for seven days/i)).toBeInTheDocument()
    expect(screen.getByText(/transaction results are never saved here/i)).toBeInTheDocument()
    const emptyState = screen.getByRole('region', { name: /no searches yet/i })
    expect(within(emptyState).getByRole('link', { name: /search transactions/i })).toHaveAttribute(
      'href',
      '/dashboard',
    )
    await runAxeSmokeTest(container)
  })
})
