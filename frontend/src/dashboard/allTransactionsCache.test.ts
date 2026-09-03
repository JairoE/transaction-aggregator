import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  persistAllTransactionsResult,
  readPersistedAllTransactionsResult,
} from './allTransactionsCache'
import type { AllTransactionsResponse } from './api'

const CACHE_KEY = 'transaction-aggregator:all-transactions:v1:owner-a:paze'
const NOW = 1_000_000
const TWELVE_HOURS_MS = 12 * 60 * 60 * 1000

const mergedResponse: AllTransactionsResponse = {
  query: 'Paze',
  total_matches: 1,
  card_count: 1,
  bank_count: 1,
  rows: [
    {
      transaction: {
        id: 'transaction-1',
        card_id: 'card-1',
        merchant_name: 'Paze Checkout',
        description: 'PAZE CHECKOUT PURCHASE',
        original_description: null,
        category: 'Shopping',
        amount_cents: 1999,
        currency_code: 'USD',
        authorized_date: '2026-08-17',
        posted_date: '2026-08-18',
        pending: false,
      },
      card: {
        id: 'card-1',
        connection_id: 'connection-1',
        bank: 'chase',
        bank_display_name: 'Chase',
        name: 'Chase Sapphire',
        official_name: null,
        mask: '1234',
        state: 'ready',
        last_successful_sync_at: '2026-08-18T12:00:00Z',
      },
    },
  ],
  next_cursor: null,
  has_more: false,
  cache_as_of: '2026-08-18T12:00:00Z',
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('all-transactions session cache', () => {
  it('round-trips a merged aggregate response for its owner and normalized submitted query', () => {
    vi.spyOn(Date, 'now').mockReturnValue(NOW)

    persistAllTransactionsResult('owner-a', '  Paze  ', mergedResponse)

    expect(readPersistedAllTransactionsResult('owner-a', 'paze', NOW)).toEqual({
      data: mergedResponse,
      cachedAt: NOW,
    })
  })

  it('isolates results by owner and submitted query', () => {
    vi.spyOn(Date, 'now').mockReturnValue(NOW)
    persistAllTransactionsResult('owner-a', 'Paze', mergedResponse)
    persistAllTransactionsResult('owner-a', '', { ...mergedResponse, query: '' })
    persistAllTransactionsResult('owner-a', 'Juniper', { ...mergedResponse, query: 'Juniper' })

    expect(readPersistedAllTransactionsResult('owner-b', 'Paze', NOW)).toBeNull()
    expect(readPersistedAllTransactionsResult('owner-a', '', NOW)?.data.query).toBe('')
    expect(readPersistedAllTransactionsResult('owner-a', 'Juniper', NOW)?.data.query).toBe('Juniper')
  })

  it('never reads a grouped-search cache key', () => {
    window.sessionStorage.setItem(
      'ta:search-cache:owner-a:paze',
      JSON.stringify({ data: mergedResponse, cachedAt: NOW }),
    )

    expect(readPersistedAllTransactionsResult('owner-a', 'Paze', NOW)).toBeNull()
  })

  it('rejects malformed JSON, an incompatible schema version, and expired entries', () => {
    window.sessionStorage.setItem(CACHE_KEY, '{not-json')
    expect(readPersistedAllTransactionsResult('owner-a', 'Paze', NOW)).toBeNull()

    window.sessionStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        version: 2,
        ownerId: 'owner-a',
        queryKey: 'paze',
        cachedAt: NOW,
        data: mergedResponse,
      }),
    )
    expect(readPersistedAllTransactionsResult('owner-a', 'Paze', NOW)).toBeNull()

    window.sessionStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        version: 1,
        ownerId: 'owner-a',
        queryKey: 'paze',
        cachedAt: NOW - TWELVE_HOURS_MS - 1,
        data: mergedResponse,
      }),
    )
    expect(readPersistedAllTransactionsResult('owner-a', 'Paze', NOW)).toBeNull()
  })

  it('rejects an entry with a row that does not match the aggregate response schema', () => {
    window.sessionStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        version: 1,
        ownerId: 'owner-a',
        queryKey: 'paze',
        cachedAt: NOW,
        data: {
          ...mergedResponse,
          rows: [{ ...mergedResponse.rows[0], card: { ...mergedResponse.rows[0].card, bank: 'other' } }],
        },
      }),
    )

    expect(readPersistedAllTransactionsResult('owner-a', 'Paze', NOW)).toBeNull()
  })

  it('rejects non-last-four card masks before persistence and hydration', () => {
    vi.spyOn(Date, 'now').mockReturnValue(NOW)
    const unsafeResponse: AllTransactionsResponse = {
      ...mergedResponse,
      rows: [{ ...mergedResponse.rows[0], card: { ...mergedResponse.rows[0].card, mask: '12345' } }],
    }

    persistAllTransactionsResult('owner-a', 'Paze', unsafeResponse)
    expect(window.sessionStorage.getItem(CACHE_KEY)).toBeNull()

    window.sessionStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        version: 1,
        ownerId: 'owner-a',
        queryKey: 'paze',
        cachedAt: NOW,
        data: unsafeResponse,
      }),
    )
    expect(readPersistedAllTransactionsResult('owner-a', 'Paze', NOW)).toBeNull()
    expect(window.sessionStorage.getItem(CACHE_KEY)).toBeNull()
  })

  it.each([
    ['description', '4111111111111111'],
    ['merchant_name', '4111 1111 1111 1111'],
    ['original_description', '4111-1111-1111-1111'],
    ['category', 'Category 5555-5555-5555-4444'],
    ['description', '4111  1111  1111  1111'],
    ['merchant_name', '4111\t1111\t1111\t1111'],
    ['original_description', '4111\u00a01111\u00a01111\u00a01111'],
  ] as const)(
    'rejects a PAN-like value in transaction %s before persistence and hydration',
    (field, pan) => {
      vi.spyOn(Date, 'now').mockReturnValue(NOW)
      const unsafeResponse: AllTransactionsResponse = {
        ...mergedResponse,
        rows: [
          {
            ...mergedResponse.rows[0],
            transaction: { ...mergedResponse.rows[0].transaction, [field]: pan },
          },
        ],
      }

      persistAllTransactionsResult('owner-a', 'Paze', unsafeResponse)
      expect(window.sessionStorage.getItem(CACHE_KEY)).toBeNull()

      window.sessionStorage.setItem(
        CACHE_KEY,
        JSON.stringify({
          version: 1,
          ownerId: 'owner-a',
          queryKey: 'paze',
          cachedAt: NOW,
          data: unsafeResponse,
        }),
      )
      expect(readPersistedAllTransactionsResult('owner-a', 'Paze', NOW)).toBeNull()
      expect(window.sessionStorage.getItem(CACHE_KEY)).toBeNull()
    },
  )

  it.each([
    ['name', 'Card 4000\t0000\t0000\t0002'],
    ['bank_display_name', 'Bank 6011\u00a01111\u00a01111\u00a01117'],
    ['official_name', 'Official 4111-1111-1111-1111'],
  ] as const)(
    'rejects a PAN-like value in card %s before persistence and hydration',
    (field, pan) => {
      vi.spyOn(Date, 'now').mockReturnValue(NOW)
      const unsafeResponse: AllTransactionsResponse = {
        ...mergedResponse,
        rows: [
          {
            ...mergedResponse.rows[0],
            card: { ...mergedResponse.rows[0].card, [field]: pan },
          },
        ],
      }

      persistAllTransactionsResult('owner-a', 'Paze', unsafeResponse)
      expect(window.sessionStorage.getItem(CACHE_KEY)).toBeNull()

      window.sessionStorage.setItem(
        CACHE_KEY,
        JSON.stringify({
          version: 1,
          ownerId: 'owner-a',
          queryKey: 'paze',
          cachedAt: NOW,
          data: unsafeResponse,
        }),
      )
      expect(readPersistedAllTransactionsResult('owner-a', 'Paze', NOW)).toBeNull()
      expect(window.sessionStorage.getItem(CACHE_KEY)).toBeNull()
    },
  )

  it.each(['name', 'bank_display_name'] as const)(
    'rejects null required card %s before persistence and hydration',
    (field) => {
      vi.spyOn(Date, 'now').mockReturnValue(NOW)
      const tampered: { rows: Array<{ card: Record<string, unknown> }> } = JSON.parse(
        JSON.stringify(mergedResponse),
      )
      tampered.rows[0].card[field] = null

      persistAllTransactionsResult('owner-a', 'Paze', tampered as unknown as AllTransactionsResponse)
      expect(window.sessionStorage.getItem(CACHE_KEY)).toBeNull()

      window.sessionStorage.setItem(
        CACHE_KEY,
        JSON.stringify({
          version: 1,
          ownerId: 'owner-a',
          queryKey: 'paze',
          cachedAt: NOW,
          data: tampered,
        }),
      )
      expect(readPersistedAllTransactionsResult('owner-a', 'Paze', NOW)).toBeNull()
      expect(window.sessionStorage.getItem(CACHE_KEY)).toBeNull()
    },
  )

  it('keeps ordinary shorter digit groups cacheable', () => {
    vi.spyOn(Date, 'now').mockReturnValue(NOW)
    const ordinaryResponse: AllTransactionsResponse = {
      ...mergedResponse,
      rows: [
        {
          ...mergedResponse.rows[0],
          transaction: {
            ...mergedResponse.rows[0].transaction,
            description: 'Receipt 1234-5678-9012 accepted',
          },
        },
      ],
    }

    persistAllTransactionsResult('owner-a', 'Paze', ordinaryResponse)

    expect(readPersistedAllTransactionsResult('owner-a', 'Paze', NOW)?.data).toEqual(ordinaryResponse)
  })

  it('rejects an entry whose embedded owner or query does not match its key scope', () => {
    window.sessionStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        version: 1,
        ownerId: 'owner-b',
        queryKey: 'juniper',
        cachedAt: NOW,
        data: mergedResponse,
      }),
    )

    expect(readPersistedAllTransactionsResult('owner-a', 'Paze', NOW)).toBeNull()
  })
})
