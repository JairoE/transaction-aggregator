import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server } from '../test/server'
import { renderAppAt } from '../test/renderApp'
import { runAxeSmokeTest } from '../test/axe'
import { authenticatedSessionHandler } from '../test/handlers'
import {
  DASHBOARD_CARDS,
  cardTransactionsHandler,
  pazeFirstCardNextPage,
  pazeSearchResponse,
  recentSearchResponse,
  searchHandler,
  zeroMatchSearchResponse,
} from '../test/dashboardFixtures'
import { highlightText } from './highlight'

async function renderDashboard() {
  const utils = renderAppAt('/dashboard')
  await screen.findByRole('heading', { name: /your credit cards/i })
  return utils
}

function regionFor(mask: string) {
  return screen.getByRole('region', { name: new RegExp(`ending in ${mask}`, 'i') })
}

describe('dashboard card grid', () => {
  beforeEach(() => {
    server.use(authenticatedSessionHandler())
  })

  it('renders all eight cards under exactly one search input on initial load', async () => {
    server.use(searchHandler(() => recentSearchResponse()))
    await renderDashboard()

    expect(screen.getAllByRole('searchbox', { name: /search transactions/i })).toHaveLength(1)
    for (const card of DASHBOARD_CARDS) {
      expect(regionFor(card.mask ?? '')).toBeInTheDocument()
    }
  })

  it('renders a bank-specific outlined preview with the visible identity of every card', async () => {
    server.use(searchHandler(() => recentSearchResponse()))
    await renderDashboard()

    for (const card of DASHBOARD_CARDS) {
      const region = regionFor(card.mask ?? '')
      const preview = within(region).getByRole('img', {
        name: `${card.name}, issued by ${card.bank_display_name}, card ending in ${card.mask}`,
      })

      expect(preview).toHaveClass(`credit-card-outline--${card.bank}`)
      expect(preview).toHaveTextContent(card.bank_display_name)
      expect(preview).toHaveTextContent(card.name)
      expect(preview).toHaveTextContent(`•••• ${card.mask}`)
    }
  })

  it('gives every card a fixed-height, independently scrollable transaction region', async () => {
    server.use(searchHandler(() => recentSearchResponse()))
    await renderDashboard()

    for (const card of DASHBOARD_CARDS) {
      const region = regionFor(card.mask ?? '')
      const viewport = region.querySelector<HTMLElement>('.transaction-list')
      expect(viewport).not.toBeNull()
      expect(viewport?.style.height).toBe('260px')
      expect(viewport?.style.overflowY).toBe('auto')
    }
  })

  it('keeps all eight groups visible, showing 0 matches for cards with no hits', async () => {
    server.use(searchHandler((query) => (query ? zeroMatchSearchResponse() : recentSearchResponse())))
    const user = userEvent.setup()
    await renderDashboard()

    await user.type(screen.getByRole('searchbox', { name: /search transactions/i }), 'raremerchant{Enter}')
    await screen.findByText(/1 match for/i)

    for (const card of DASHBOARD_CARDS) {
      expect(regionFor(card.mask ?? '')).toBeInTheDocument()
    }
    expect(screen.getAllByText('0 matches')).toHaveLength(7)
    expect(screen.getAllByText(/no matching transactions on this card/i)).toHaveLength(7)
  })

  it('loading more on one card only changes that card, leaving the others untouched', async () => {
    server.use(
      searchHandler((query) => (query ? pazeSearchResponse() : recentSearchResponse())),
      cardTransactionsHandler((cardId, cursor) => {
        if (cardId === DASHBOARD_CARDS[0].id && cursor === 'cursor-co1-more') {
          return pazeFirstCardNextPage()
        }
        throw new Error(`Unexpected card-transactions request: ${cardId} / ${String(cursor)}`)
      }),
    )
    const user = userEvent.setup()
    await renderDashboard()
    await user.type(screen.getByRole('searchbox', { name: /search transactions/i }), 'Paze{Enter}')
    await screen.findByText(/10 matches for/i)

    const untouchedCard = DASHBOARD_CARDS[3]
    const untouchedRegion = regionFor(untouchedCard.mask ?? '')
    const untouchedRowsBefore = within(untouchedRegion)
      .getAllByRole('listitem')
      .map((row) => row.textContent)

    const targetCard = DASHBOARD_CARDS[0]
    const targetRegion = regionFor(targetCard.mask ?? '')
    await user.click(within(targetRegion).getByRole('button', { name: /load more/i }))

    await expect
      .poll(() => within(targetRegion).getAllByRole('listitem'))
      .toHaveLength(2)
    const rows = within(targetRegion).getAllByRole('listitem')
    expect(rows[1]).toHaveTextContent(/paze checkout 2/i)
    expect(
      within(targetRegion).queryByRole('button', { name: /load more/i }),
    ).not.toBeInTheDocument()

    const untouchedRowsAfter = within(untouchedRegion)
      .getAllByRole('listitem')
      .map((row) => row.textContent)
    expect(untouchedRowsAfter).toEqual(untouchedRowsBefore)
  })

  it('has no detectable accessibility violations on the dashboard view', async () => {
    server.use(searchHandler(() => recentSearchResponse()))
    const { container } = await renderDashboard()

    await runAxeSmokeTest(container)
  })

  it('exposes date, merchant/description, pending state, and signed amount to assistive technology', async () => {
    server.use(searchHandler(() => recentSearchResponse()))
    await renderDashboard()

    const card = DASHBOARD_CARDS[0]
    const region = regionFor(card.mask ?? '')
    const row = within(region).getAllByRole('listitem')[0]

    const time = row.querySelector('time')
    expect(time).not.toBeNull()
    expect(time?.getAttribute('dateTime')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(row.textContent).toMatch(/everyday purchase/i)
    // A purchase reads as a plain amount, like a statement; only the
    // accessible name states which direction the money moved.
    expect(row.textContent).toMatch(/\$[\d.,]+/)
    const amount = within(row).getByLabelText(/charged|credited/i)
    expect(amount).toHaveTextContent(/^\$[\d.,]+$/)
  })

  it('marks pending transactions with a text marker rather than color alone', async () => {
    server.use(
      searchHandler(() => {
        const response = recentSearchResponse()
        response.groups[0].transactions[0].pending = true
        return response
      }),
    )
    await renderDashboard()

    const card = DASHBOARD_CARDS[0]
    const region = regionFor(card.mask ?? '')
    expect(within(region).getByText('Pending')).toBeInTheDocument()
  })

  it('offers a transaction-level shortcut that prefills an alert for its card and merchant', async () => {
    server.use(searchHandler(() => recentSearchResponse()))
    await renderDashboard()

    const card = DASHBOARD_CARDS[0]
    const region = regionFor(card.mask ?? '')
    const link = within(region).getByRole('link', {
      name: `Set alert for ${card.bank_display_name} Everyday Purchase`,
    })

    expect(link).toHaveAttribute(
      'href',
      `/transaction-limitations?keyword=${encodeURIComponent(`${card.bank_display_name} Everyday Purchase`)}&card_id=${encodeURIComponent(card.id)}`,
    )
  })
})

describe('highlightText', () => {
  it('highlights a literal substring case-insensitively without using regex semantics', () => {
    expect(() => highlightText('Pay a*b now', 'a*b')).not.toThrow()

    const { container } = render(<>{highlightText('Pay A*B now', 'a*b')}</>)
    expect(container.textContent).toBe('Pay A*B now')
    expect(container.querySelector('mark')).toHaveTextContent('A*B')
  })

  it('never injects markup for HTML-looking terms', () => {
    const nodes = highlightText('Contains <b>bold</b> text', '<b>')
    expect(() => render(<>{nodes}</>)).not.toThrow()

    const { container } = render(<>{nodes}</>)
    expect(container.textContent).toBe('Contains <b>bold</b> text')
    expect(container.querySelector('b')).toBeNull()
  })
})
