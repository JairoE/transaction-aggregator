import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, setCsrfToken } from '../api/client'
import { CONNECTIONS_QUERY_KEY } from '../connections/ConnectionsPage'
import { TRANSACTION_LIMIT_ALERTS_QUERY_KEY } from '../limitations/api'
import { server } from '../test/server'
import { transactionRefreshRun } from '../test/dashboardFixtures'
import { useTransactionRefresh } from './useTransactionRefresh'

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return { queryClient, wrapper }
}

afterEach(() => setCsrfToken(null))

describe('useTransactionRefresh', () => {
  it('rediscovers active work and polls it to terminal once', async () => {
    const { queryClient, wrapper } = setup()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    const onTerminal = vi.fn()
    server.use(
      http.get('/api/transaction-refreshes/active', () =>
        HttpResponse.json(transactionRefreshRun({ state: 'running' })),
      ),
      http.get('/api/transaction-refreshes/refresh-1', () =>
        HttpResponse.json(
          transactionRefreshRun({
            state: 'succeeded',
            finished_at: '2026-09-03T12:00:03Z',
            summary: {
              total: 1,
              completed: 1,
              updated: 1,
              attention: 0,
              added: 1,
              modified: 0,
              removed: 0,
            },
          }),
        ),
      ),
    )

    const { result } = renderHook(
      () => useTransactionRefresh({ ownerId: 'owner-1', onTerminal, pollScheduleMs: [10] }),
      { wrapper },
    )

    await waitFor(() => expect(result.current.run?.state).toBe('succeeded'))
    expect(onTerminal).toHaveBeenCalledTimes(1)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['transactions', 'search', 'owner-1'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['transactions', 'all', 'owner-1'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: CONNECTIONS_QUERY_KEY })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: TRANSACTION_LIMIT_ALERTS_QUERY_KEY })
  })

  it('reuses the click key after an ambiguous failure and blocks double starts', async () => {
    const { wrapper } = setup()
    setCsrfToken('csrf-token')
    const keys: string[] = []
    let attempts = 0
    server.use(
      http.get('/api/transaction-refreshes/active', () => new HttpResponse(null, { status: 204 })),
      http.post('/api/transaction-refreshes', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key') ?? '')
        attempts += 1
        if (attempts === 1) return HttpResponse.error()
        return HttpResponse.json(
          { coalesced: true, refresh: transactionRefreshRun({ state: 'running' }) },
          { status: 202 },
        )
      }),
    )
    const { result } = renderHook(
      () => useTransactionRefresh({ ownerId: 'owner-1', pollScheduleMs: [10_000] }),
      { wrapper },
    )

    act(() => {
      result.current.start()
      result.current.start()
    })
    await waitFor(() => expect(result.current.isStarting).toBe(false))
    act(() => result.current.start())
    await waitFor(() => expect(result.current.run?.state).toBe('running'))

    expect(keys).toHaveLength(2)
    expect(keys[0]).toBeTruthy()
    expect(keys[1]).toBe(keys[0])
  })

  it('abandons the click key after a definite client error', async () => {
    const { wrapper } = setup()
    const keys: string[] = []
    server.use(
      http.get('/api/transaction-refreshes/active', () => new HttpResponse(null, { status: 204 })),
      http.post('/api/transaction-refreshes', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key') ?? '')
        return HttpResponse.json({ code: 'NO_ACTIVE_CONNECTIONS', message: 'No connections.' }, { status: 409 })
      }),
    )
    const { result } = renderHook(
      () => useTransactionRefresh({ ownerId: 'owner-1' }),
      { wrapper },
    )

    act(() => result.current.start())
    await waitFor(() => expect(result.current.error).toBeInstanceOf(ApiError))
    act(() => result.current.start())
    await waitFor(() => expect(keys).toHaveLength(2))

    expect(keys[1]).not.toBe(keys[0])
  })
})
