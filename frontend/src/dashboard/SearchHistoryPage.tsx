import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { AppShell } from '../shell/AppShell'
import { SearchIcon } from '../shell/icons'
import { readSearchHistory } from './searchHistory'

const timestampFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

export function SearchHistoryPage() {
  const { owner } = useAuth()

  if (!owner) {
    return null
  }

  const entries = readSearchHistory(owner.id)

  return (
    <AppShell
      currentStep={3}
      statusPillText="7-day history"
      actionLink={{ label: 'Search transactions', to: '/dashboard' }}
    >
      <main className="search-history-page">
        <p className="eyebrow">Recent searches</p>
        <h1>Search history</h1>
        <p>
          Search phrases are stored in this browser for seven days. Transaction results are never
          saved here.
        </p>

        {entries.length === 0 ? (
          <section className="search-history-empty" aria-labelledby="empty-history-title">
            <SearchIcon />
            <h2 id="empty-history-title">No searches yet</h2>
            <p>Your submitted transaction searches will appear here.</p>
            <Link className="primary-button" to="/dashboard">
              Search transactions
            </Link>
          </section>
        ) : (
          <ol className="search-history-list" aria-label="Searches from the last seven days">
            {entries.map((entry) => (
              <li key={`${entry.query}:${entry.searchedAt}`}>
                <Link
                  className="search-history-entry"
                  to={`/dashboard?q=${encodeURIComponent(entry.query)}`}
                >
                  <span className="search-history-entry__icon" aria-hidden="true">
                    <SearchIcon />
                  </span>
                  <span className="search-history-entry__copy">
                    <strong>{entry.query}</strong>
                    <time dateTime={new Date(entry.searchedAt).toISOString()}>
                      {timestampFormatter.format(entry.searchedAt)}
                    </time>
                  </span>
                  <span className="search-history-entry__action" aria-hidden="true">
                    Search again
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        )}
      </main>
    </AppShell>
  )
}
