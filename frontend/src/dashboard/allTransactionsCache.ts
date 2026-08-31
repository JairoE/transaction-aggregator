import type { AllTransactionsResponse, CardResponse, TransactionMatch } from './api'

const STORAGE_PREFIX = 'transaction-aggregator:all-transactions:v1:'
const CACHE_VERSION = 1
/** Keep aggregate results for the same 12 hours as dashboard search results. */
const TTL_MS = 12 * 60 * 60 * 1000

interface PersistedAllTransactionsEntry {
  version: number
  ownerId: string
  queryKey: string
  cachedAt: number
  data: AllTransactionsResponse
}

export interface PersistedAllTransactionsResult {
  data: AllTransactionsResponse
  cachedAt: number
}

type UnknownRecord = Record<string, unknown>

const BANKS = new Set(['capital-one', 'chase', 'citi', 'wells-fargo'])
const LAST_FOUR_MASK = /^\d{4}$/
const PAN_LIKE_SEQUENCE = /(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)/

function normalizeQuery(query: string): string {
  return query.trim().toLocaleLowerCase()
}

function storageKey(ownerId: string, queryKey: string): string {
  return `${STORAGE_PREFIX}${encodeURIComponent(ownerId)}:${encodeURIComponent(queryKey)}`
}

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStringOrNull(value: unknown): value is string | null {
  return typeof value === 'string' || value === null
}

function isSafeDisplayText(value: unknown): value is string | null {
  return isStringOrNull(value) && (value === null || !PAN_LIKE_SEQUENCE.test(value))
}

function isLastFourMask(value: unknown): value is string | null {
  return value === null || (typeof value === 'string' && LAST_FOUR_MASK.test(value))
}

function isCardResponse(value: unknown): value is CardResponse {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.connection_id === 'string' &&
    typeof value.bank === 'string' &&
    BANKS.has(value.bank) &&
    typeof value.bank_display_name === 'string' &&
    typeof value.name === 'string' &&
    isStringOrNull(value.official_name) &&
    isLastFourMask(value.mask) &&
    typeof value.state === 'string' &&
    (value.last_successful_sync_at === undefined || isStringOrNull(value.last_successful_sync_at))
  )
}

function isTransactionMatch(value: unknown): value is TransactionMatch {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.card_id === 'string' &&
    isSafeDisplayText(value.merchant_name) &&
    typeof value.description === 'string' &&
    isSafeDisplayText(value.description) &&
    isSafeDisplayText(value.original_description) &&
    isStringOrNull(value.category) &&
    typeof value.amount_cents === 'number' &&
    typeof value.currency_code === 'string' &&
    isStringOrNull(value.authorized_date) &&
    isStringOrNull(value.posted_date) &&
    typeof value.pending === 'boolean'
  )
}

function sanitizeCard(value: CardResponse): CardResponse {
  return {
    id: value.id,
    connection_id: value.connection_id,
    bank: value.bank,
    bank_display_name: value.bank_display_name,
    name: value.name,
    official_name: value.official_name,
    mask: value.mask,
    state: value.state,
    ...(value.last_successful_sync_at === undefined
      ? {}
      : { last_successful_sync_at: value.last_successful_sync_at }),
  }
}

function sanitizeTransaction(value: TransactionMatch): TransactionMatch {
  return {
    id: value.id,
    card_id: value.card_id,
    merchant_name: value.merchant_name,
    description: value.description,
    original_description: value.original_description,
    category: value.category,
    amount_cents: value.amount_cents,
    currency_code: value.currency_code,
    authorized_date: value.authorized_date,
    posted_date: value.posted_date,
    pending: value.pending,
  }
}

function sanitizeAllTransactionsResponse(value: unknown): AllTransactionsResponse | null {
  if (
    !isRecord(value) ||
    typeof value.query !== 'string' ||
    typeof value.total_matches !== 'number' ||
    typeof value.card_count !== 'number' ||
    typeof value.bank_count !== 'number' ||
    !Array.isArray(value.rows) ||
    !isStringOrNull(value.next_cursor) ||
    typeof value.has_more !== 'boolean' ||
    !isStringOrNull(value.cache_as_of)
  ) {
    return null
  }

  const rows = []
  for (const row of value.rows) {
    if (!isRecord(row) || !isTransactionMatch(row.transaction) || !isCardResponse(row.card)) {
      return null
    }
    rows.push({ transaction: sanitizeTransaction(row.transaction), card: sanitizeCard(row.card) })
  }

  return {
    query: value.query,
    total_matches: value.total_matches,
    card_count: value.card_count,
    bank_count: value.bank_count,
    rows,
    next_cursor: value.next_cursor,
    has_more: value.has_more,
    cache_as_of: value.cache_as_of,
  }
}

function parseEntry(value: unknown, ownerId: string, queryKey: string, now: number): PersistedAllTransactionsResult | null {
  if (
    !isRecord(value) ||
    value.version !== CACHE_VERSION ||
    value.ownerId !== ownerId ||
    value.queryKey !== queryKey ||
    typeof value.cachedAt !== 'number' ||
    !Number.isFinite(value.cachedAt) ||
    value.cachedAt > now ||
    now - value.cachedAt > TTL_MS
  ) {
    return null
  }

  const data = sanitizeAllTransactionsResponse(value.data)
  if (!data || normalizeQuery(data.query) !== queryKey) {
    return null
  }
  return { data, cachedAt: value.cachedAt }
}

/** Persists one aggregate result without credentials or fields outside the API response contract. */
export function persistAllTransactionsResult(
  ownerId: string,
  query: string,
  data: AllTransactionsResponse,
): void {
  const queryKey = normalizeQuery(query)
  const sanitized = sanitizeAllTransactionsResponse(data)
  if (!sanitized || normalizeQuery(sanitized.query) !== queryKey) {
    return
  }

  try {
    const entry: PersistedAllTransactionsEntry = {
      version: CACHE_VERSION,
      ownerId,
      queryKey,
      cachedAt: Date.now(),
      data: sanitized,
    }
    window.sessionStorage.setItem(storageKey(ownerId, queryKey), JSON.stringify(entry))
  } catch {
    // Caching is an enhancement; quota and privacy-mode failures are non-fatal.
  }
}

/** Reads only a current, schema-valid aggregate response for this exact owner/query scope. */
export function readPersistedAllTransactionsResult(
  ownerId: string,
  query: string,
  now: number = Date.now(),
): PersistedAllTransactionsResult | null {
  const queryKey = normalizeQuery(query)
  const key = storageKey(ownerId, queryKey)
  try {
    const raw = window.sessionStorage.getItem(key)
    if (!raw) {
      return null
    }
    const result = parseEntry(JSON.parse(raw), ownerId, queryKey, now)
    if (!result) {
      window.sessionStorage.removeItem(key)
      return null
    }
    return result
  } catch {
    try {
      window.sessionStorage.removeItem(key)
    } catch {
      // Storage access may itself be unavailable.
    }
    return null
  }
}
