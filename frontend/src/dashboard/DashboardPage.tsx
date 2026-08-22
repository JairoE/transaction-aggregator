import { useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { apiClient } from '../api/client'
import type { components } from '../api/generated'
import { useAuth } from '../auth/AuthProvider'
import { CONNECTIONS_QUERY_KEY } from '../connections/ConnectionsPage'
import { AppShell } from '../shell/AppShell'
import { DotIcon } from '../shell/icons'
import { useOnlineStatus } from '../shell/useOnlineStatus'
import { CacheStatusBanner } from './CacheStatusBanner'
import { CardGrid, type DashboardCardGroup } from './CardGrid'
import { SearchBar } from './SearchBar'
import { SearchQueryProvider } from './SearchContext'
import { fetchCardTransactions, fetchTransactionSearch } from './api'
import { buildFleetSummary, buildResultsSummary, formatSyncStatus } from './format'
import { persistSearchResult, readPersistedSearchResult } from './searchCache'
import { recordSearchHistory } from './searchHistory'

type ConnectionsResponse = components['schemas']['ConnectionsResponse']

interface CardPageState {
  /** Transactions appended by "Load more" clicks, beyond the base page. */
  extraTransactions: DashboardCardGroup['transactions']
  cursor: string | null
  hasMore: boolean
}

export function DashboardPage() {
  const { owner } = useAuth()
  const isOnline = useOnlineStatus()
  const [searchParams, setSearchParams] = useSearchParams()
  const submittedQuery = searchParams.get('q')?.trim() ?? ''
  const [pageState, setPageState] = useState<Record<string, CardPageState>>({})

  // Connection health for `CacheStatusBanner`. Shares its query key with
  // `ConnectionsPage` so navigating between the two screens doesn't
  // duplicate the request.
  const connectionsQuery = useQuery({
    queryKey: CONNECTIONS_QUERY_KEY,
    queryFn: () => apiClient.request<ConnectionsResponse>('/api/connections'),
  })

  const searchQuery = useQuery({
    queryKey: ['transactions', 'search', submittedQuery] as const,
    queryFn: () => fetchTransactionSearch(submittedQuery),
    placeholderData: keepPreviousData,
    // Offline: don't attempt a doomed fetch — fall back to whatever is
    // already cached (in memory, or hydrated below from sessionStorage)
    // and let the `online` event re-enable fetching automatically.
    enabled: isOnline,
    initialData: () =>
      owner ? readPersistedSearchResult(owner.id, submittedQuery)?.data : undefined,
    initialDataUpdatedAt: () =>
      owner ? readPersistedSearchResult(owner.id, submittedQuery)?.cachedAt : undefined,
  })

  // Persist every successful search result to sessionStorage (see
  // `./searchCache.ts`) so a reload — or simply going offline — still has
  // last-known-good rows to show instead of a blank/loading dashboard.
  useEffect(() => {
    if (owner && searchQuery.isSuccess && searchQuery.data) {
      persistSearchResult(owner.id, submittedQuery, searchQuery.data)
    }
  }, [owner, searchQuery.isSuccess, searchQuery.data, submittedQuery])

  // A newly submitted search — including an empty one that restores recent
  // cached transactions — resets every card's pagination state so no stale
  // cursor or appended page survives the resubmission.
  useEffect(() => {
    setPageState({})
  }, [submittedQuery])

  const loadMoreMutation = useMutation({
    mutationFn: async (cardId: string) => {
      const baseGroup = searchQuery.data?.groups.find((group) => group.card.id === cardId)
      const currentCursor = pageState[cardId]?.cursor ?? baseGroup?.next_cursor ?? null
      const group = await fetchCardTransactions(cardId, submittedQuery, currentCursor)
      return { cardId, group }
    },
    onSuccess: ({ cardId, group }) => {
      setPageState((prev) => ({
        ...prev,
        [cardId]: {
          extraTransactions: [...(prev[cardId]?.extraTransactions ?? []), ...group.transactions],
          cursor: group.next_cursor,
          hasMore: group.has_more,
        },
      }))
    },
  })

  const pendingCardId = loadMoreMutation.isPending ? (loadMoreMutation.variables ?? null) : null

  const groups = useMemo<DashboardCardGroup[]>(() => {
    return (searchQuery.data?.groups ?? []).map((group) => {
      const extra = pageState[group.card.id]
      const merged = extra
        ? {
            ...group,
            transactions: [...group.transactions, ...extra.extraTransactions],
            next_cursor: extra.cursor,
            has_more: extra.hasMore,
          }
        : group
      return { ...merged, isLoadingMore: pendingCardId === group.card.id }
    })
  }, [searchQuery.data, pageState, pendingCardId])

  const cardCount = searchQuery.data?.card_count ?? 0
  const bankCount = useMemo(
    () => new Set((searchQuery.data?.groups ?? []).map((group) => group.card.bank)).size,
    [searchQuery.data],
  )
  const hasQuery = submittedQuery.trim().length > 0
  const statusPillText = formatSyncStatus(searchQuery.data?.cache_as_of ?? null)

  function handleSearchSubmit(query: string) {
    if (owner) {
      recordSearchHistory(owner.id, query)
    }
    setSearchParams(query ? { q: query } : {}, { replace: true })
  }

  if (!owner) {
    return null
  }

  return (
    <AppShell
      currentStep={3}
      statusPillText={statusPillText}
      actionLink={{ label: 'Manage connections', to: '/connections' }}
    >
      <main className="dashboard-page">
        <p className="eyebrow">{buildFleetSummary(cardCount, bankCount)}</p>
        <h1>{hasQuery ? 'Search results' : 'Your credit cards'}</h1>
        <p>
          {hasQuery
            ? 'Every matching transaction remains grouped by card.'
            : 'All connected cards are loaded and ready to search.'}
        </p>

        <SearchBar
          initialQuery={submittedQuery}
          pending={searchQuery.isFetching}
          onSubmit={handleSearchSubmit}
        />

        <CacheStatusBanner
          banks={connectionsQuery.data?.banks ?? []}
          cacheAsOf={searchQuery.data?.cache_as_of ?? null}
          isOnline={isOnline}
        />

        <div className="dashboard-page__meta">
          <p className="dashboard-page__meta-text">
            <DotIcon />
            {hasQuery
              ? buildResultsSummary(submittedQuery, searchQuery.data?.total_matches ?? 0, cardCount)
              : 'Showing recent cached transactions on every card'}
          </p>
          {hasQuery ? (
            <button
              type="button"
              className="dashboard-page__clear"
              onClick={() => handleSearchSubmit('')}
            >
              Clear search
            </button>
          ) : (
            <span className="dashboard-page__hint">Try searching for Paze</span>
          )}
        </div>

        {searchQuery.isPending ? (
          <p role="status">Loading your cards…</p>
        ) : searchQuery.isError ? (
          <p role="alert">We could not load your cards. Try again.</p>
        ) : (
          <SearchQueryProvider value={submittedQuery}>
            <CardGrid groups={groups} onLoadMore={(cardId) => loadMoreMutation.mutate(cardId)} />
          </SearchQueryProvider>
        )}
      </main>
    </AppShell>
  )
}
