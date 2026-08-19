import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import { LoginPage } from './auth/LoginPage'
import { ConnectionsPage } from './connections/ConnectionsPage'
import { OAuthReturnPage } from './connections/OAuthReturnPage'

function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })
}

function RequireAuth() {
  const { status } = useAuth()

  if (status === 'loading') {
    return (
      <p className="app-loading" role="status">
        Loading…
      </p>
    )
  }

  if (status === 'unauthenticated') {
    return <Navigate to="/" replace />
  }

  return <Outlet />
}

function DashboardPlaceholder() {
  // Task 8 replaces this with the responsive card grid and search flow.
  return <h1>Your credit cards</h1>
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/connections" element={<ConnectionsPage />} />
        <Route path="/oauth-return" element={<OAuthReturnPage />} />
        <Route path="/dashboard" element={<DashboardPlaceholder />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export function App() {
  const [queryClient] = useState(createQueryClient)

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
