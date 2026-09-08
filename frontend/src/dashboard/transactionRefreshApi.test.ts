import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { setCsrfToken } from '../api/client'
import { server } from '../test/server'
import { transactionRefreshRun } from '../test/dashboardFixtures'
import {
  createTransactionRefresh,
  fetchActiveTransactionRefresh,
  fetchTransactionRefresh,
} from './transactionRefreshApi'

describe('transaction refresh API', () => {
  it('posts one stable idempotency header without a body', async () => {
    setCsrfToken('csrf-token')
    let capturedKey = ''
    let capturedBody = 'unexpected'
    server.use(
      http.post('/api/transaction-refreshes', async ({ request }) => {
        capturedKey = request.headers.get('Idempotency-Key') ?? ''
        capturedBody = await request.text()
        return HttpResponse.json({ coalesced: false, refresh: transactionRefreshRun() }, { status: 202 })
      }),
    )

    await createTransactionRefresh('logical-click-key')

    expect(capturedKey).toBe('logical-click-key')
    expect(capturedBody).toBe('')
  })

  it('encodes the run id and maps an idle active lookup to null', async () => {
    let requestedPath = ''
    server.use(
      http.get('/api/transaction-refreshes/active', () => new HttpResponse(null, { status: 204 })),
      http.get('/api/transaction-refreshes/:refreshId', ({ request }) => {
        const path = new URL(request.url).pathname
        if (!path.endsWith('/active')) requestedPath = path
        return HttpResponse.json(transactionRefreshRun())
      }),
    )

    await fetchTransactionRefresh('refresh/with spaces')
    const active = await fetchActiveTransactionRefresh()

    expect(requestedPath).toBe('/api/transaction-refreshes/refresh%2Fwith%20spaces')
    expect(active).toBeNull()
  })
})
