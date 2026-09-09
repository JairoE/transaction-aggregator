import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import { server } from '../test/server'
import { renderAppAt } from '../test/renderApp'
import { authenticatedSessionHandler } from '../test/handlers'
import { DASHBOARD_CARDS, recentSearchResponse, searchHandler } from '../test/dashboardFixtures'

function savedAggregatesHandler(aggregates: Record<string, unknown>[]) {
  return http.get('/api/saved-transaction-aggregates', () => HttpResponse.json({
    aggregates,
    evaluated_at: '2026-09-08T12:00:00Z',
    cache_as_of: '2026-09-08T11:59:00Z',
  }))
}

function savedAggregate(
  aggregateId: string,
  keyword: string,
  cardIndex: number,
  summary: {
    usd_match_count: number
    usd_pending_count: number
    purchases_cents: number
    refunds_cents: number
    net_total_cents: number
  },
) {
  return {
    aggregate_id: aggregateId,
    keyword,
    card: DASHBOARD_CARDS[cardIndex],
    summary,
  }
}

function cardRegion(index: number) {
  return screen.getByRole('region', {
    name: new RegExp(`ending in ${DASHBOARD_CARDS[index].mask}`, 'i'),
  })
}

describe('saved transaction aggregates on dashboard cards', () => {
  it('renders each recurring aggregate only on its target cards', async () => {
    server.use(
      authenticatedSessionHandler(),
      searchHandler(() => recentSearchResponse()),
      savedAggregatesHandler([
        savedAggregate('all-paze', 'Paze', 0, {
          usd_match_count: 10,
          usd_pending_count: 1,
          purchases_cents: 12_000,
          refunds_cents: 2_000,
          net_total_cents: 10_000,
        }),
        savedAggregate('refunds', 'Paze refunds', 0, {
          usd_match_count: 1,
          usd_pending_count: 0,
          purchases_cents: 0,
          refunds_cents: 10_000,
          net_total_cents: -10_000,
        }),
        savedAggregate('selected-dunkin', 'Dunkin', 1, {
          usd_match_count: 12,
          usd_pending_count: 0,
          purchases_cents: 12_108,
          refunds_cents: 0,
          net_total_cents: 12_108,
        }),
        savedAggregate('all-paze', 'Paze', 2, {
          usd_match_count: 0,
          usd_pending_count: 0,
          purchases_cents: 0,
          refunds_cents: 0,
          net_total_cents: 0,
        }),
      ]),
    )

    renderAppAt('/dashboard')

    const first = await screen.findByRole('region', {
      name: new RegExp(`ending in ${DASHBOARD_CARDS[0].mask}`, 'i'),
    })
    const paze = within(first).getByRole('article', { name: 'Paze saved aggregate' })
    expect(within(paze).getByText('$120.00')).toBeInTheDocument()
    expect(within(paze).getByText('$20.00')).toBeInTheDocument()
    expect(within(paze).getByText('$100.00')).toBeInTheDocument()
    expect(within(paze).getByText('10 USD matches · 1 pending · All history')).toBeInTheDocument()
    const refunds = within(first).getByRole('article', { name: 'Paze refunds saved aggregate' })
    expect(within(refunds).getByText('-$100.00')).toBeInTheDocument()

    const second = cardRegion(1)
    expect(within(second).getByRole('article', { name: 'Dunkin saved aggregate' })).toBeInTheDocument()
    expect(within(second).queryByRole('article', { name: 'Paze saved aggregate' })).not.toBeInTheDocument()

    const zeroResult = within(cardRegion(2)).getByRole('article', { name: 'Paze saved aggregate' })
    expect(within(zeroResult).getAllByText('$0.00')).toHaveLength(3)
    expect(within(zeroResult).getByText('0 USD matches · All history')).toBeInTheDocument()
    expect(within(cardRegion(3)).queryByText('Saved aggregates')).not.toBeInTheDocument()
  })

  it('places saved aggregates below the card art and before alerts and transactions', async () => {
    const card = DASHBOARD_CARDS[0]
    server.use(
      authenticatedSessionHandler(),
      searchHandler(() => recentSearchResponse()),
      savedAggregatesHandler([
        savedAggregate('all-paze', 'Paze', 0, {
          usd_match_count: 1,
          usd_pending_count: 0,
          purchases_cents: 1_999,
          refunds_cents: 0,
          net_total_cents: 1_999,
        }),
      ]),
      http.get('/api/transaction-limit-alerts', () => HttpResponse.json({
        alerts: [{
          rule_id: 'rule-1',
          card,
          keyword: 'Paze',
          metric: 'count',
          threshold: 1,
          total_threshold_cents: null,
          match_count: 1,
          pending_count: 0,
          match_total_cents: null,
          pending_total_cents: null,
          window: { type: 'all_time' },
        }],
        evaluated_at: '2026-09-08T12:00:00Z',
        as_of_date: '2026-09-08',
        cache_as_of: null,
      })),
    )

    renderAppAt('/dashboard')

    const region = await screen.findByRole('region', {
      name: new RegExp(`ending in ${card.mask}`, 'i'),
    })
    const cardArt = within(region).getByRole('img')
    const saved = within(region).getByRole('region', { name: 'Saved aggregates' })
    const alert = within(region).getByRole('alert')
    const transaction = within(region).getAllByRole('listitem')[0]
    expect(cardArt.compareDocumentPosition(saved) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(saved.compareDocumentPosition(alert) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(saved.compareDocumentPosition(transaction) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('keeps cards, transactions, and alerts usable when saved evaluation fails', async () => {
    const card = DASHBOARD_CARDS[0]
    server.use(
      authenticatedSessionHandler(),
      searchHandler(() => recentSearchResponse()),
      http.get('/api/saved-transaction-aggregates', () => HttpResponse.json(
        { code: 'INTERNAL_ERROR', message: 'Unavailable' },
        { status: 500 },
      )),
      http.get('/api/transaction-limit-alerts', () => HttpResponse.json({
        alerts: [{
          rule_id: 'rule-1',
          card,
          keyword: 'Paze',
          metric: 'count',
          threshold: 1,
          total_threshold_cents: null,
          match_count: 1,
          pending_count: 0,
          match_total_cents: null,
          pending_total_cents: null,
          window: { type: 'all_time' },
        }],
        evaluated_at: '2026-09-08T12:00:00Z',
        as_of_date: '2026-09-08',
        cache_as_of: null,
      })),
    )

    renderAppAt('/dashboard')

    const region = await screen.findByRole('region', {
      name: new RegExp(`ending in ${card.mask}`, 'i'),
    })
    expect(within(region).getByText(/capital one everyday purchase/i)).toBeInTheDocument()
    expect(within(region).getByRole('alert')).toHaveTextContent(/transactions match “Paze”/i)
    expect(screen.getByRole('status', { name: /saved transaction aggregates/i })).toHaveTextContent(
      /saved aggregates are temporarily unavailable/i,
    )
  })
})
