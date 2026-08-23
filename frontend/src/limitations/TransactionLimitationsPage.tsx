import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AppShell } from '../shell/AppShell'
import {
  TRANSACTION_LIMITATIONS_QUERY_KEY,
  TRANSACTION_LIMIT_ALERTS_QUERY_KEY,
  createTransactionLimitation,
  deleteTransactionLimitation,
  fetchTransactionLimitations,
  updateTransactionLimitation,
  type CreateTransactionLimitationRequest,
  type TransactionLimitationResponse,
} from './api'
import { TransactionLimitationForm } from './TransactionLimitationForm'
import { TransactionLimitationList } from './TransactionLimitationList'

export function TransactionLimitationsPage() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<TransactionLimitationResponse | null>(null)
  const [busyRuleId, setBusyRuleId] = useState<string | null>(null)
  const query = useQuery({
    queryKey: TRANSACTION_LIMITATIONS_QUERY_KEY,
    queryFn: fetchTransactionLimitations,
  })

  async function invalidate() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: TRANSACTION_LIMITATIONS_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: TRANSACTION_LIMIT_ALERTS_QUERY_KEY }),
    ])
  }

  const saveMutation = useMutation({
    mutationFn: (input: CreateTransactionLimitationRequest) => editing
      ? updateTransactionLimitation(editing.id, input)
      : createTransactionLimitation(input),
    onSuccess: async () => {
      setEditing(null)
      await invalidate()
    },
  })
  const updateMutation = useMutation({
    mutationFn: ({ id, is_enabled }: { id: string; is_enabled: boolean }) =>
      updateTransactionLimitation(id, { is_enabled }),
    onSuccess: invalidate,
    onSettled: () => setBusyRuleId(null),
  })
  const deleteMutation = useMutation({
    mutationFn: deleteTransactionLimitation,
    onSuccess: invalidate,
    onSettled: () => setBusyRuleId(null),
  })

  return (
    <AppShell currentStep={3} statusPillText="Informational limits" actionLink={{ label: 'View cards', to: '/dashboard' }}>
      <main className="limitations-page">
        <p className="eyebrow">Transaction limitations</p>
        <h1>Set transaction-count alerts</h1>
        <p className="limitations-page__notice"><strong>Informational alerts only.</strong> These rules cannot block or decline card transactions.</p>
        {query.isPending ? <p role="status">Loading transaction limits…</p> : query.isError ? (
          <p role="alert">We could not load transaction limits. Try again.</p>
        ) : (
          <div className="limitations-page__layout">
            <TransactionLimitationForm
              cards={query.data.cards}
              initialRule={editing}
              busy={saveMutation.isPending}
              onSubmit={(input) => saveMutation.mutate(input)}
              onCancel={editing ? () => setEditing(null) : undefined}
            />
            {saveMutation.isError && <p className="form-error" role="alert">We could not save that rule. Check the fields and try again.</p>}
            <TransactionLimitationList
              rules={query.data.rules}
              busyRuleId={busyRuleId}
              onEdit={setEditing}
              onToggle={(rule) => {
                setBusyRuleId(rule.id)
                updateMutation.mutate({ id: rule.id, is_enabled: !rule.is_enabled })
              }}
              onDelete={(rule) => {
                if (window.confirm(`Delete the transaction limitation for “${rule.keyword}”?`)) {
                  setBusyRuleId(rule.id)
                  deleteMutation.mutate(rule.id)
                }
              }}
            />
          </div>
        )}
      </main>
    </AppShell>
  )
}
