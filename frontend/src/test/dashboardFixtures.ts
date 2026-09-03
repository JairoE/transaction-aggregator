import { http, HttpResponse } from 'msw'
import type { components } from '../api/generated'

type CardResponse = components['schemas']['CardResponse']
type TransactionMatch = components['schemas']['TransactionMatch']
type CardTransactionGroup = components['schemas']['CardTransactionGroup']
type GroupedSearchResponse = components['schemas']['GroupedSearchResponse']
type AllTransactionsResponse = components['schemas']['AllTransactionsResponse']

const BANKS: { bank: CardResponse['bank']; displayName: string }[] = [
  { bank: 'capital-one', displayName: 'Capital One' },
  { bank: 'chase', displayName: 'Chase' },
  { bank: 'citi', displayName: 'Citi' },
  { bank: 'wells-fargo', displayName: 'Wells Fargo' },
]

/** Masks in fixed bank order, two per bank, exactly as specified for Task 8. */
const MASKS = ['4812', '9064', '1187', '2041', '7730', '3628', '5509', '6144']

/** Eight cards: two each for Capital One, Chase, Citi, and Wells Fargo. */
export const DASHBOARD_CARDS: CardResponse[] = BANKS.flatMap((bankMeta, bankIndex) =>
  [0, 1].map((cardIndex) => {
    const overallIndex = bankIndex * 2 + cardIndex
    const card: CardResponse = {
      id: `card-${bankMeta.bank}-${cardIndex + 1}`,
      connection_id: `conn-${bankMeta.bank}`,
      bank: bankMeta.bank,
      bank_display_name: bankMeta.displayName,
      name: `${bankMeta.displayName} ${cardIndex === 0 ? 'Rewards' : 'Cash'} Card`,
      official_name: null,
      mask: MASKS[overallIndex],
      state: 'ready',
      last_successful_sync_at: '2026-08-19T12:00:00Z',
    }
    return card
  }),
)

/** 10 total "Paze" matches distributed 2/1/1/2/1/1/1/1 across the 8 cards
 * above, in the fixed card order (Capital One ×2, Chase ×2, Citi ×2, Wells
 * Fargo ×2) — exactly as specified for Task 8. */
const PAZE_MATCH_COUNTS = [2, 1, 1, 2, 1, 1, 1, 1]

/** The first card's total (2) is only partly loaded up front (1 of 2), so
 * the "load more" flow has something real to fetch within the Paze fixture. */
const FIRST_CARD_LOAD_MORE_CURSOR = 'cursor-co1-more'

function makeTransaction(
  overrides: Partial<TransactionMatch> & { id: string; card_id: string },
): TransactionMatch {
  return {
    merchant_name: 'Paze Checkout',
    description: 'PAZE CHECKOUT PURCHASE',
    original_description: 'POS PURCHASE PAZE CHECKOUT',
    category: 'Shopping',
    amount_cents: 1999,
    currency_code: 'USD',
    authorized_date: '2026-08-17',
    posted_date: '2026-08-18',
    pending: false,
    ...overrides,
  }
}

export function pazeSearchResponse(): GroupedSearchResponse {
  const groups: CardTransactionGroup[] = DASHBOARD_CARDS.map((card, index) => {
    const matchCount = PAZE_MATCH_COUNTS[index]
    const isFirstCard = index === 0
    const loadedCount = isFirstCard ? 1 : matchCount
    const transactions = Array.from({ length: loadedCount }, (_, txIndex) =>
      makeTransaction({
        id: `${card.id}-paze-${txIndex + 1}`,
        card_id: card.id,
        merchant_name: `Paze Checkout ${txIndex + 1}`,
      }),
    )
    return {
      card,
      transactions,
      match_count: matchCount,
      next_cursor: isFirstCard ? FIRST_CARD_LOAD_MORE_CURSOR : null,
      has_more: isFirstCard,
    }
  })
  return {
    query: 'Paze',
    total_matches: PAZE_MATCH_COUNTS.reduce((sum, count) => sum + count, 0),
    card_count: DASHBOARD_CARDS.length,
    cache_as_of: '2026-08-19T12:29:30Z',
    groups,
  }
}

/** The second page for the one card whose Paze results are split (see above). */
export function pazeFirstCardNextPage(): CardTransactionGroup {
  const card = DASHBOARD_CARDS[0]
  return {
    card,
    transactions: [
      makeTransaction({
        id: `${card.id}-paze-2`,
        card_id: card.id,
        merchant_name: 'Paze Checkout 2',
        amount_cents: 2500,
        authorized_date: '2026-08-16',
        posted_date: '2026-08-16',
      }),
    ],
    match_count: 2,
    next_cursor: null,
    has_more: false,
  }
}

export function recentSearchResponse(): GroupedSearchResponse {
  const groups: CardTransactionGroup[] = DASHBOARD_CARDS.map((card) => ({
    card,
    transactions: [
      makeTransaction({
        id: `${card.id}-recent-1`,
        card_id: card.id,
        merchant_name: `${card.bank_display_name} Everyday Purchase`,
        description: 'EVERYDAY PURCHASE',
        original_description: null,
        category: 'General',
      }),
    ],
    match_count: 1,
    next_cursor: null,
    has_more: false,
  }))
  return {
    query: '',
    total_matches: DASHBOARD_CARDS.length,
    card_count: DASHBOARD_CARDS.length,
    cache_as_of: '2026-08-19T12:29:30Z',
    groups,
  }
}

