import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import { LoginPage } from './auth/LoginPage'
import { ConnectionsPage } from './connections/ConnectionsPage'
import { OAuthReturnPage } from './connections/OAuthReturnPage'
import { DashboardPage } from './dashboard/DashboardPage'
import { AppShell } from './shell/AppShell'

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

function SignInScreen() {
  // The reference design shows the same four-step progress strip and header
  // chrome on the sign-in screen as every signed-in view: step 1 current,
  // and status text limited to "Owner access" (there's no sync/connection
  // summary to show yet).
  return (
    <AppShell currentStep={1} statusPillText="Owner access">
      <LoginPage />
    </AppShell>
  )
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<SignInScreen />} />
      <Route element={<RequireAuth />}>
        <Route path="/connections" element={<ConnectionsPage />} />
        <Route path="/oauth-return" element={<OAuthReturnPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
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
