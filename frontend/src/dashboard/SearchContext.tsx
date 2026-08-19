import { createContext, useContext } from 'react'

/**
 * The currently *submitted* search term, threaded to `CardPanel` and
 * `TransactionList` without widening their pinned prop signatures
 * (`{ group, onLoadMore }` / `{ transactions, height }`). Both need the term
 * — to choose the category-vs-original-description line and to highlight
 * matches — so a small context avoids duplicating it as a prop on every
 * intermediate component.
 */
const SearchQueryContext = createContext<string>('')

export const SearchQueryProvider = SearchQueryContext.Provider

export function useSearchQuery(): string {
  return useContext(SearchQueryContext)
}
