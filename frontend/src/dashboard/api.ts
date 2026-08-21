/**
 * Typed fetch helpers for the two cached, Plaid-free read endpoints the
 * dashboard consumes: the grouped multi-card search and the single-card
 * continuation page. Both go through the shared `apiClient` so session
 * cookies/CSRF handling stay centralized (see `../api/client.ts`).
 */
import { apiClient } from '../api/client'
import type { components } from '../api/generated'

export type GroupedSearchResponse = components['schemas']['GroupedSearchResponse']
export type CardTransactionGroup = components['schemas']['CardTransactionGroup']
export type TransactionMatch = components['schemas']['TransactionMatch']
export type CardResponse = components['schemas']['CardResponse']

/** Matches the backend's own default (`app/services/search_service.py`). */
export const DEFAULT_PER_CARD_LIMIT = 25
/** The backend rejects `per_card_limit`/`limit` above this with a 422. */
export const MAX_PER_CARD_LIMIT = 50

function clampLimit(limit: number): number {
  return Math.min(Math.max(1, Math.trunc(limit)), MAX_PER_CARD_LIMIT)
}

// Note: these deliberately do NOT forward TanStack Query's queryFn
// `AbortSignal` into `fetch()`. "Abort the previous request when the key
// changes" is satisfied at the state level regardless — each submitted query
// gets its own query-cache entry (`['transactions', 'search', submittedQuery]`),
// so a slow, still-in-flight request for an old key can only ever populate
// that old entry's cache and can never overwrite what the UI reads for the
// current key. (Wiring the signal through is also unsafe in this project's
// jsdom test environment: Node's native `fetch` and jsdom's `AbortController`
// come from different realms, so `fetch` rejects a jsdom-issued signal with
// "Expected signal to be an instance of AbortSignal".)

export function fetchTransactionSearch(query: string): Promise<GroupedSearchResponse> {
  const params = new URLSearchParams()
  if (query) {
    params.set('q', query)
  }
  params.set('per_card_limit', String(clampLimit(DEFAULT_PER_CARD_LIMIT)))
  return apiClient.request<GroupedSearchResponse>(`/api/transactions/search?${params.toString()}`)
}

export function fetchCardTransactions(
  cardId: string,
  query: string,
  cursor: string | null,
  limit: number = DEFAULT_PER_CARD_LIMIT,
): Promise<CardTransactionGroup> {
  const params = new URLSearchParams()
  if (query) {
    params.set('q', query)
  }
  if (cursor) {
    params.set('cursor', cursor)
  }
  params.set('limit', String(clampLimit(limit)))
  return apiClient.request<CardTransactionGroup>(
    `/api/cards/${encodeURIComponent(cardId)}/transactions?${params.toString()}`,
  )
}
