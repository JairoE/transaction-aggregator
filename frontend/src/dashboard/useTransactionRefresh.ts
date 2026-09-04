import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/client'
import { CONNECTIONS_QUERY_KEY } from '../connections/ConnectionsPage'
import { TRANSACTION_LIMIT_ALERTS_QUERY_KEY } from '../limitations/api'
import { useOnlineStatus } from '../shell/useOnlineStatus'
import {
  createTransactionRefresh,
  fetchActiveTransactionRefresh,
  fetchTransactionRefresh,
  type TransactionRefreshResponse,
} from './transactionRefreshApi'

const DEFAULT_POLL_SCHEDULE_MS = [1_000, 2_000, 5_000, 10_000] as const
const FOREGROUND_LIMIT_MS = 90_000
const DEFAULT_JITTER = (milliseconds: number) =>
  milliseconds * (0.8 + Math.random() * 0.4)

function isActive(run: TransactionRefreshResponse | null): boolean {
  return run?.state === 'queued' || run?.state === 'running'
}

function newIdempotencyKey(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export interface UseTransactionRefreshOptions {
  ownerId: string
  onTerminal?: () => void
  pollScheduleMs?: readonly number[]
  foregroundLimitMs?: number
  jitter?: (milliseconds: number) => number
}

export interface UseTransactionRefreshResult {
  run: TransactionRefreshResponse | null
  start(): void
  isStarting: boolean
  isActive: boolean
  foregroundTimedOut: boolean
  announcement: string
  error: Error | null
}

export function useTransactionRefresh({
  ownerId,
  onTerminal,
  pollScheduleMs = DEFAULT_POLL_SCHEDULE_MS,
  foregroundLimitMs = FOREGROUND_LIMIT_MS,
  jitter = DEFAULT_JITTER,
}: UseTransactionRefreshOptions): UseTransactionRefreshResult {
  const queryClient = useQueryClient()
  const online = useOnlineStatus()
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden')
  const [run, setRun] = useState<TransactionRefreshResponse | null>(null)
  const [foregroundTimedOut, setForegroundTimedOut] = useState(false)
  const idempotencyKeyRef = useRef<string | null>(null)
  const startingRef = useRef(false)
  const pollStepRef = useRef(0)
  const pollingStartedAtRef = useRef(0)
  const completedRunsRef = useRef(new Set<string>())
  const knownRunRef = useRef<TransactionRefreshResponse | null>(null)

  const activeQuery = useQuery({
    queryKey: ['transaction-refresh', 'active', ownerId] as const,
    queryFn: fetchActiveTransactionRefresh,
    enabled: online,
    staleTime: 0,
    refetchOnWindowFocus: false,
  })

  useEffect(() => {
    if (activeQuery.data && !knownRunRef.current) setRun(activeQuery.data)
  }, [activeQuery.data])

  useEffect(() => {
    knownRunRef.current = run
    if (run && isActive(run) && pollingStartedAtRef.current === 0) {
      pollingStartedAtRef.current = Date.now()
      pollStepRef.current = 0
      setForegroundTimedOut(false)
    }
  }, [run])

  const mutation = useMutation({
    mutationFn: createTransactionRefresh,
    onSuccess: ({ refresh }) => {
      idempotencyKeyRef.current = null
      pollingStartedAtRef.current = Date.now()
      pollStepRef.current = 0
      setForegroundTimedOut(false)
      setRun(refresh)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
        idempotencyKeyRef.current = null
      }
    },
    onSettled: () => {
      startingRef.current = false
    },
  })

  const start = useCallback(() => {
    if (startingRef.current || isActive(knownRunRef.current) || !online) return
    startingRef.current = true
    idempotencyKeyRef.current ??= newIdempotencyKey()
    mutation.mutate(idempotencyKeyRef.current)
  }, [mutation, online])

  useEffect(() => {
    if (!run || !isActive(run) || !online || !visible || foregroundTimedOut) return
    const startedAt = pollingStartedAtRef.current || Date.now()
    pollingStartedAtRef.current = startedAt
    const remaining = foregroundLimitMs - (Date.now() - startedAt)
    if (remaining <= 0) {
      setForegroundTimedOut(true)
      return
    }
    const baseDelay = pollScheduleMs[
      Math.min(pollStepRef.current, pollScheduleMs.length - 1)
    ] ?? 10_000
    const delay = Math.min(Math.max(0, jitter(baseDelay)), remaining)
    let cancelled = false
    const timer = window.setTimeout(async () => {
      if (Date.now() - startedAt >= foregroundLimitMs) {
        if (!cancelled) setForegroundTimedOut(true)
        return
      }
      try {
        const refreshed = await fetchTransactionRefresh(run.id)
        if (!cancelled) {
          pollStepRef.current += 1
          setRun(refreshed)
        }
      } catch {
        if (!cancelled) {
          pollStepRef.current += 1
          setRun((current) => current && { ...current })
        }
      }
    }, delay)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [foregroundLimitMs, foregroundTimedOut, jitter, online, pollScheduleMs, run, visible])

  useEffect(() => {
    const handleVisibility = () => setVisible(document.visibilityState !== 'hidden')
    const recover = () => {
      const known = knownRunRef.current
      if (!online) return
      if (known && isActive(known)) {
        pollingStartedAtRef.current = Date.now()
        setForegroundTimedOut(false)
        void fetchTransactionRefresh(known.id).then(setRun).catch(() => undefined)
      } else {
        void activeQuery.refetch()
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)
    window.addEventListener('focus', recover)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      window.removeEventListener('focus', recover)
    }
  }, [activeQuery, online])

  useEffect(() => {
    if (!online) return
    const known = knownRunRef.current
    if (known && isActive(known)) {
      pollingStartedAtRef.current = Date.now()
      setForegroundTimedOut(false)
      void fetchTransactionRefresh(known.id).then(setRun).catch(() => undefined)
    }
  }, [online])

  useEffect(() => {
    if (!run || isActive(run) || completedRunsRef.current.has(run.id)) return
    completedRunsRef.current.add(run.id)
    onTerminal?.()
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ['transactions', 'search', ownerId] }),
      queryClient.invalidateQueries({ queryKey: ['transactions', 'all', ownerId] }),
      queryClient.invalidateQueries({ queryKey: CONNECTIONS_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: TRANSACTION_LIMIT_ALERTS_QUERY_KEY }),
    ])
  }, [onTerminal, ownerId, queryClient, run])

  const announcement = useMemo(() => {
    if (!run) return ''
    if (foregroundTimedOut) return 'The transaction check is still running in the background.'
    if (isActive(run)) {
      return `Checking for new transactions. ${run.summary.completed} of ${run.summary.total} connections complete.`
    }
    return `Transaction check complete. ${run.summary.added + run.summary.modified} updates found.`
  }, [foregroundTimedOut, run])

  return {
    run,
    start,
    isStarting: mutation.isPending,
    isActive: isActive(run),
    foregroundTimedOut,
    announcement,
    error: mutation.error instanceof Error ? mutation.error : null,
  }
}
