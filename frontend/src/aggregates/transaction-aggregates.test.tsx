import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server } from '../test/server'
import { renderAppAt } from '../test/renderApp'
import { runAxeSmokeTest } from '../test/axe'
import { authenticatedSessionHandler } from '../test/handlers'

const card = {
  id: 'card-1',
  connection_id: 'connection-1',
  bank: 'capital-one',
  bank_display_name: 'Capital One',
  name: 'Savor',
  official_name: 'Capital One Savor',
  mask: '5663',
  state: 'ready',
  last_successful_sync_at: '2026-09-08T12:00:00Z',
}

const aggregate = {
  id: 'aggregate-1',
  keyword: 'Paze',
  card_scope: 'selected_cards',
  card_ids: ['card-1'],
  created_at: '2026-09-08T12:00:00Z',
  updated_at: '2026-09-08T12:00:00Z',
}

function limitationsHandler() {
  return http.get('/api/transaction-limitations', () => HttpResponse.json({
    rules: [],
    cards: [card],
  }))
}

afterEach(() => vi.restoreAllMocks())

describe('saved aggregate management', () => {
  it('creates a selected-card aggregate with only aggregate fields', async () => {
    let body: unknown
    let aggregates: typeof aggregate[] = []
    server.use(
      authenticatedSessionHandler(),
      limitationsHandler(),
      http.get('/api/transaction-aggregates', () => HttpResponse.json({ aggregates, cards: [card] })),
      http.post('/api/transaction-aggregates', async ({ request }) => {
        body = await request.json()
        aggregates = [aggregate]
        return HttpResponse.json(aggregate, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    const { container } = renderAppAt('/transaction-limitations')
    const section = await screen.findByRole('region', { name: 'Saved aggregates' })

    await user.type(await within(section).findByLabelText(/aggregate search term/i), 'Paze')
    await user.click(within(section).getByRole('radio', { name: 'Specific cards' }))
    await user.click(within(section).getByRole('checkbox', { name: /capital one savor ending in 5663/i }))
    await user.click(within(section).getByRole('button', { name: /save aggregate/i }))

    expect(body).toEqual({
      keyword: 'Paze',
      card_scope: 'selected_cards',
      card_ids: ['card-1'],
    })
    expect(await within(section).findByRole('heading', { name: 'Paze' })).toBeInTheDocument()
    expect(within(section).queryByLabelText(/threshold|date window|alert type/i)).not.toBeInTheDocument()
    await runAxeSmokeTest(container)
  })

  it('requires a card for selected-card scope', async () => {
    server.use(
      authenticatedSessionHandler(),
      limitationsHandler(),
      http.get('/api/transaction-aggregates', () => HttpResponse.json({ aggregates: [], cards: [card] })),
    )
    const user = userEvent.setup()
    renderAppAt('/transaction-limitations')
    const section = await screen.findByRole('region', { name: 'Saved aggregates' })

    await user.type(await within(section).findByLabelText(/aggregate search term/i), 'Paze')
    await user.click(within(section).getByRole('radio', { name: 'Specific cards' }))
    await user.click(within(section).getByRole('button', { name: /save aggregate/i }))

    const error = within(section).getByRole('alert')
    expect(error).toHaveTextContent(/select at least one card/i)
    expect(within(section).getByRole('group', { name: 'Aggregate cards' }))
      .toHaveAttribute('aria-describedby', error.id)
  })

  it('prefills and updates an existing aggregate', async () => {
    let body: unknown
    server.use(
      authenticatedSessionHandler(),
      limitationsHandler(),
      http.get('/api/transaction-aggregates', () => HttpResponse.json({ aggregates: [aggregate], cards: [card] })),
      http.patch('/api/transaction-aggregates/:aggregateId', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({
          ...aggregate,
          keyword: 'Dunkin',
          card_scope: 'all_cards',
          card_ids: [],
        })
      }),
    )
    const user = userEvent.setup()
    renderAppAt('/transaction-limitations')
    const section = await screen.findByRole('region', { name: 'Saved aggregates' })

    await user.click(await within(section).findByRole('button', { name: 'Edit Paze' }))
    const keyword = within(section).getByLabelText(/aggregate search term/i)
    expect(keyword).toHaveValue('Paze')
    expect(within(section).getByRole('checkbox', { name: /capital one savor ending in 5663/i })).toBeChecked()
    await user.clear(keyword)
    await user.type(keyword, 'Dunkin')
    await user.click(within(section).getByRole('radio', { name: /every card/i }))
    await user.click(within(section).getByRole('button', { name: /update aggregate/i }))

    expect(body).toEqual({
      keyword: 'Dunkin',
      card_scope: 'all_cards',
      card_ids: [],
    })
  })

  it('confirms and deletes an aggregate', async () => {
    let deleted = false
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    server.use(
      authenticatedSessionHandler(),
      limitationsHandler(),
      http.get('/api/transaction-aggregates', () => HttpResponse.json({
        aggregates: deleted ? [] : [aggregate],
        cards: [card],
      })),
      http.delete('/api/transaction-aggregates/:aggregateId', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderAppAt('/transaction-limitations')
    const section = await screen.findByRole('region', { name: 'Saved aggregates' })

    await user.click(await within(section).findByRole('button', { name: 'Delete Paze' }))

    expect(window.confirm).toHaveBeenCalledWith('Delete the saved aggregate for “Paze”?')
    expect(await within(section).findByText(/no saved aggregates yet/i)).toBeInTheDocument()
  })
})
