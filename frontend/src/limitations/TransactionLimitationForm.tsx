import { useEffect, useState, type FormEvent } from 'react'
import type {
  CreateTransactionLimitationRequest,
  LimitationCard,
  TransactionLimitationResponse,
} from './api'

interface Props {
  cards: LimitationCard[]
  initialRule?: TransactionLimitationResponse | null
  initialKeyword?: string
  initialCardId?: string
  busy: boolean
  onSubmit: (input: CreateTransactionLimitationRequest) => void
  onCancel?: () => void
}

type ValidationField = 'keyword' | 'threshold' | 'cards' | 'rolling-days' | 'fixed-dates'

interface ValidationError {
  field: ValidationField
  message: string
}

const VALIDATION_ERROR_ID = 'limitation-form-error'
const MAX_TOTAL_THRESHOLD_CENTS = 2_147_483_647

function centsToUsdInput(cents: number | null | undefined): string {
  return ((cents ?? 100) / 100).toFixed(2)
}

function parseUsdCents(value: string): number | null {
  const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(value.trim())
  if (!match) {
    return null
  }
  const dollars = Number(match[1])
  const cents = Number((match[2] ?? '').padEnd(2, '0'))
  const total = dollars * 100 + cents
  return Number.isSafeInteger(total) ? total : null
}

