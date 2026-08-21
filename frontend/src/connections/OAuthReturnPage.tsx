import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ApiError, apiClient } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { CONNECTIONS_QUERY_KEY } from './ConnectionsPage'
import { clearLinkContinuation, readLinkContinuation } from './linkContinuation'
import { PlaidLinkLauncher } from './PlaidLinkLauncher'

const GENERIC_ERROR_MESSAGE = 'Something went wrong. Try again.'

/**
 * Landing point for the registered OAuth redirect URI. Reinitializes
 * `react-plaid-link` with the same Link token that was in flight before the
 * bank's OAuth step navigated away, using the current URL as
 * `receivedRedirectUri`. An absent or expired continuation returns to the
 * connections page without ever calling the exchange endpoint.
 */
export function OAuthReturnPage() {
  const { owner } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const handledRef = useRef(false)
  const [continuation] = useState(() => (owner ? readLinkContinuation(owner.id) : null))

  useEffect(() => {
    if (!owner || !continuation) {
      navigate('/connections', { replace: true })
    }
  }, [owner, continuation, navigate])

  if (!owner || !continuation) {
    return null
  }

  function finishWithExchange(publicToken: string, institutionId: string, institutionName: string) {
    if (handledRef.current || !continuation) {
      return
    }
    handledRef.current = true
    clearLinkContinuation(owner!.id)
    void (async () => {
      try {
        await apiClient.request('/api/connections/exchange', {
          method: 'POST',
          body: JSON.stringify({
            bank: continuation.bank,
            public_token: publicToken,
            institution_id: institutionId,
            institution_name: institutionName,
          }),
        })
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : GENERIC_ERROR_MESSAGE)
      } finally {
        void queryClient.invalidateQueries({ queryKey: CONNECTIONS_QUERY_KEY })
        navigate('/connections', { replace: true })
      }
    })()
  }

  function handleExit() {
    if (handledRef.current) {
      return
    }
    handledRef.current = true
    clearLinkContinuation(owner!.id)
    navigate('/connections', { replace: true })
  }

  return (
    <main className="oauth-return-page">
      <p role="status">Finishing your bank connection…</p>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      <PlaidLinkLauncher
        linkToken={continuation.linkToken}
        receivedRedirectUri={window.location.href}
        onSuccess={finishWithExchange}
        onExit={handleExit}
      />
    </main>
  )
}
