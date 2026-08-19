import { useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthProvider'
import { AppShell } from '../shell/AppShell'
import { DotIcon } from '../shell/icons'
import { CardGrid, type DashboardCardGroup } from './CardGrid'
import { SearchBar } from './SearchBar'
import { SearchQueryProvider } from './SearchContext'
import { fetchCardTransactions, fetchTransactionSearch } from './api'
import { buildFleetSummary, buildResultsSummary, formatSyncStatus } from './format'

interface CardPageState {
  /** Transactions appended by "Load more" clicks, beyond the base page. */
  extraTransactions: DashboardCardGroup['transactions']
  cursor: string | null
  hasMore: boolean
}

export function DashboardPage() {
  const { owner } = useAuth()
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [pageState, setPageState] = useState<Record<string, CardPageState>>({})

  const searchQuery = useQuery({
    queryKey: ['transactions', 'search', submittedQuery] as const,
    queryFn: () => fetchTransactionSearch(submittedQuery),
    placeholderData: keepPreviousData,
  })

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

  if (!owner) {
    return null
  }

  return (
    <AppShell currentStep={hasQuery ? 4 : 3} statusPillText={statusPillText}>
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
          onSubmit={setSubmittedQuery}
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
              onClick={() => setSubmittedQuery('')}
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
