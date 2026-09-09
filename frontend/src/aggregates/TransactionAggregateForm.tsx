import { useEffect, useState, type FormEvent } from 'react'
import type {
  AggregateCard,
  CreateTransactionAggregateRequest,
  TransactionAggregateResponse,
} from './api'

interface Props {
  cards: AggregateCard[]
  initialAggregate?: TransactionAggregateResponse | null
  busy: boolean
  onSubmit: (input: CreateTransactionAggregateRequest) => void
  onCancel?: () => void
}

type ValidationField = 'keyword' | 'cards'

interface ValidationError {
  field: ValidationField
  message: string
}

const VALIDATION_ERROR_ID = 'aggregate-form-error'

export function TransactionAggregateForm({
  cards,
  initialAggregate,
  busy,
  onSubmit,
  onCancel,
}: Props) {
  const [keyword, setKeyword] = useState(initialAggregate?.keyword ?? '')
  const [scope, setScope] = useState<'all_cards' | 'selected_cards'>(
    initialAggregate?.card_scope ?? 'all_cards',
  )
  const [cardIds, setCardIds] = useState<string[]>(initialAggregate?.card_ids ?? [])
  const [error, setError] = useState<ValidationError | null>(null)

  useEffect(() => {
    setKeyword(initialAggregate?.keyword ?? '')
    setScope(initialAggregate?.card_scope ?? 'all_cards')
    setCardIds(initialAggregate?.card_ids ?? [])
    setError(null)
  }, [initialAggregate])

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!keyword.trim()) {
      setError({ field: 'keyword', message: 'Enter a keyword or phrase.' })
      return
    }
    if (scope === 'selected_cards' && cardIds.length === 0) {
      setError({ field: 'cards', message: 'Select at least one card.' })
      return
    }
    setError(null)
    onSubmit({
      keyword: keyword.trim(),
      card_scope: scope,
      card_ids: scope === 'all_cards' ? [] : cardIds,
    })
  }

  return (
    <form className="limitation-form aggregate-form" onSubmit={submit} noValidate>
      <h3>{initialAggregate ? 'Edit saved aggregate' : 'Create a saved aggregate'}</h3>
      {error && <p className="form-error" id={VALIDATION_ERROR_ID} role="alert">{error.message}</p>}
      <div className="form-field">
        <label htmlFor="aggregate-keyword">Aggregate search term</label>
        <input
          id="aggregate-keyword"
          aria-describedby={error?.field === 'keyword' ? VALIDATION_ERROR_ID : undefined}
          aria-invalid={error?.field === 'keyword' || undefined}
          maxLength={100}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
        />
      </div>
      <fieldset
        className="limitation-form__fieldset"
        aria-describedby={error?.field === 'cards' ? VALIDATION_ERROR_ID : undefined}
        aria-invalid={error?.field === 'cards' || undefined}
      >
        <legend>Aggregate cards</legend>
        <label>
          <input
            type="radio"
            name="aggregate-card-scope"
            checked={scope === 'all_cards'}
            onChange={() => setScope('all_cards')}
          />
          Every card, including cards connected later
        </label>
        <label>
          <input
            type="radio"
            name="aggregate-card-scope"
            checked={scope === 'selected_cards'}
            onChange={() => setScope('selected_cards')}
          />
          Specific cards
        </label>
        {scope === 'selected_cards' && (
          <div className="limitation-form__cards">
            {cards.length === 0 ? (
              <p>No active cards are available.</p>
            ) : cards.map((card) => (
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
      <p className="aggregate-form__note">Totals use all available history and USD transactions, including pending activity.</p>
      <div className="limitation-form__actions">
        <button type="submit" className="primary-button" disabled={busy}>
          {busy ? 'Saving…' : initialAggregate ? 'Update aggregate' : 'Save aggregate'}
        </button>
        {onCancel && <button type="button" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  )
}
