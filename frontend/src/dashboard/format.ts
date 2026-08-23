/**
 * Pure text-formatting helpers for the dashboard. Kept free of JSX and
 * network concerns so they are trivial to unit test and reuse from both
 * `CardPanel` and `TransactionList`.
 */

function locale(): string {
  return typeof navigator !== 'undefined' && navigator.language ? navigator.language : 'en-US'
}

/**
 * The API's `amount_cents` follows Plaid's convention: positive means money
 * out (a purchase). Card statements read as plain amounts, so a purchase
 * renders as `$184.20` and only money coming back gets a leading `+`. The
 * stored value is never mutated.
 */
export function formatAmount(amountCents: number, currencyCode: string): string {
  const formatted = new Intl.NumberFormat(locale(), {
    style: 'currency',
    currency: currencyCode,
  }).format(Math.abs(amountCents) / 100)
  return amountCents < 0 ? `+${formatted}` : formatted
}

/** Screen-reader wording, since a bare number does not say which way it went. */
export function describeAmount(amountCents: number, currencyCode: string): string {
  const formatted = new Intl.NumberFormat(locale(), {
    style: 'currency',
    currency: currencyCode,
  }).format(Math.abs(amountCents) / 100)
  return amountCents < 0 ? `${formatted} credited` : `${formatted} charged`
}

/** Formats a `YYYY-MM-DD` date string as a short label like "Aug 17". */
export function formatShortDate(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00`)
  return new Intl.DateTimeFormat(locale(), { month: 'short', day: 'numeric' }).format(date)
}

/** Formats a `YYYY-MM-DD` date string as a medium label like "Jul 31, 2026". */
export function formatDateWithYear(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00`)
  return new Intl.DateTimeFormat(locale(), {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(date)
}

/** Right-aligned header status pill text, derived from `cache_as_of`. */
export function formatSyncStatus(cacheAsOf: string | null, now: Date = new Date()): string {
  if (!cacheAsOf) {
    return 'Not yet synced'
  }
  const then = new Date(cacheAsOf)
  const diffMinutes = Math.max(0, Math.round((now.getTime() - then.getTime()) / 60_000))
  if (diffMinutes < 1) {
    return 'Synced just now'
  }
  if (diffMinutes < 60) {
    return `Synced ${diffMinutes}m ago`
  }
  const diffHours = Math.round(diffMinutes / 60)
  if (diffHours < 24) {
    return `Synced ${diffHours}h ago`
  }
  const diffDays = Math.round(diffHours / 24)
  return `Synced ${diffDays}d ago`
}

/**
 * An exact, locale-formatted moment — "Aug 19, 2026, 10:00 AM" — for the
 * places a relative label like `formatSyncStatus`'s "58m ago" would be too
 * vague: a stale bank connection or an offline banner both need to show
 * precisely which cached snapshot the owner is looking at.
 */
export function formatExactTimestamp(isoTimestamp: string): string {
  return new Intl.DateTimeFormat(locale(), {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(isoTimestamp))
}

/** "8 cards · 4 banks" eyebrow line above the grid. */
export function buildFleetSummary(cardCount: number, bankCount: number): string {
  const cardWord = cardCount === 1 ? 'card' : 'cards'
  const bankWord = bankCount === 1 ? 'bank' : 'banks'
  return `${cardCount} ${cardWord} · ${bankCount} ${bankWord}`
}

/** `10 matches for "Paze" across 8 cards`, with real curly quotes. */
export function buildResultsSummary(query: string, totalMatches: number, cardCount: number): string {
  const matchWord = totalMatches === 1 ? 'match' : 'matches'
  const cardWord = cardCount === 1 ? 'card' : 'cards'
  return `${totalMatches} ${matchWord} for “${query}” across ${cardCount} ${cardWord}`
}
