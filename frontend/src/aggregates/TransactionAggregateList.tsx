import type { TransactionAggregateResponse } from './api'

export type BusyAggregateAction = {
  aggregateId: string
  action: 'delete'
} | null

interface Props {
  aggregates: TransactionAggregateResponse[]
  busyAction: BusyAggregateAction
  onEdit: (aggregate: TransactionAggregateResponse) => void
  onDelete: (aggregate: TransactionAggregateResponse) => void
}

export function TransactionAggregateList({
  aggregates,
  busyAction,
  onEdit,
  onDelete,
}: Props) {
  if (aggregates.length === 0) {
    return <p className="limitation-list__empty">No saved aggregates yet.</p>
  }

  return (
    <div className="limitation-list__grid" aria-label="Existing saved aggregates">
      {aggregates.map((aggregate) => {
        const deleting = busyAction?.aggregateId === aggregate.id
        return (
          <article className="limitation-rule aggregate-rule" key={aggregate.id}>
            <div>
              <h3>{aggregate.keyword}</h3>
              <p>Purchases, refunds, and net · All available history</p>
              <p>{aggregate.card_scope === 'all_cards'
                ? 'Every card independently'
                : `${aggregate.card_ids.length} selected cards`}</p>
            </div>
            <div className="limitation-rule__actions">
              <button
                type="button"
                aria-label={`Edit ${aggregate.keyword}`}
                disabled={busyAction !== null}
                onClick={() => onEdit(aggregate)}
              >
                Edit
              </button>
              <button
                type="button"
                aria-label={`Delete ${aggregate.keyword}`}
                aria-busy={deleting}
                disabled={busyAction !== null}
                onClick={() => onDelete(aggregate)}
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </article>
        )
      })}
    </div>
  )
}
