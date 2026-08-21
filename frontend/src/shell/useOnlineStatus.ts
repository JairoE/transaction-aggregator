import { useEffect, useState } from 'react'

/**
 * Live `navigator.onLine` state, kept in sync via the `online`/`offline`
 * window events rather than read once. Shared by the dashboard (to gate the
 * search query and label cached results) and every bank-connection action
 * (Sync/Connect/Reconnect/Disconnect all require the backend), so a single
 * hook is the one source of truth for "can we reach our own server right
 * now" instead of each screen guessing independently.
 */
export function useOnlineStatus(): boolean {
  const [isOnline, setIsOnline] = useState(
    () => typeof navigator === 'undefined' || navigator.onLine,
  )

  useEffect(() => {
    function handleOnline() {
      setIsOnline(true)
    }
    function handleOffline() {
      setIsOnline(false)
    }
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  return isOnline
}
