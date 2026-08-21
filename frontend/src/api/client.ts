/**
 * Thin fetch wrapper for the same-origin, cookie-authenticated API.
 *
 * - Always sends `credentials: 'same-origin'` so the session cookie travels
 *   with every request.
 * - Attaches `X-CSRF-Token` only for mutating requests (never for GET/HEAD),
 *   using whatever token the auth layer currently holds.
 * - Decodes the backend's stable `{code, message}` error envelope into a
 *   typed `ApiError` instead of a generic HTTP failure.
 * - Never retries a request itself. When the server reports `AUTH_REQUIRED`
 *   it notifies a registered listener so the auth layer can drop the stale
 *   session and route the owner back to sign-in; it does not resubmit the
 *   original (possibly mutating) request.
 */

export interface ApiErrorPayload {
  code: string
  message: string
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(payload: ApiErrorPayload, status: number) {
    super(payload.message)
    this.name = 'ApiError'
    this.code = payload.code
    this.status = status
  }
}

export interface RequestOptions extends RequestInit {
  /**
   * Force CSRF header behavior. When omitted, the header is attached
   * automatically for mutating HTTP methods (POST/PUT/PATCH/DELETE) and
   * skipped for safe methods.
   */
  csrf?: boolean
}

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

function resolveUrl(path: string): string {
  if (typeof window !== 'undefined' && window.location) {
    return new URL(path, window.location.origin).toString()
  }
  return path
}

function isErrorPayload(value: unknown): value is ApiErrorPayload {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as Record<string, unknown>).code === 'string' &&
    typeof (value as Record<string, unknown>).message === 'string'
  )
}

export type AuthRequiredListener = () => void

export class ApiClient {
  private authRequiredListener: AuthRequiredListener | null = null

  constructor(private readonly getCsrfToken: () => string | null) {}

  onAuthRequired(listener: AuthRequiredListener | null): void {
    this.authRequiredListener = listener
  }

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const { csrf, headers: headersInit, ...rest } = options
    const method = (rest.method ?? 'GET').toString().toUpperCase()
    const headers = new Headers(headersInit)
    const shouldAttachCsrf = csrf ?? MUTATING_METHODS.has(method)

    if (rest.body !== undefined && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }
    if (shouldAttachCsrf) {
      const token = this.getCsrfToken()
      if (token) {
        headers.set('X-CSRF-Token', token)
      }
    }

    const response = await fetch(resolveUrl(path), {
      ...rest,
      method,
      headers,
      credentials: 'same-origin',
    })

    if (response.status === 204) {
      return undefined as T
    }

    const text = await response.text()
    const data: unknown = text.length > 0 ? JSON.parse(text) : undefined

    if (!response.ok) {
      const payload: ApiErrorPayload = isErrorPayload(data)
        ? data
        : { code: 'UNKNOWN_ERROR', message: 'Something went wrong. Try again.' }
      if (payload.code === 'AUTH_REQUIRED') {
        this.authRequiredListener?.()
      }
      throw new ApiError(payload, response.status)
    }

    return data as T
  }
}

let currentCsrfToken: string | null = null

export function setCsrfToken(token: string | null): void {
  currentCsrfToken = token
}

export function getCsrfToken(): string | null {
  return currentCsrfToken
}

/**
 * Shared client instance. The CSRF token is mutated by the auth layer as
 * sessions start, refresh, and end; every consumer reads through
 * `getCsrfToken` so there is exactly one source of truth.
 */
export const apiClient = new ApiClient(() => currentCsrfToken)
