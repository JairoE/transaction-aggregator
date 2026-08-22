const STORAGE_PREFIX = 'ta:search-history:'
const TTL_MS = 7 * 24 * 60 * 60 * 1000
const MAX_ENTRIES = 100
const MAX_QUERY_LENGTH = 200

export interface SearchHistoryEntry {
  query: string
  searchedAt: number
}

function storageKey(ownerId: string): string {
  return `${STORAGE_PREFIX}${ownerId}`
}

function isSearchHistoryEntry(value: unknown): value is SearchHistoryEntry {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { query?: unknown }).query === 'string' &&
    (value as { query: string }).query.trim().length > 0 &&
    (value as { query: string }).query.length <= MAX_QUERY_LENGTH &&
    typeof (value as { searchedAt?: unknown }).searchedAt === 'number' &&
    Number.isFinite((value as { searchedAt: number }).searchedAt)
  )
}

function writeHistory(ownerId: string, entries: SearchHistoryEntry[]): void {
  const key = storageKey(ownerId)
  if (entries.length === 0) {
    window.localStorage.removeItem(key)
    return
  }
  window.localStorage.setItem(key, JSON.stringify(entries))
}

/** Reads and sanitizes one owner's browser-local phrase history. Expired,
 * future-dated, and malformed records are removed as part of every read. */
export function readSearchHistory(
  ownerId: string,
  now: number = Date.now(),
): SearchHistoryEntry[] {
  const key = storageKey(ownerId)
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) {
      return []
    }

    const parsed: unknown = JSON.parse(raw)
    const entries = Array.isArray(parsed)
      ? parsed
          .filter(isSearchHistoryEntry)
          .filter((entry) => entry.searchedAt <= now && now - entry.searchedAt < TTL_MS)
          .sort((left, right) => right.searchedAt - left.searchedAt)
          .slice(0, MAX_ENTRIES)
      : []

    writeHistory(ownerId, entries)
    return entries
  } catch {
    try {
      window.localStorage.removeItem(key)
    } catch {
      // Storage may be disabled entirely; history must remain best-effort.
    }
    return []
  }
}

export function recordSearchHistory(ownerId: string, query: string, now: number = Date.now()): void {
  const normalizedQuery = query.trim().slice(0, MAX_QUERY_LENGTH)
  if (!normalizedQuery) {
    return
  }

  try {
    const entry: SearchHistoryEntry = { query: normalizedQuery, searchedAt: now }
    const dedupeKey = normalizedQuery.toLocaleLowerCase()
    const entries = readSearchHistory(ownerId, now).filter(
      (saved) => saved.query.toLocaleLowerCase() !== dedupeKey,
    )
    writeHistory(ownerId, [entry, ...entries].slice(0, MAX_ENTRIES))
  } catch {
    // Search history is an enhancement; storage failures must not block search.
  }
}
