import { apiClient } from '../api/client'
import type { components } from '../api/generated'

export type CreateTransactionRefreshResponse = components['schemas']['CreateTransactionRefreshResponse']
export type TransactionRefreshResponse = components['schemas']['TransactionRefreshResponse']

export function createTransactionRefresh(
  idempotencyKey: string,
): Promise<CreateTransactionRefreshResponse> {
  return apiClient.request('/api/transaction-refreshes', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
  })
}

export function fetchTransactionRefresh(
  refreshId: string,
): Promise<TransactionRefreshResponse> {
  return apiClient.request(
    `/api/transaction-refreshes/${encodeURIComponent(refreshId)}`,
  )
}

export async function fetchActiveTransactionRefresh(): Promise<TransactionRefreshResponse | null> {
  const run = await apiClient.request<TransactionRefreshResponse | undefined>(
    '/api/transaction-refreshes/active',
  )
  return run ?? null
}
