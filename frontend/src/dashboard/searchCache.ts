/**
 * Session-scoped, owner-namespaced cache for the dashboard's *search*
 * results — the one query that needs to survive going offline (or a
 * reload while offline) so the dashboard can render true offline-first.
 *
 * Deliberately narrow: this module knows about exactly one response shape
 * (`GroupedSearchResponse`) and never touches anything else. In particular
 * it never sees the session cookie (HttpOnly — inaccessible to JS anyway)
 * or the CSRF token (held only in `../api/client.ts`'s module-level
 * variable, never handed to this module). `clearSearchCache` is called from
 * `../auth/AuthProvider.tsx` on logout, the same way that file already
 * clears the Plaid Link continuation on logout.
 */
import type { GroupedSearchResponse } from './api'

const STORAGE_PREFIX = 'ta:search-cache:'
/** Persisted entries older than this are treated as absent. */
const TTL_MS = 12 * 60 * 60 * 1000

interface PersistedSearchEntry {
  data: GroupedSearchResponse
  cachedAt: number
}

export interface PersistedSearchResult {
  data: GroupedSearchResponse
  cachedAt: number
}

function storageKey(ownerId: string, query: string): string {
  return `${STORAGE_PREFIX}${ownerId}:${query}`
}

function isPersistedSearchEntry(value: unknown): value is PersistedSearchEntry {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { cachedAt?: unknown }).cachedAt === 'number' &&
    typeof (value as { data?: unknown }).data === 'object'
  )
}

/** Persists one successful search response. Best-effort: a full, disabled,
 * or otherwise-throwing `sessionStorage` must never break the dashboard. */
export function persistSearchResult(
  ownerId: string,
  query: string,
  data: GroupedSearchResponse,
): void {
  try {
    const entry: PersistedSearchEntry = { data, cachedAt: Date.now() }
    window.sessionStorage.setItem(storageKey(ownerId, query), JSON.stringify(entry))
  } catch {
    // Caching is an enhancement, not a requirement — ignore storage errors.
  }
}

/** Reads back a persisted search result for the exact `(ownerId, query)`
 * pair, or `null` if there isn't one or it has expired past the 12-hour
 * TTL (in which case the stale entry is removed). */
export function readPersistedSearchResult(
  ownerId: string,
  query: string,
  now: number = Date.now(),
): PersistedSearchResult | null {
  const key = storageKey(ownerId, query)
  try {
    const raw = window.sessionStorage.getItem(key)
    if (!raw) {
      return null
    }
    const parsed: unknown = JSON.parse(raw)
    if (!isPersistedSearchEntry(parsed) || now - parsed.cachedAt > TTL_MS) {
      window.sessionStorage.removeItem(key)
      return null
    }
    return { data: parsed.data, cachedAt: parsed.cachedAt }
  } catch {
    window.sessionStorage.removeItem(key)
    return null
  }
}

/** Removes every persisted search entry for one owner. Called on logout so
 * the next signed-in owner (or the next sign-in by the same owner) never
 * inherits another session's cached rows. */
export function clearSearchCache(ownerId: string): void {
  const prefix = `${STORAGE_PREFIX}${ownerId}:`
  const staleKeys: string[] = []
  for (let index = 0; index < window.sessionStorage.length; index += 1) {
    const key = window.sessionStorage.key(index)
    if (key && key.startsWith(prefix)) {
      staleKeys.push(key)
    }
  }
  staleKeys.forEach((key) => window.sessionStorage.removeItem(key))
}
