import type { TransactionLimitationResponse } from './api'

interface Props {
  rules: TransactionLimitationResponse[]
  busyRuleId: string | null
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

export function TransactionLimitationList({ rules, busyRuleId, onEdit, onToggle, onDelete }: Props) {
  if (rules.length === 0) {
    return <p className="limitation-list__empty">No transaction limitation rules yet.</p>
  }
  return (
    <section className="limitation-list" aria-labelledby="saved-rules-heading">
      <h2 id="saved-rules-heading">Saved rules</h2>
      <div className="limitation-list__grid">
        {rules.map((rule) => (
          <article className="limitation-rule" key={rule.id}>
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
              <button type="button" onClick={() => onEdit(rule)}>Edit</button>
              <button type="button" disabled={busyRuleId === rule.id} onClick={() => onToggle(rule)}>
                {rule.is_enabled ? 'Disable' : 'Enable'}
              </button>
              <button type="button" disabled={busyRuleId === rule.id} onClick={() => onDelete(rule)}>
                Delete
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
