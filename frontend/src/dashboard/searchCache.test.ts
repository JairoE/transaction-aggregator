import { describe, expect, it } from 'vitest'
import { pazeSearchResponse } from '../test/dashboardFixtures'
import { persistSearchResult, readPersistedSearchResult } from './searchCache'

const CACHE_KEY = 'ta:search-cache:owner-a:Paze'
const NOW = 1_000_000

describe('grouped-search session cache schema', () => {
  it('removes a pre-summary unversioned cache entry', () => {
    window.sessionStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ data: pazeSearchResponse(), cachedAt: NOW }),
    )

    expect(readPersistedSearchResult('owner-a', 'Paze', NOW)).toBeNull()
    expect(window.sessionStorage.getItem(CACHE_KEY)).toBeNull()
  })

  it('round-trips the current summary-bearing response', () => {
    const response = pazeSearchResponse()

    persistSearchResult('owner-a', 'Paze', response)

    expect(readPersistedSearchResult('owner-a', 'Paze')?.data).toEqual(response)
  })
})
