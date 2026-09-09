import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  SAVED_TRANSACTION_AGGREGATES_QUERY_KEY,
  TRANSACTION_AGGREGATES_QUERY_KEY,
  createTransactionAggregate,
  deleteTransactionAggregate,
  fetchTransactionAggregates,
  updateTransactionAggregate,
  type CreateTransactionAggregateRequest,
  type TransactionAggregateResponse,
} from './api'
import { TransactionAggregateForm } from './TransactionAggregateForm'
import {
  TransactionAggregateList,
  type BusyAggregateAction,
} from './TransactionAggregateList'

export function TransactionAggregatesSection() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<TransactionAggregateResponse | null>(null)
  const [busyAction, setBusyAction] = useState<BusyAggregateAction>(null)
  const [operationError, setOperationError] = useState<string | null>(null)
  const query = useQuery({
    queryKey: TRANSACTION_AGGREGATES_QUERY_KEY,
    queryFn: fetchTransactionAggregates,
  })

  async function invalidate() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: TRANSACTION_AGGREGATES_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: SAVED_TRANSACTION_AGGREGATES_QUERY_KEY }),
    ])
  }

  const saveMutation = useMutation({
    mutationFn: (input: CreateTransactionAggregateRequest) => editing
      ? updateTransactionAggregate(editing.id, input)
      : createTransactionAggregate(input),
    onSuccess: async () => {
      setEditing(null)
      await invalidate()
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (aggregate: TransactionAggregateResponse) =>
      deleteTransactionAggregate(aggregate.id),
    onSuccess: invalidate,
    onError: (_error, aggregate) => {
      setOperationError(`We could not delete “${aggregate.keyword}”. Try again.`)
    },
    onSettled: () => setBusyAction(null),
  })

  return (
    <section
      className="transaction-aggregates-section"
      aria-labelledby="transaction-aggregates-heading"
    >
      <div className="transaction-aggregates-section__intro">
        <h2 id="transaction-aggregates-heading">Saved aggregates</h2>
        <p>Keep a recurring purchase, refund, and net-total summary on each matching card.</p>
      </div>
      {query.isPending ? <p role="status">Loading saved aggregates…</p> : query.isError ? (
        <p role="alert">We could not load saved aggregates. Try again.</p>
      ) : (
        <div className="limitations-page__layout">
          <TransactionAggregateForm
            cards={query.data.cards}
            initialAggregate={editing}
            busy={saveMutation.isPending}
            onSubmit={(input) => saveMutation.mutate(input)}
            onCancel={editing ? () => setEditing(null) : undefined}
          />
          {saveMutation.isError && (
            <p className="form-error" role="alert">
              We could not save that aggregate. Check the fields and try again.
            </p>
          )}
          {operationError && <p className="form-error" role="alert">{operationError}</p>}
          <TransactionAggregateList
            aggregates={query.data.aggregates}
            busyAction={busyAction}
            onEdit={setEditing}
            onDelete={(aggregate) => {
              if (window.confirm(`Delete the saved aggregate for “${aggregate.keyword}”?`)) {
                setOperationError(null)
                setBusyAction({ aggregateId: aggregate.id, action: 'delete' })
                deleteMutation.mutate(aggregate)
              }
            }}
          />
        </div>
      )}
    </section>
  )
}
