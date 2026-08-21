import { useEffect, useRef, useState, type FormEvent } from 'react'
import { SearchIcon } from '../shell/icons'

export interface SearchBarProps {
  /** The currently *submitted* query — used only to seed/resync the draft. */
  initialQuery: string
  pending: boolean
  onSubmit: (query: string) => void
}

/**
 * Owns its own draft text. Typing only ever updates local state — `onSubmit`
 * fires exclusively from the form's submit handler (Enter in the input, or
 * the Search button), which is what keeps typing from ever issuing a search
 * request. `initialQuery` re-syncs the visible text when the parent resets
 * the submitted query from elsewhere (e.g. the "Clear search" control).
 */
export function SearchBar({ initialQuery, pending, onSubmit }: SearchBarProps) {
  const [draft, setDraft] = useState(initialQuery)
  const lastSyncedQuery = useRef(initialQuery)

  useEffect(() => {
    if (initialQuery !== lastSyncedQuery.current) {
      lastSyncedQuery.current = initialQuery
      setDraft(initialQuery)
    }
  }, [initialQuery])

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSubmit(draft.trim())
  }

  return (
    <form className="search-bar" role="search" aria-label="Transaction search" onSubmit={handleSubmit}>
      <div className="search-bar__field">
        <label htmlFor="dashboard-search-input">Search every card</label>
        <input
          id="dashboard-search-input"
          type="search"
          value={draft}
          placeholder="Merchant or statement keyword"
          onChange={(event) => setDraft(event.target.value)}
        />
      </div>
      <button type="submit" className="search-bar__submit" aria-busy={pending}>
        <SearchIcon />
        <span>{pending ? 'Searching…' : 'Search'}</span>
      </button>
    </form>
  )
}
