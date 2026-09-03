import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { ApiError } from '../api/client'
import { server } from '../test/server'
import { DEFAULT_ALL_TRANSACTIONS_LIMIT, fetchAllTransactions } from './api'

const aggregateResponse = {
  query: '',
  total_matches: 0,
  card_count: 0,
  bank_count: 0,
  rows: [],
  next_cursor: null,
  has_more: false,
  cache_as_of: null,
}

describe('fetchAllTransactions', () => {
  it('omits blank query and null cursor while using the aggregate default limit', async () => {
    let requestUrl: URL | undefined
    server.use(
      http.get('/api/transactions', ({ request }) => {
        requestUrl = new URL(request.url)
        return HttpResponse.json(aggregateResponse)
      }),
    )

    await expect(fetchAllTransactions('', null)).resolves.toEqual(aggregateResponse)

    expect(DEFAULT_ALL_TRANSACTIONS_LIMIT).toBe(50)
    expect(requestUrl?.pathname).toBe('/api/transactions')
    expect(requestUrl?.searchParams.get('q')).toBeNull()
    expect(requestUrl?.searchParams.get('cursor')).toBeNull()
    expect(requestUrl?.searchParams.get('limit')).toBe('50')
  })

  it('URL encodes and forwards a submitted query, cursor, and explicit limit', async () => {
    let requestUrl: URL | undefined
    server.use(
      http.get('/api/transactions', ({ request }) => {
        requestUrl = new URL(request.url)
        return HttpResponse.json(aggregateResponse)
      }),
    )

    await fetchAllTransactions('Paze & Pay', 'next/one?', 25)

    expect(requestUrl?.search).toBe('?q=Paze+%26+Pay&cursor=next%2Fone%3F&limit=25')
  })

  it.each([
    [0, '1'],
    [500, '50'],
  ])('clamps limit %i to the accepted boundary %s', async (limit, expectedLimit) => {
    let requestUrl: URL | undefined
    server.use(
      http.get('/api/transactions', ({ request }) => {
        requestUrl = new URL(request.url)
        return HttpResponse.json(aggregateResponse)
      }),
    )

    await fetchAllTransactions('', null, limit)

    expect(requestUrl?.searchParams.get('limit')).toBe(expectedLimit)
  })

  it('propagates the shared client structured API error', async () => {
    server.use(
      http.get('/api/transactions', () =>
        HttpResponse.json(
          { code: 'INVALID_CURSOR', message: 'The cursor is no longer valid.' },
          { status: 422 },
        ),
      ),
    )

    await expect(fetchAllTransactions('', 'expired-cursor')).rejects.toMatchObject({
      name: ApiError.name,
      code: 'INVALID_CURSOR',
      status: 422,
      message: 'The cursor is no longer valid.',
    })
  })
})