/** A globally ordered, cross-bank aggregate page for the All transactions view. */
export function recentAllTransactionsResponse(): AllTransactionsResponse {
  const rows = [
    {
      transaction: makeTransaction({
        id: 'aggregate-capital-one-newest',
        card_id: DASHBOARD_CARDS[0].id,
        merchant_name: 'Capital One Newest Purchase',
        description: 'CAPITAL ONE NEWEST PURCHASE',
        original_description: 'POS CAPITAL ONE NEWEST PURCHASE',
        amount_cents: 4812,
        posted_date: '2026-08-21',
        pending: false,
      }),
      card: DASHBOARD_CARDS[0],
    },
    {
      transaction: makeTransaction({
        id: 'aggregate-chase-pending',
        card_id: DASHBOARD_CARDS[2].id,
        merchant_name: 'Chase Pending Purchase',
        description: 'CHASE PENDING PURCHASE',
        original_description: null,
        amount_cents: -1250,
        posted_date: '2026-08-20',
        pending: true,
      }),
      card: DASHBOARD_CARDS[2],
    },
    {
      transaction: makeTransaction({
        id: 'aggregate-citi-authorized',
        card_id: DASHBOARD_CARDS[4].id,
        merchant_name: 'Citi Authorized Purchase',
        description: 'CITI AUTHORIZED PURCHASE',
        original_description: null,
        amount_cents: 2400,
        authorized_date: '2026-08-19',
        posted_date: null,
      }),
      card: DASHBOARD_CARDS[4],
    },
    {
      transaction: makeTransaction({
        id: 'aggregate-wells-unknown-date',
        card_id: DASHBOARD_CARDS[6].id,
        merchant_name: 'Wells Fargo Unknown Date',
        description: 'WELLS FARGO UNKNOWN DATE',
        original_description: null,
        amount_cents: 5100,
        authorized_date: null,
        posted_date: null,
      }),
      card: DASHBOARD_CARDS[6],
    },
  ]

  return {
    query: '',
    total_matches: rows.length,
    card_count: DASHBOARD_CARDS.length,
    bank_count: 4,
    rows,
    next_cursor: 'aggregate-recent-next',
    has_more: true,
    cache_as_of: '2026-08-19T12:29:30Z',
  }
}

export function pazeAllTransactionsResponse(): AllTransactionsResponse {
  const base = recentAllTransactionsResponse()
  return {
    ...base,
    query: 'Paze',
    total_matches: 2,
    rows: base.rows.slice(0, 2).map((row, index) => ({
      ...row,
      transaction: {
        ...row.transaction,
        id: `aggregate-paze-${index + 1}`,
        merchant_name: `Paze aggregate ${index + 1}`,
        description: `PAZE AGGREGATE ${index + 1}`,
      },
    })),
    next_cursor: null,
    has_more: false,
  }
}

export function aggregateNextPage(): AllTransactionsResponse {
  const base = recentAllTransactionsResponse()
  return {
    ...base,
    rows: [{
      transaction: makeTransaction({
        id: 'aggregate-wells-next-page',
        card_id: DASHBOARD_CARDS[7].id,
        merchant_name: 'Wells Fargo Later Purchase',
        description: 'WELLS FARGO LATER PURCHASE',
        original_description: null,
        amount_cents: 3200,
        posted_date: '2026-08-18',
      }),
      card: DASHBOARD_CARDS[7],
    }],
    next_cursor: null,
    has_more: false,
  }
}

export function emptyAllTransactionsResponse(query = ''): AllTransactionsResponse {
  return {
    query,
    total_matches: 0,
    card_count: DASHBOARD_CARDS.length,
    bank_count: 4,
    rows: [],
    next_cursor: null,
    has_more: false,
    cache_as_of: '2026-08-19T12:29:30Z',
  }
}

/** Every card visible, but all except the first have zero matches — used to
 * exercise the zero-match rendering path without contradicting the exact
 * "10 matches ... across 8 cards" Paze distribution above. */
export function zeroMatchSearchResponse(): GroupedSearchResponse {
  const groups: CardTransactionGroup[] = DASHBOARD_CARDS.map((card, index) => {
    const isOnlyMatch = index === 0
    return {
      card,
      transactions: isOnlyMatch
        ? [makeTransaction({ id: `${card.id}-rare-1`, card_id: card.id, merchant_name: 'Rare Merchant' })]
        : [],
      match_count: isOnlyMatch ? 1 : 0,
      next_cursor: null,
      has_more: false,
    }
  })
  return {
    query: 'raremerchant',
    total_matches: 1,
    card_count: DASHBOARD_CARDS.length,
    cache_as_of: '2026-08-19T12:29:30Z',
    groups,
  }
}

export function searchHandler(
  responder: (query: string) => GroupedSearchResponse | Promise<GroupedSearchResponse>,
  onRequest?: (query: string) => void,
) {
  return http.get('/api/transactions/search', async ({ request }) => {
    const url = new URL(request.url)
    const query = (url.searchParams.get('q') ?? '').trim()
    onRequest?.(query)
    const body = await responder(query)
    return HttpResponse.json(body)
  })
}

export function cardTransactionsHandler(
  responder: (cardId: string, cursor: string | null) => CardTransactionGroup,
) {
  return http.get('/api/cards/:cardId/transactions', ({ request, params }) => {
    const url = new URL(request.url)
    const cursor = url.searchParams.get('cursor')
    const cardId = String(params.cardId)
    return HttpResponse.json(responder(cardId, cursor))
  })
}

export function allTransactionsHandler(
  responder: (query: string, cursor: string | null) => AllTransactionsResponse | Promise<AllTransactionsResponse>,
  onRequest?: (query: string, cursor: string | null) => void,
) {
  return http.get('/api/transactions', async ({ request }) => {
    const url = new URL(request.url)
    const query = (url.searchParams.get('q') ?? '').trim()
    const cursor = url.searchParams.get('cursor')
    onRequest?.(query, cursor)
    return HttpResponse.json(await responder(query, cursor))
  })
}
