import { useCallback, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../api/client'
import type { components } from '../api/generated'
import { AppShell } from '../shell/AppShell'
import { useAuth } from '../auth/AuthProvider'
import { BankConnectionCard } from './BankConnectionCard'

type ConnectionsResponse = components['schemas']['ConnectionsResponse']

export const CONNECTIONS_QUERY_KEY = ['connections'] as const

export function ConnectionsPage() {
  const { owner } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [announcement, setAnnouncement] = useState('')

  const connectionsQuery = useQuery({
    queryKey: CONNECTIONS_QUERY_KEY,
    queryFn: () => apiClient.request<ConnectionsResponse>('/api/connections'),
  })

  const handleChanged = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: CONNECTIONS_QUERY_KEY })
  }, [queryClient])

  if (!owner) {
    return null
  }

  if (connectionsQuery.isPending) {
    return (
      <AppShell currentStep={2} statusPillText="Loading…">
        <main className="connections-page">
          <p>Loading your connections…</p>
        </main>
      </AppShell>
    )
  }

  if (connectionsQuery.isError) {
    return (
      <AppShell currentStep={2} statusPillText="Owner access">
        <main className="connections-page">
          <p role="alert">We could not load your bank connections. Try again.</p>
        </main>
      </AppShell>
    )
  }

  const data = connectionsQuery.data
  const connectedCount = data.banks.filter((bank) => bank.connected).length
  const allConnected = connectedCount === data.banks.length && data.banks.length > 0

  return (
    <AppShell
      currentStep={2}
      statusPillText={`${connectedCount} of ${data.banks.length} connected`}
    >
      <main className="connections-page">
        <p className="eyebrow">Secure bank connections</p>
        <h1>Connect your credit cards</h1>
        <p>
          Each sign-in opens a bank-hosted OAuth flow. Select every card you want to
          search.
        </p>
        <div aria-live="polite" role="status" className="sr-only">
          {announcement}
        </div>
        <div className="bank-grid">
          {data.banks.map((bank) => (
            <BankConnectionCard
              key={bank.bank}
              bank={bank}
              ownerId={owner.id}
              usesDemoBank={data.uses_demo_bank}
              onAnnounce={setAnnouncement}
              onChanged={handleChanged}
            />
          ))}
        </div>
        {allConnected && (
          <button
            type="button"
            className="primary-button"
            onClick={() => navigate('/dashboard')}
          >
            View dashboard
          </button>
        )}
      </main>
    </AppShell>
  )
}
