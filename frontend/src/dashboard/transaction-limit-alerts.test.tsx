import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import { server } from '../test/server'
import { renderAppAt } from '../test/renderApp'
import { authenticatedSessionHandler } from '../test/handlers'
import { DASHBOARD_CARDS, recentSearchResponse, searchHandler } from '../test/dashboardFixtures'

function alertsHandler(response: Record<string, unknown>, status = 200) {
  return http.get('/api/transaction-limit-alerts', () => HttpResponse.json(response, { status }))
}

describe('dashboard transaction-limit alerts', () => {
  it('shows a qualifying alert only on its card and reports pending matches', async () => {
    const card = DASHBOARD_CARDS[0]
    server.use(
      authenticatedSessionHandler(),
      searchHandler(() => recentSearchResponse()),
      alertsHandler({
        alerts: [{
          rule_id: 'rule-1',
          card,
          keyword: 'Paze',
          threshold: 10,
          match_count: 12,
          pending_count: 2,
          window: {
            type: 'all_time',
            days: null,
            start_date: null,
            end_date: null,
            effective_start_date: null,
            effective_end_date: null,
          },
        }],
        evaluated_at: '2026-08-22T12:00:00Z',
        as_of_date: '2026-08-22',
        cache_as_of: '2026-08-22T11:59:00Z',
      }),
    )

    renderAppAt('/dashboard')

    const qualifyingCard = await screen.findByRole('region', {
      name: new RegExp(`ending in ${card.mask}`, 'i'),
    })
    const alert = await within(qualifyingCard).findByRole('alert')
    expect(alert).toHaveTextContent(/12 transactions match “Paze”/i)
    expect(alert).toHaveTextContent(/threshold: 10/i)
    expect(alert).toHaveTextContent(/2 pending/i)
    expect(alert).toHaveTextContent(/all available history/i)

    const otherCard = screen.getByRole('region', {
      name: new RegExp(`ending in ${DASHBOARD_CARDS[1].mask}`, 'i'),
    })
    expect(within(otherCard).queryByRole('alert')).not.toBeInTheDocument()
  })

  it('keeps cards usable when alert evaluation fails', async () => {
    server.use(
      authenticatedSessionHandler(),
      searchHandler(() => recentSearchResponse()),
      alertsHandler({ code: 'INTERNAL_ERROR', message: 'Unavailable' }, 500),
    )

    renderAppAt('/dashboard')

    expect(await screen.findByRole('heading', { name: /your credit cards/i })).toBeInTheDocument()
    expect(screen.getAllByRole('region', { name: /card ending in/i })).toHaveLength(8)
    expect(screen.getByRole('status', { name: /transaction limit alerts/i })).toHaveTextContent(
      /alerts are temporarily unavailable/i,
    )
  })
})
