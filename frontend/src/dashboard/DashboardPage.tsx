import { useEffect, useMemo, useRef, useState } from 'react'
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { connectionsQueryOptions } from '../connections/ConnectionsPage'
import { AppShell } from '../shell/AppShell'
import { DotIcon } from '../shell/icons'
import { useOnlineStatus } from '../shell/useOnlineStatus'
import { fetchTransactionLimitAlerts, TRANSACTION_LIMIT_ALERTS_QUERY_KEY } from '../limitations/api'
import { AllTransactionsTable } from './AllTransactionsTable'
import {
  persistAllTransactionsResult,
  readPersistedAllTransactionsResult,
} from './allTransactionsCache'
import {
  fetchAllTransactions,
  fetchCardTransactions,
  fetchTransactionSearch,
  type AllTransactionRow,
} from './api'
import { CacheStatusBanner } from './CacheStatusBanner'
import { CardGrid, type DashboardCardGroup } from './CardGrid'
import { DashboardViewToggle, type DashboardView } from './DashboardViewToggle'
import { buildFleetSummary, buildResultsSummary, formatSyncStatus } from './format'
import { persistSearchResult, readPersistedSearchResult } from './searchCache'
import { recordSearchHistory } from './searchHistory'
import { SearchBar } from './SearchBar'
import { SearchQueryProvider } from './SearchContext'

interface CardPageState {
  extraTransactions: DashboardCardGroup['transactions']
  cursor: string | null
  hasMore: boolean
}

interface AggregatePageState {
  query: string
  rows: AllTransactionRow[]
  cursor: string | null
  hasMore: boolean
}

interface CardLoadMoreVariables {
  cardId: string
  query: string
  generation: number
}

interface AggregateLoadMoreVariables {
  query: string
  cursor: string
  generation: number
}

function resolveView(value: string | null): DashboardView {
  return value === 'transactions' ? 'transactions' : 'cards'
}

function uniqueRows(rows: AllTransactionRow[]): AllTransactionRow[] {
  const ids = new Set<string>()
  return rows.filter((row) => {
    if (ids.has(row.transaction.id)) return false
    ids.add(row.transaction.id)
    return true
  })
}