export function TransactionLimitationForm({
  cards,
  initialRule,
  initialKeyword,
  initialCardId,
  busy,
  onSubmit,
  onCancel,
}: Props) {
  const [keyword, setKeyword] = useState(initialRule?.keyword ?? initialKeyword ?? '')
  const [metric, setMetric] = useState<'count' | 'net_total_usd'>(initialRule?.metric ?? 'count')
  const [threshold, setThreshold] = useState(String(initialRule?.threshold ?? 1))
  const [totalThreshold, setTotalThreshold] = useState(centsToUsdInput(initialRule?.total_threshold_cents))
  const [scope, setScope] = useState<'all_cards' | 'selected_cards'>(
    initialRule?.card_scope ?? (initialCardId ? 'selected_cards' : 'all_cards'),
  )
  const [cardIds, setCardIds] = useState<string[]>(
    initialRule?.card_ids ?? (initialCardId ? [initialCardId] : []),
  )
  const [windowType, setWindowType] = useState<'all_time' | 'rolling' | 'fixed'>(
    initialRule?.window.type ?? 'all_time',
  )
  const [rollingDays, setRollingDays] = useState(
    String(initialRule?.window.type === 'rolling' ? initialRule.window.days : 5),
  )
  const [startDate, setStartDate] = useState(
    initialRule?.window.type === 'fixed' ? initialRule.window.start_date : '',
  )
  const [endDate, setEndDate] = useState(
    initialRule?.window.type === 'fixed' ? initialRule.window.end_date : '',
  )
  const [error, setError] = useState<ValidationError | null>(null)

  useEffect(() => {
    setKeyword(initialRule?.keyword ?? initialKeyword ?? '')
    setMetric(initialRule?.metric ?? 'count')
    setThreshold(String(initialRule?.threshold ?? 1))
    setTotalThreshold(centsToUsdInput(initialRule?.total_threshold_cents))
    setScope(initialRule?.card_scope ?? (initialCardId ? 'selected_cards' : 'all_cards'))
    setCardIds(initialRule?.card_ids ?? (initialCardId ? [initialCardId] : []))
    setWindowType(initialRule?.window.type ?? 'all_time')
    setRollingDays(String(initialRule?.window.type === 'rolling' ? initialRule.window.days : 5))
    setStartDate(initialRule?.window.type === 'fixed' ? initialRule.window.start_date : '')
    setEndDate(initialRule?.window.type === 'fixed' ? initialRule.window.end_date : '')
    setError(null)
  }, [initialCardId, initialKeyword, initialRule])

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!keyword.trim()) {
      setError({ field: 'keyword', message: 'Enter a keyword or phrase.' })
      return
    }
    const parsedThreshold = Number(threshold)
    const parsedTotalThreshold = parseUsdCents(totalThreshold)
    if (metric === 'count') {
      if (!Number.isInteger(parsedThreshold) || parsedThreshold < 1 || parsedThreshold > 10_000) {
        setError({ field: 'threshold', message: 'Enter a transaction threshold from 1 through 10,000.' })
        return
      }
    } else if (
      parsedTotalThreshold === null
      || parsedTotalThreshold < 1
      || parsedTotalThreshold > MAX_TOTAL_THRESHOLD_CENTS
    ) {
      setError({ field: 'threshold', message: 'Enter a net total threshold in USD.' })
      return
    }
    if (scope === 'selected_cards' && cardIds.length === 0) {
      setError({ field: 'cards', message: 'Select at least one card.' })
      return
    }
    const parsedRollingDays = Number(rollingDays)
    if (
      windowType === 'rolling'
      && (!Number.isInteger(parsedRollingDays) || parsedRollingDays < 1 || parsedRollingDays > 730)
    ) {
      setError({ field: 'rolling-days', message: 'Enter a rolling window from 1 through 730 days.' })
      return
    }
    if (windowType === 'fixed' && (!startDate || !endDate)) {
      setError({ field: 'fixed-dates', message: 'Enter both a start date and an end date.' })
      return
    }
    if (windowType === 'fixed' && startDate > endDate) {
      setError({ field: 'fixed-dates', message: 'End date must be on or after the start date.' })
      return
    }
    setError(null)
    onSubmit({
      keyword: keyword.trim(),
      metric,
      ...(metric === 'count'
        ? { threshold: parsedThreshold }
        : { total_threshold_cents: parsedTotalThreshold as number }),
      card_scope: scope,
      card_ids: scope === 'all_cards' ? [] : cardIds,
      window: windowType === 'rolling'
        ? { type: 'rolling', days: parsedRollingDays }
        : windowType === 'fixed'
          ? { type: 'fixed', start_date: startDate, end_date: endDate }
          : { type: 'all_time' },
      is_enabled: initialRule?.is_enabled ?? true,
    })
  }

  return (
    <form className="limitation-form" onSubmit={submit} noValidate>
      <h2>{initialRule ? 'Edit rule' : 'Create a rule'}</h2>
      {error && <p className="form-error" id={VALIDATION_ERROR_ID} role="alert">{error.message}</p>}
      <div className="form-field">
        <label htmlFor="limitation-keyword">Keyword or phrase</label>
        <input
          id="limitation-keyword"
          aria-describedby={error?.field === 'keyword' ? VALIDATION_ERROR_ID : undefined}
          aria-invalid={error?.field === 'keyword' || undefined}
          maxLength={100}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
        />
      </div>
      <div className="form-field">
        <fieldset
          className="limitation-form__fieldset"
          aria-describedby={error?.field === 'threshold' ? VALIDATION_ERROR_ID : undefined}
        >
          <legend>Alert type</legend>
          <label>
            <input
              type="radio"
              name="limitation-metric"
              checked={metric === 'count'}
              onChange={() => setMetric('count')}
            />
            Transaction count
          </label>
          <label>
            <input
              type="radio"
              name="limitation-metric"
              checked={metric === 'net_total_usd'}
              onChange={() => setMetric('net_total_usd')}
            />
            Net transaction total (USD)
          </label>
        </fieldset>
        <label htmlFor="limitation-threshold">
          {metric === 'count' ? 'Transaction threshold' : 'Net total threshold (USD)'}
        </label>
        <input
          id="limitation-threshold"
          aria-describedby={error?.field === 'threshold' ? VALIDATION_ERROR_ID : undefined}
          aria-invalid={error?.field === 'threshold' || undefined}
          type={metric === 'count' ? 'number' : 'text'}
          min={1}
          max={metric === 'count' ? 10_000 : undefined}
          inputMode={metric === 'count' ? 'numeric' : 'decimal'}
          value={metric === 'count' ? threshold : totalThreshold}
          onChange={(event) => {
            if (metric === 'count') {
              setThreshold(event.target.value)
            } else {
              setTotalThreshold(event.target.value)
            }
          }}
        />
      </div>
      <fieldset
        className="limitation-form__fieldset"
        aria-describedby={error?.field === 'cards' ? VALIDATION_ERROR_ID : undefined}
        aria-invalid={error?.field === 'cards' || undefined}
      >
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
          <input
            type="radio"
            name="date-window"
            checked={windowType === 'all_time'}
            onChange={() => setWindowType('all_time')}
          />
          All available history
        </label>
        <label>
          <input
            type="radio"
            name="date-window"
            checked={windowType === 'rolling'}
            onChange={() => setWindowType('rolling')}
          />
          Last N days
        </label>
        <label>
          <input
            type="radio"
            name="date-window"
            checked={windowType === 'fixed'}
            onChange={() => setWindowType('fixed')}
          />
          Fixed date range
        </label>
        {windowType === 'rolling' && (
          <div className="form-field">
            <label htmlFor="limitation-rolling-days">Number of days</label>
            <input
              id="limitation-rolling-days"
              aria-describedby={error?.field === 'rolling-days' ? VALIDATION_ERROR_ID : undefined}
              aria-invalid={error?.field === 'rolling-days' || undefined}
              type="number"
              min={1}
              max={730}
              inputMode="numeric"
              value={rollingDays}
              onChange={(event) => setRollingDays(event.target.value)}
            />
          </div>
        )}
        {windowType === 'fixed' && (
          <div className="limitation-form__dates">
            <div className="form-field">
              <label htmlFor="limitation-start-date">Start date</label>
              <input
                id="limitation-start-date"
                aria-describedby={error?.field === 'fixed-dates' ? VALIDATION_ERROR_ID : undefined}
                aria-invalid={error?.field === 'fixed-dates' || undefined}
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </div>
            <div className="form-field">
              <label htmlFor="limitation-end-date">End date</label>
              <input
                id="limitation-end-date"
                aria-describedby={error?.field === 'fixed-dates' ? VALIDATION_ERROR_ID : undefined}
                aria-invalid={error?.field === 'fixed-dates' || undefined}
                type="date"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
              />
            </div>
          </div>
        )}
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
