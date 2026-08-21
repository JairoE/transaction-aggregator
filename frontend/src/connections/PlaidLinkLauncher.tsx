import { useEffect } from 'react'
import { usePlaidLink, type PlaidLinkOnExit, type PlaidLinkOnSuccess } from 'react-plaid-link'

export interface PlaidLinkLauncherProps {
  linkToken: string
  /** Present only when reinitializing Link after an OAuth redirect. */
  receivedRedirectUri?: string
  onSuccess: (publicToken: string, institutionId: string, institutionName: string) => void
  onExit: () => void
}

/**
 * Thin wrapper around `usePlaidLink` for the real (non-demo) connection
 * path. Opens automatically once Plaid's script has loaded and the handler
 * is ready, and only ever forwards `public_token` plus institution metadata
 * to the caller — never the Link token itself.
 */
export function PlaidLinkLauncher({
  linkToken,
  receivedRedirectUri,
  onSuccess,
  onExit,
}: PlaidLinkLauncherProps) {
  const handleSuccess: PlaidLinkOnSuccess = (publicToken, metadata) => {
    if (!publicToken) {
      return
    }
    onSuccess(
      publicToken,
      metadata.institution?.institution_id ?? '',
      metadata.institution?.name ?? '',
    )
  }

  const handleExit: PlaidLinkOnExit = () => {
    onExit()
  }

  const { open, ready } = usePlaidLink({
    token: linkToken,
    receivedRedirectUri,
    onSuccess: handleSuccess,
    onExit: handleExit,
  })

  useEffect(() => {
    if (ready) {
      open()
    }
  }, [ready, open])

  return null
}