export function DashboardPage() {
  const { owner } = useAuth()
  const isOnline = useOnlineStatus()
  const [searchParams, setSearchParams] = useSearchParams()
  const submittedQuery = searchParams.get('q')?.trim() ?? ''
  const view = resolveView(searchParams.get('view'))
  const [pageState, setPageState] = useState<Record<string, CardPageState>>({})
  const [aggregatePage, setAggregatePage] = useState<AggregatePageState | null>(null)
  const continuationScopeKey = `${view}\u0000${submittedQuery}`
  const continuationScopeRef = useRef({ key: continuationScopeKey, generation: 0 })
  if (continuationScopeRef.current.key !== continuationScopeKey) {
    continuationScopeRef.current = {
      key: continuationScopeKey,
      generation: continuationScopeRef.current.generation + 1,
    }
  }
  const continuationGeneration = continuationScopeRef.current.generation

  const connectionsQuery = useQuery(connectionsQueryOptions)
  const searchQuery = useQuery({
    queryKey: ['transactions', 'search', owner?.id ?? null, submittedQuery] as const,
    queryFn: () => fetchTransactionSearch(submittedQuery),
    placeholderData: keepPreviousData,
    enabled: isOnline && view === 'cards',
    initialData: () =>
      owner ? readPersistedSearchResult(owner.id, submittedQuery)?.data : undefined,
    initialDataUpdatedAt: () =>
      owner ? readPersistedSearchResult(owner.id, submittedQuery)?.cachedAt : undefined,
  })
  const allTransactionsQuery = useQuery({
    queryKey: ['transactions', 'all', owner?.id ?? null, submittedQuery] as const,
    queryFn: () => fetchAllTransactions(submittedQuery, null),
    enabled: isOnline && view === 'transactions',
    initialData: () =>
      owner ? readPersistedAllTransactionsResult(owner.id, submittedQuery)?.data : undefined,
    initialDataUpdatedAt: () =>
      owner ? readPersistedAllTransactionsResult(owner.id, submittedQuery)?.cachedAt : undefined,
  })
  const limitationAlertsQuery = useQuery({
    queryKey: TRANSACTION_LIMIT_ALERTS_QUERY_KEY,
    queryFn: fetchTransactionLimitAlerts,
    enabled: view === 'cards',
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    refetchIntervalInBackground: false,
  })

  useEffect(() => {
    if (owner && searchQuery.isSuccess && searchQuery.data) {
      persistSearchResult(owner.id, submittedQuery, searchQuery.data)
    }
  }, [owner, searchQuery.isSuccess, searchQuery.data, submittedQuery])

  // Submitted query and view both delimit a pagination sequence. Clearing this
  // state prevents a late or old continuation page from crossing that boundary.
  useEffect(() => {
    setPageState({})
    setAggregatePage(null)
  }, [submittedQuery, view])

  const loadMoreMutation = useMutation({
    mutationFn: async ({ cardId, query, generation }: CardLoadMoreVariables) => {
      const baseGroup = searchQuery.data?.groups.find((group) => group.card.id === cardId)
      const cursor = pageState[cardId]?.cursor ?? baseGroup?.next_cursor ?? null
      return {
        cardId,
        query,
        generation,
        group: await fetchCardTransactions(cardId, query, cursor),
      }
    },
    onSuccess: ({ cardId, query, generation, group }) => {
      if (query !== submittedQuery || view !== 'cards' || generation !== continuationGeneration) return
      setPageState((previous) => ({
        ...previous,
        [cardId]: {
          extraTransactions: [...(previous[cardId]?.extraTransactions ?? []), ...group.transactions],
          cursor: group.next_cursor,
          hasMore: group.has_more,
        },
      }))
    },
  })
  const aggregateMoreMutation = useMutation({
    mutationFn: ({ query, cursor }: AggregateLoadMoreVariables) =>
      fetchAllTransactions(query, cursor),
    onSuccess: (page, variables) => {
      if (
        variables.query !== submittedQuery ||
        view !== 'transactions' ||
        variables.generation !== continuationGeneration
      ) return
      setAggregatePage((previous) => {
        const baseRows = allTransactionsQuery.data?.rows ?? []
        const previousRows = previous?.query === variables.query ? previous.rows : []
        const allRows = uniqueRows([...baseRows, ...previousRows, ...page.rows])
        return {
          query: variables.query,
          rows: allRows.filter(
            (row) => !baseRows.some((base) => base.transaction.id === row.transaction.id),
          ),
          cursor: page.next_cursor,
          hasMore: page.has_more,
        }
      })
    },
  })

  useEffect(() => {
    aggregateMoreMutation.reset()
  }, [submittedQuery, view])

  const pendingCardId = loadMoreMutation.isPending ? (loadMoreMutation.variables?.cardId ?? null) : null
  const groups = useMemo<DashboardCardGroup[]>(
    () =>
      (searchQuery.data?.groups ?? []).map((group) => {
        const extra = pageState[group.card.id]
        const merged = extra
          ? {
              ...group,
              transactions: [...group.transactions, ...extra.extraTransactions],
              next_cursor: extra.cursor,
              has_more: extra.hasMore,
            }
          : group
        return {
          ...merged,
          isLoadingMore: pendingCardId === group.card.id,
          limitationAlerts: (limitationAlertsQuery.data?.alerts ?? []).filter(
            (alert) => alert.card.id === group.card.id,
          ),
        }
      }),
    [searchQuery.data, pageState, pendingCardId, limitationAlertsQuery.data],
  )

  const aggregateData = useMemo(() => {
    const base = allTransactionsQuery.data
    if (!base || !aggregatePage || aggregatePage.query !== submittedQuery) return base
    return {
      ...base,
      rows: uniqueRows([...base.rows, ...aggregatePage.rows]),
      next_cursor: aggregatePage.cursor,
      has_more: aggregatePage.hasMore,
    }
  }, [allTransactionsQuery.data, aggregatePage, submittedQuery])

  useEffect(() => {
    if (owner && allTransactionsQuery.isSuccess && aggregateData) {
      persistAllTransactionsResult(owner.id, submittedQuery, aggregateData)
    }
  }, [owner, allTransactionsQuery.isSuccess, aggregateData, submittedQuery])

  const activeData = view === 'cards' ? searchQuery.data : aggregateData
  const cardCount = activeData?.card_count ?? 0
  const bankCount =
    view === 'cards'
      ? new Set((searchQuery.data?.groups ?? []).map((group) => group.card.bank)).size
      : (aggregateData?.bank_count ?? 0)
  const hasQuery = submittedQuery.length > 0
  const activeIsFetching = view === 'cards' ? searchQuery.isFetching : allTransactionsQuery.isFetching
  const statusPillText = formatSyncStatus(activeData?.cache_as_of ?? null)

  function handleSearchSubmit(query: string) {
    if (owner) recordSearchHistory(owner.id, query)
    const next = new URLSearchParams(searchParams)
    if (query) next.set('q', query)
    else next.delete('q')
    setSearchParams(next, { replace: true })
  }

  function handleViewChange(nextView: DashboardView) {
    const next = new URLSearchParams(searchParams)
    if (nextView === 'transactions') next.set('view', 'transactions')
    else next.delete('view')
    setSearchParams(next)
  }

  if (!owner) return null

  return (
    <AppShell
      currentStep={3}
      statusPillText={statusPillText}
      actionLink={{ label: 'Manage connections', to: '/connections' }}
    >
      <main className="dashboard-page">
        <div className="dashboard-page__view-row">
          <p className="eyebrow">{buildFleetSummary(cardCount, bankCount)}</p>
          <DashboardViewToggle view={view} onChange={handleViewChange} />
        </div>
        <h1>
          {hasQuery
            ? 'Search results'
            : view === 'transactions'
              ? 'All transactions'
              : 'Your credit cards'}
        </h1>
        <p>
          {hasQuery
            ? view === 'transactions'
              ? 'Every matching transaction is combined in one table.'
              : 'Every matching transaction remains grouped by card.'
            : view === 'transactions'
              ? 'Review cached transactions across every connected card.'
              : 'All connected cards are loaded and ready to search.'}
        </p>

        <SearchBar
          initialQuery={submittedQuery}
          pending={activeIsFetching}
          onSubmit={handleSearchSubmit}
        />

        <CacheStatusBanner
          banks={connectionsQuery.data?.banks ?? []}
          cacheAsOf={activeData?.cache_as_of ?? null}
          isOnline={isOnline}
        />

        {view === 'cards' && limitationAlertsQuery.isError && (
          <p
            className="dashboard-page__alert-status"
            role="status"
            aria-label="Transaction limit alerts"
          >
            Transaction limit alerts are temporarily unavailable. Your cards and transactions
            are still available.
          </p>
        )}

        <div className="dashboard-page__meta">
          <p className="dashboard-page__meta-text">
            <DotIcon />
            {hasQuery
              ? buildResultsSummary(submittedQuery, activeData?.total_matches ?? 0, cardCount)
              : view === 'transactions'
                ? 'Showing recent cached transactions across all cards'
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

        {view === 'cards' ? (
          searchQuery.isPending ? (
            <p role="status">Loading your cards…</p>
          ) : searchQuery.isError ? (
            <p role="alert">We could not load your cards. Try again.</p>
          ) : (
            <SearchQueryProvider value={submittedQuery}>
              <CardGrid
                groups={groups}
                onLoadMore={(cardId) =>
                  loadMoreMutation.mutate({
                    cardId,
                    query: submittedQuery,
                    generation: continuationGeneration,
                  })
                }
              />
            </SearchQueryProvider>
          )
        ) : allTransactionsQuery.isPending && !aggregateData ? (
          <p role="status">Loading transactions…</p>
        ) : (
          <AllTransactionsTable
            query={submittedQuery}
            rows={aggregateData?.rows ?? []}
            cardCount={cardCount}
            hasMore={aggregateData?.has_more ?? false}
            isLoadingMore={aggregateMoreMutation.isPending}
            continuationError={aggregateMoreMutation.isError}
            initialError={allTransactionsQuery.isError && !aggregateData}
            canRetryInitial={isOnline}
            onRetryInitial={() => {
              if (isOnline) void allTransactionsQuery.refetch()
            }}
            onLoadMore={() => {
              const cursor = aggregateData?.next_cursor
              if (cursor && !aggregateMoreMutation.isPending) {
                aggregateMoreMutation.mutate({
                  query: submittedQuery,
                  cursor,
                  generation: continuationGeneration,
                })
              }
            }}
          />
        )}
      </main>
    </AppShell>
  )
}
