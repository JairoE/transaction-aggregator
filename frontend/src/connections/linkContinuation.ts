/**
 * OAuth continuation storage for the real Plaid Link path.
 *
 * Before Link opens for a bank whose OAuth step redirects away from the
 * page, we remember just enough to reinitialize Link when the browser
 * returns to `/oauth-return`: the bank slug, the same Link token, and an
 * expiry. Nothing else — never a public token, access token, or bank
 * credential — touches storage, and the entry is scoped per owner so one
 * browser profile cannot resume another owner's flow.
 */

import type { BankSlug } from './banks'

export interface LinkContinuation {
  bank: BankSlug
  linkToken: string
  expiresAt: string
}

const KEY_PREFIX = 'ta:link-continuation:'
const CONTINUATION_TTL_MINUTES = 30

function storageKey(ownerId: string): string {
  return `${KEY_PREFIX}${ownerId}`
}

export function continuationExpiry(now: Date = new Date()): string {
  return new Date(now.getTime() + CONTINUATION_TTL_MINUTES * 60_000).toISOString()
}

export function saveLinkContinuation(
  ownerId: string,
  continuation: LinkContinuation,
): void {
  window.sessionStorage.setItem(storageKey(ownerId), JSON.stringify(continuation))
}

export function readLinkContinuation(ownerId: string): LinkContinuation | null {
  const raw = window.sessionStorage.getItem(storageKey(ownerId))
  if (!raw) {
    return null
  }
  try {
    const parsed = JSON.parse(raw) as LinkContinuation
    if (
      typeof parsed.bank !== 'string' ||
      typeof parsed.linkToken !== 'string' ||
      typeof parsed.expiresAt !== 'string'
    ) {
      clearLinkContinuation(ownerId)
      return null
    }
    if (Number.isNaN(Date.parse(parsed.expiresAt)) || Date.parse(parsed.expiresAt) <= Date.now()) {
      clearLinkContinuation(ownerId)
      return null
    }
    return parsed
  } catch {
    clearLinkContinuation(ownerId)
    return null
  }
}

export function clearLinkContinuation(ownerId: string): void {
  window.sessionStorage.removeItem(storageKey(ownerId))
}
