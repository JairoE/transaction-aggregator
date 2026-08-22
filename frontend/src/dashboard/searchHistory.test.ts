import { describe, expect, it, vi } from 'vitest'
import { readSearchHistory, recordSearchHistory } from './searchHistory'

const WEEK_MS = 7 * 24 * 60 * 60 * 1000

describe('search history persistence', () => {
  it('keeps distinct phrases newest-first and refreshes a repeated phrase', () => {
    recordSearchHistory('owner-1', 'Paze', 1_000)
    recordSearchHistory('owner-1', 'groceries', 2_000)
    recordSearchHistory('owner-1', '  paze  ', 3_000)

    expect(readSearchHistory('owner-1', 3_000)).toEqual([
      { query: 'paze', searchedAt: 3_000 },
      { query: 'groceries', searchedAt: 2_000 },
    ])
  })

  it('prunes phrases once they are seven days old', () => {
    const now = 10 * WEEK_MS
    recordSearchHistory('owner-1', 'expired', now - WEEK_MS)
    recordSearchHistory('owner-1', 'still recent', now - WEEK_MS + 1)

    expect(readSearchHistory('owner-1', now)).toEqual([
      { query: 'still recent', searchedAt: now - WEEK_MS + 1 },
    ])
    expect(window.localStorage.getItem('ta:search-history:owner-1')).not.toContain('expired')
  })

  it('keeps each owner history isolated', () => {
    recordSearchHistory('owner-1', 'coffee', 1_000)
    recordSearchHistory('owner-2', 'airfare', 2_000)

    expect(readSearchHistory('owner-1', 2_000)).toEqual([
      { query: 'coffee', searchedAt: 1_000 },
    ])
    expect(readSearchHistory('owner-2', 2_000)).toEqual([
      { query: 'airfare', searchedAt: 2_000 },
    ])
  })

  it('returns an empty history when browser storage is unavailable', () => {
    const storageError = new DOMException('Storage is disabled', 'SecurityError')
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw storageError
    })
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw storageError
    })

    let history: ReturnType<typeof readSearchHistory> | undefined
    expect(() => {
      history = readSearchHistory('owner-1')
    }).not.toThrow()
    expect(history).toEqual([])

    getItem.mockRestore()
    removeItem.mockRestore()
  })
})
