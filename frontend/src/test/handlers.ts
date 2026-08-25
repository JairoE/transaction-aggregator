import { http, HttpResponse } from 'msw'
import type { components } from '../api/generated'

type BankConnectionResponse = components['schemas']['BankConnectionResponse']
type ConnectionsResponse = components['schemas']['ConnectionsResponse']
type SessionResponse = components['schemas']['SessionResponse']

export const TEST_OWNER = { id: 'owner-1', email: 'owner@example.com' }
export const TEST_CSRF_TOKEN = 'test-csrf-token-0123456789abcdef'

export function sessionResponse(): SessionResponse {
  return { owner: TEST_OWNER, csrf_token: TEST_CSRF_TOKEN }
}

const BANK_SLUGS = ['capital-one', 'chase', 'citi', 'wells-fargo'] as const

const DISPLAY_NAMES: Record<(typeof BANK_SLUGS)[number], string> = {
  'capital-one': 'Capital One',
  chase: 'Chase',
  citi: 'Citi',
  'wells-fargo': 'Wells Fargo',
}

export function makeBank(
  overrides: Partial<BankConnectionResponse> & { bank: BankConnectionResponse['bank'] },
): BankConnectionResponse {
  return {
    action: 'none',
    cache_as_of: null,
    card_count: 0,
    connected: false,
    connection_id: null,
    consent_expiration_at: null,
    display_name: DISPLAY_NAMES[overrides.bank],
    institution_name: null,
    last_error_code: null,
    last_provider_update_at: null,
    last_successful_sync_at: null,
    lifecycle_status: 'disconnected',
    message: 'Not connected.',
    refresh_supported: true,
    state: 'disconnected',
    ...overrides,
  }
}

export function makeConnectionsResponse(
  bankOverrides: (Partial<BankConnectionResponse> & { bank: BankConnectionResponse['bank'] })[] = [],
  extra: Partial<ConnectionsResponse> = {},
): ConnectionsResponse {
  const bySlug = new Map(bankOverrides.map((entry) => [entry.bank, entry]))
  return {
    banks: BANK_SLUGS.map((slug) => makeBank(bySlug.get(slug) ?? { bank: slug })),
    production_item_count: 0,
    production_item_limit: 10,
    environment: 'demo',
    uses_demo_bank: true,
    ...extra,
  }
}

/**
 * Anonymous visitor: no owner session. Individual tests layer on top.
 *
 * The default `/api/connections` response (four disconnected banks, no
 * attention needed) exists so specs that never touch bank connections —
 * most dashboard specs — don't have to mock an endpoint they don't care
 * about. `onUnhandledRequest: 'error'` in `./setup.ts` means any request
 * without a matching handler fails the test, and `DashboardPage` now reads
 * `/api/connections` (for `CacheStatusBanner`) on every render. Tests that
 * do care about connection health override this via `connectionsHandler(...)`.
 */
export const handlers = [
  http.get('/api/auth/session', () =>
    HttpResponse.json({ code: 'AUTH_REQUIRED', message: 'Sign in to continue.' }, { status: 401 }),
  ),
  http.get('/api/connections', () => HttpResponse.json(makeConnectionsResponse())),
  http.get('/api/transaction-limit-alerts', () => HttpResponse.json({
    alerts: [],
    evaluated_at: '2026-08-22T12:00:00Z',
    as_of_date: '2026-08-22',
    cache_as_of: null,
  })),
]

export function authenticatedSessionHandler() {
  return http.get('/api/auth/session', () => HttpResponse.json(sessionResponse()))
}

export function loginSuccessHandler() {
  return http.post('/api/auth/login', () => HttpResponse.json(sessionResponse()))
}

export function loginFailureHandler() {
  return http.post('/api/auth/login', () =>
    HttpResponse.json({ code: 'AUTH_INVALID', message: 'Email or password is incorrect.' }, { status: 401 }),
  )
}

export function logoutHandler() {
  return http.post('/api/auth/logout', () => new HttpResponse(null, { status: 204 }))
}

export function connectionsHandler(response: ConnectionsResponse) {
  return http.get('/api/connections', () => HttpResponse.json(response))
}
