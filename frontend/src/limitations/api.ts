import { apiClient } from '../api/client'
import type { components } from '../api/generated'

export type TransactionLimitationListResponse = components['schemas']['TransactionLimitationListResponse']
export type TransactionLimitationResponse = components['schemas']['TransactionLimitationResponse']
export type CreateTransactionLimitationRequest = components['schemas']['CreateTransactionLimitationRequest']
export type UpdateTransactionLimitationRequest = components['schemas']['UpdateTransactionLimitationRequest']
export type TransactionLimitAlertListResponse = components['schemas']['TransactionLimitAlertListResponse']
export type TransactionLimitAlertResponse = components['schemas']['TransactionLimitAlertResponse']
export type LimitationCard = components['schemas']['CardResponse']

export const TRANSACTION_LIMITATIONS_QUERY_KEY = ['transaction-limitations'] as const
export const TRANSACTION_LIMIT_ALERTS_QUERY_KEY = ['transaction-limit-alerts'] as const

export function fetchTransactionLimitations(): Promise<TransactionLimitationListResponse> {
  return apiClient.request('/api/transaction-limitations')
}

export function createTransactionLimitation(
  input: CreateTransactionLimitationRequest,
): Promise<TransactionLimitationResponse> {
  return apiClient.request('/api/transaction-limitations', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function updateTransactionLimitation(
  ruleId: string,
  input: UpdateTransactionLimitationRequest,
): Promise<TransactionLimitationResponse> {
  return apiClient.request(`/api/transaction-limitations/${encodeURIComponent(ruleId)}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function deleteTransactionLimitation(ruleId: string): Promise<void> {
  return apiClient.request(`/api/transaction-limitations/${encodeURIComponent(ruleId)}`, {
    method: 'DELETE',
  })
}

export function fetchTransactionLimitAlerts(): Promise<TransactionLimitAlertListResponse> {
  return apiClient.request('/api/transaction-limit-alerts')
}
