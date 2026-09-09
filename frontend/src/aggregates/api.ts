import { apiClient } from '../api/client'
import type { components } from '../api/generated'

export type TransactionAggregateListResponse = components['schemas']['TransactionAggregateListResponse']
export type TransactionAggregateResponse = components['schemas']['TransactionAggregateResponse']
export type CreateTransactionAggregateRequest = components['schemas']['CreateTransactionAggregateRequest']
export type UpdateTransactionAggregateRequest = components['schemas']['UpdateTransactionAggregateRequest']
export type SavedTransactionAggregateListResponse = components['schemas']['SavedTransactionAggregateListResponse']
export type SavedTransactionAggregateResponse = components['schemas']['SavedTransactionAggregateResponse']
export type AggregateCard = components['schemas']['CardResponse']

export const TRANSACTION_AGGREGATES_QUERY_KEY = ['transaction-aggregates'] as const
export const SAVED_TRANSACTION_AGGREGATES_QUERY_KEY = ['saved-transaction-aggregates'] as const

export function fetchTransactionAggregates(): Promise<TransactionAggregateListResponse> {
  return apiClient.request('/api/transaction-aggregates')
}

export function createTransactionAggregate(
  input: CreateTransactionAggregateRequest,
): Promise<TransactionAggregateResponse> {
  return apiClient.request('/api/transaction-aggregates', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function updateTransactionAggregate(
  aggregateId: string,
  input: UpdateTransactionAggregateRequest,
): Promise<TransactionAggregateResponse> {
  return apiClient.request(`/api/transaction-aggregates/${encodeURIComponent(aggregateId)}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function deleteTransactionAggregate(aggregateId: string): Promise<void> {
  return apiClient.request(`/api/transaction-aggregates/${encodeURIComponent(aggregateId)}`, {
    method: 'DELETE',
  })
}

export function fetchSavedTransactionAggregates(): Promise<SavedTransactionAggregateListResponse> {
  return apiClient.request('/api/saved-transaction-aggregates')
}
