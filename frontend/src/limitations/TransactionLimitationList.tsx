import type { TransactionLimitationResponse } from './api'

export type BusyRuleAction = {
  ruleId: string
  action: 'enable' | 'disable' | 'delete'
} | null

interface Props {
  rules: TransactionLimitationResponse[]
  busyAction: BusyRuleAction
  onEdit: (rule: TransactionLimitationResponse) => void
  onToggle: (rule: TransactionLimitationResponse) => void
  onDelete: (rule: TransactionLimitationResponse) => void
}

function windowSummary(rule: TransactionLimitationResponse): string {
  if (rule.window.type === 'rolling') {
    return `Last ${rule.window.days} days`
  }
  if (rule.window.type === 'fixed') {
    return `${rule.window.start_date} through ${rule.window.end_date}`
  }
  return 'All available history'
}

export function TransactionLimitationList({ rules, busyAction, onEdit, onToggle, onDelete }: Props) {
  if (rules.length === 0) {
    return <p className="limitation-list__empty">No transaction limitation rules yet.</p>
  }
  return (
    <section className="limitation-list" aria-labelledby="saved-rules-heading">
      <h2 id="saved-rules-heading">Saved rules</h2>
      <div className="limitation-list__grid">
        {rules.map((rule) => {
          const pendingAction = busyAction?.ruleId === rule.id ? busyAction.action : null
          const toggleLabel = pendingAction === 'disable'
            ? 'Disabling…'
            : pendingAction === 'enable'
              ? 'Enabling…'
              : rule.is_enabled ? 'Disable' : 'Enable'

          return <article className="limitation-rule" key={rule.id}>
            <div>
              <h3>{rule.keyword}</h3>
              <p>{rule.threshold} transactions · {windowSummary(rule)}</p>
              <p>{rule.card_scope === 'all_cards' ? 'Every card independently' : `${rule.card_ids.length} selected cards`}</p>
              {rule.needs_card_selection && (
                <p className="limitation-rule__warning" role="status">
                  Needs card selection. Edit this rule to choose an active card.
                </p>
              )}
              <span className="status-chip">{rule.is_enabled ? 'Enabled' : 'Disabled'}</span>
            </div>
            <div className="limitation-rule__actions">
              <button type="button" disabled={busyAction !== null} onClick={() => onEdit(rule)}>Edit</button>
              <button
                type="button"
                aria-busy={pendingAction === 'enable' || pendingAction === 'disable'}
                disabled={busyAction !== null}
                onClick={() => onToggle(rule)}
              >
                {toggleLabel}
              </button>
              <button
                type="button"
                aria-busy={pendingAction === 'delete'}
                disabled={busyAction !== null}
                onClick={() => onDelete(rule)}
              >
                {pendingAction === 'delete' ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </article>
        })}
      </div>
    </section>
  )
}
