import { HttpResponse, delay, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
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
  name: 'Venture',
  official_name: 'Capital One Venture',
  mask: '4812',
  state: 'ready',
  last_successful_sync_at: '2026-08-22T12:00:00Z',
}

const createdRule = {
  id: 'rule-1',
  keyword: 'Paze',
  threshold: 10,
  card_scope: 'all_cards',
  card_ids: [],
  window: { type: 'all_time' },
  is_enabled: true,
  needs_card_selection: false,
  created_at: '2026-08-22T12:00:00Z',
  updated_at: '2026-08-22T12:00:00Z',
}

afterEach(() => vi.restoreAllMocks())

describe('transaction limitations page', () => {
  it('creates an informational all-time rule for every card', async () => {
    let body: unknown
    let rules: typeof createdRule[] = []
    server.use(
      authenticatedSessionHandler(),
      http.get('/api/transaction-limitations', () => HttpResponse.json({ rules, cards: [card] })),
      http.post('/api/transaction-limitations', async ({ request }) => {
        body = await request.json()
        rules = [createdRule]
        return HttpResponse.json(createdRule, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    const { container } = renderAppAt('/transaction-limitations')

    expect(await screen.findByText(/informational alerts only/i)).toBeInTheDocument()
    await user.type(await screen.findByLabelText(/keyword or phrase/i), 'Paze')
    await user.clear(screen.getByLabelText(/transaction threshold/i))
    await user.type(screen.getByLabelText(/transaction threshold/i), '10')
    await user.click(screen.getByRole('button', { name: /save rule/i }))

    expect(body).toEqual({
      keyword: 'Paze',
      threshold: 10,
      card_scope: 'all_cards',
      card_ids: [],
      window: { type: 'all_time' },
      is_enabled: true,
    })
    expect(await screen.findByRole('heading', { name: 'Paze' })).toBeInTheDocument()
    expect(screen.getAllByText(/all available history/i)).not.toHaveLength(0)
    await runAxeSmokeTest(container)
  })

  it('requires at least one card when selected-card scope is chosen', async () => {
    server.use(
      authenticatedSessionHandler(),
      http.get('/api/transaction-limitations', () => HttpResponse.json({ rules: [], cards: [card] })),
    )
    const user = userEvent.setup()
    renderAppAt('/transaction-limitations')

    await screen.findByLabelText(/keyword or phrase/i)
    await user.type(screen.getByLabelText(/keyword or phrase/i), 'Paze')
    await user.click(screen.getByRole('radio', { name: /selected cards/i }))
    await user.click(screen.getByRole('button', { name: /save rule/i }))

    expect(screen.getByRole('alert')).toHaveTextContent(/select at least one card/i)
  })

  it('marks a selected-card rule whose cards were disconnected', async () => {
    server.use(
      authenticatedSessionHandler(),
      http.get('/api/transaction-limitations', () => HttpResponse.json({
        rules: [{
          ...createdRule,
          card_scope: 'selected_cards',
          card_ids: [],
          needs_card_selection: true,
        }],
        cards: [card],
      })),
    )

    renderAppAt('/transaction-limitations')

    expect(await screen.findByText(/needs card selection/i)).toBeInTheDocument()
  })

  it('shows pending and failure states when disabling a rule', async () => {
    server.use(
      authenticatedSessionHandler(),
      http.get('/api/transaction-limitations', () => HttpResponse.json({
        rules: [createdRule],
        cards: [card],
      })),
      http.patch('/api/transaction-limitations/:ruleId', async () => {
        await delay(100)
        return HttpResponse.json({ code: 'INTERNAL_ERROR', message: 'Unavailable' }, { status: 500 })
      }),
    )
    const user = userEvent.setup()
    renderAppAt('/transaction-limitations')

    await user.click(await screen.findByRole('button', { name: 'Disable' }))

    expect(screen.getByRole('button', { name: 'Disabling…' })).toBeDisabled()
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not disable “Paze”/i)
  })

  it('shows pending and failure states when deleting a rule', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    server.use(
      authenticatedSessionHandler(),
      http.get('/api/transaction-limitations', () => HttpResponse.json({
        rules: [createdRule],
        cards: [card],
      })),
      http.delete('/api/transaction-limitations/:ruleId', async () => {
        await delay(100)
        return HttpResponse.json({ code: 'INTERNAL_ERROR', message: 'Unavailable' }, { status: 500 })
      }),
    )
    const user = userEvent.setup()
    renderAppAt('/transaction-limitations')

    await user.click(await screen.findByRole('button', { name: 'Delete' }))

    expect(screen.getByRole('button', { name: 'Deleting…' })).toBeDisabled()
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not delete “Paze”/i)
  })

  it('creates a rolling rule with a validated number of days', async () => {
    let body: unknown
    const rollingRule = {
      ...createdRule,
      id: 'rule-rolling',
      window: { type: 'rolling', days: 5 },
    }
    server.use(
      authenticatedSessionHandler(),
      http.get('/api/transaction-limitations', () => HttpResponse.json({ rules: [], cards: [card] })),
      http.post('/api/transaction-limitations', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(rollingRule, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderAppAt('/transaction-limitations')

    await user.type(await screen.findByLabelText(/keyword or phrase/i), 'Dunkin’ Donuts')
    await user.clear(screen.getByLabelText(/transaction threshold/i))
    await user.type(screen.getByLabelText(/transaction threshold/i), '5')
    await user.click(screen.getByRole('radio', { name: /last n days/i }))
    await user.clear(screen.getByLabelText(/number of days/i))
    await user.type(screen.getByLabelText(/number of days/i), '5')
    await user.click(screen.getByRole('button', { name: /save rule/i }))

    expect(body).toEqual({
      keyword: 'Dunkin’ Donuts',
      threshold: 5,
      card_scope: 'all_cards',
      card_ids: [],
      window: { type: 'rolling', days: 5 },
      is_enabled: true,
    })
  })

  it('validates and creates an inclusive fixed date rule', async () => {
    let body: unknown
    const fixedRule = {
      ...createdRule,
      id: 'rule-fixed',
      window: { type: 'fixed', start_date: '2026-07-01', end_date: '2026-07-31' },
    }
    server.use(
      authenticatedSessionHandler(),
      http.get('/api/transaction-limitations', () => HttpResponse.json({ rules: [], cards: [card] })),
      http.post('/api/transaction-limitations', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(fixedRule, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderAppAt('/transaction-limitations')

    await user.type(await screen.findByLabelText(/keyword or phrase/i), 'Paze')
    await user.click(screen.getByRole('radio', { name: /fixed date range/i }))
    await user.type(screen.getByLabelText(/start date/i), '2026-07-31')
    await user.type(screen.getByLabelText(/end date/i), '2026-07-01')
    await user.click(screen.getByRole('button', { name: /save rule/i }))
    expect(screen.getByRole('alert')).toHaveTextContent(/end date must be on or after/i)

    await user.clear(screen.getByLabelText(/start date/i))
    await user.type(screen.getByLabelText(/start date/i), '2026-07-01')
    await user.clear(screen.getByLabelText(/end date/i))
    await user.type(screen.getByLabelText(/end date/i), '2026-07-31')
    await user.click(screen.getByRole('button', { name: /save rule/i }))

    expect(body).toMatchObject({
      keyword: 'Paze',
      window: { type: 'fixed', start_date: '2026-07-01', end_date: '2026-07-31' },
    })
  })
})
