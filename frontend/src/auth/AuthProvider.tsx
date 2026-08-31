import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  type ReactNode,
} from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, apiClient, setCsrfToken } from '../api/client'
import type { components } from '../api/generated'
import { clearLinkContinuation } from '../connections/linkContinuation'
import { clearAllTransactionsCache } from '../dashboard/allTransactionsCache'
import { clearSearchCache } from '../dashboard/searchCache'
import { readSearchHistory } from '../dashboard/searchHistory'

export type SessionResponse = components['schemas']['SessionResponse']
export type Owner = components['schemas']['OwnerResponse']

export const SESSION_QUERY_KEY = ['auth', 'session'] as const

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

export interface AuthContextValue {
  owner: Owner | null
  csrfToken: string | null
  status: AuthStatus
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

async function fetchSession(): Promise<SessionResponse | null> {
  try {
    return await apiClient.request<SessionResponse>('/api/auth/session')
  } catch (error) {
    if (error instanceof ApiError && error.code === 'AUTH_REQUIRED') {
      return null
    }
    throw error
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  const sessionQuery = useQuery({
    queryKey: SESSION_QUERY_KEY,
    queryFn: fetchSession,
    retry: false,
    staleTime: 60_000,
  })

  useEffect(() => {
    setCsrfToken(sessionQuery.data?.csrf_token ?? null)
  }, [sessionQuery.data])

  useEffect(() => {
    const ownerId = sessionQuery.data?.owner.id
    if (ownerId) {
      readSearchHistory(ownerId)
    }
  }, [sessionQuery.data?.owner.id])

  useEffect(() => {
    apiClient.onAuthRequired(() => {
      queryClient.setQueryData<SessionResponse | null>(SESSION_QUERY_KEY, null)
    })
    return () => apiClient.onAuthRequired(null)
  }, [queryClient])

  const loginMutation = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      apiClient.request<SessionResponse>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
        csrf: false,
      }),
    onSuccess: (data) => {
      setCsrfToken(data.csrf_token)
      queryClient.setQueryData<SessionResponse | null>(SESSION_QUERY_KEY, data)
    },
  })

  const logoutMutation = useMutation({
    mutationFn: () => apiClient.request<void>('/api/auth/logout', { method: 'POST' }),
    onSuccess: () => {
      const ownerId = sessionQuery.data?.owner.id
      if (ownerId) {
        clearLinkContinuation(ownerId)
        clearAllTransactionsCache(ownerId)
        clearSearchCache(ownerId)
      }
      setCsrfToken(null)
      queryClient.setQueryData<SessionResponse | null>(SESSION_QUERY_KEY, null)
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'auth' })
    },
  })

  const value = useMemo<AuthContextValue>(() => {
    const status: AuthStatus = sessionQuery.isPending
      ? 'loading'
      : sessionQuery.data
        ? 'authenticated'
        : 'unauthenticated'

    return {
      owner: sessionQuery.data?.owner ?? null,
      csrfToken: sessionQuery.data?.csrf_token ?? null,
      status,
      login: async (email: string, password: string) => {
        await loginMutation.mutateAsync({ email, password })
      },
      logout: async () => {
        await logoutMutation.mutateAsync()
      },
    }
  }, [sessionQuery.isPending, sessionQuery.data, loginMutation, logoutMutation])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
