import { useEffect, useState, type FormEvent } from 'react'
import type {
  CreateTransactionLimitationRequest,
  LimitationCard,
  TransactionLimitationResponse,
} from './api'

interface Props {
  cards: LimitationCard[]
  initialRule?: TransactionLimitationResponse | null
  busy: boolean
  onSubmit: (input: CreateTransactionLimitationRequest) => void
  onCancel?: () => void
}

export function TransactionLimitationForm({ cards, initialRule, busy, onSubmit, onCancel }: Props) {
  const [keyword, setKeyword] = useState(initialRule?.keyword ?? '')
  const [threshold, setThreshold] = useState(String(initialRule?.threshold ?? 1))
  const [scope, setScope] = useState<'all_cards' | 'selected_cards'>(initialRule?.card_scope ?? 'all_cards')
  const [cardIds, setCardIds] = useState<string[]>(initialRule?.card_ids ?? [])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setKeyword(initialRule?.keyword ?? '')
    setThreshold(String(initialRule?.threshold ?? 1))
    setScope(initialRule?.card_scope ?? 'all_cards')
    setCardIds(initialRule?.card_ids ?? [])
    setError(null)
  }, [initialRule])

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsedThreshold = Number(threshold)
    if (!keyword.trim()) {
      setError('Enter a keyword or phrase.')
      return
    }
    if (!Number.isInteger(parsedThreshold) || parsedThreshold < 1 || parsedThreshold > 10_000) {
      setError('Enter a transaction threshold from 1 through 10,000.')
      return
    }
    if (scope === 'selected_cards' && cardIds.length === 0) {
      setError('Select at least one card.')
      return
    }
    setError(null)
    onSubmit({
      keyword: keyword.trim(),
      threshold: parsedThreshold,
      card_scope: scope,
      card_ids: scope === 'all_cards' ? [] : cardIds,
      window: { type: 'all_time' },
      is_enabled: initialRule?.is_enabled ?? true,
    })
  }

  return (
    <form className="limitation-form" onSubmit={submit} noValidate>
      <h2>{initialRule ? 'Edit rule' : 'Create a rule'}</h2>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="form-field">
        <label htmlFor="limitation-keyword">Keyword or phrase</label>
        <input
          id="limitation-keyword"
          maxLength={100}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
        />
      </div>
      <div className="form-field">
        <label htmlFor="limitation-threshold">Transaction threshold</label>
        <input
          id="limitation-threshold"
          type="number"
          min={1}
          max={10_000}
          value={threshold}
          onChange={(event) => setThreshold(event.target.value)}
        />
      </div>
      <fieldset className="limitation-form__fieldset">
        <legend>Cards</legend>
        <label>
          <input
            type="radio"
            name="card-scope"
            checked={scope === 'all_cards'}
            onChange={() => setScope('all_cards')}
          />
          All cards, including cards connected later
        </label>
        <label>
          <input
            type="radio"
            name="card-scope"
            checked={scope === 'selected_cards'}
            onChange={() => setScope('selected_cards')}
          />
          Selected cards
        </label>
        {scope === 'selected_cards' && (
          <div className="limitation-form__cards">
            {cards.map((card) => (
              <label key={card.id}>
                <input
                  type="checkbox"
                  checked={cardIds.includes(card.id)}
                  onChange={(event) => setCardIds((current) => event.target.checked
                    ? [...current, card.id]
                    : current.filter((id) => id !== card.id))}
                />
                {card.bank_display_name} {card.name} ending in {card.mask ?? 'unknown'}
              </label>
            ))}
          </div>
        )}
      </fieldset>
      <fieldset className="limitation-form__fieldset">
        <legend>Date window</legend>
        <label>
          <input type="radio" checked readOnly />
          All available history
        </label>
      </fieldset>
      <div className="limitation-form__actions">
        <button type="submit" className="primary-button" disabled={busy}>
          {busy ? 'Saving…' : initialRule ? 'Update rule' : 'Save rule'}
        </button>
        {onCancel && <button type="button" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  )
}
