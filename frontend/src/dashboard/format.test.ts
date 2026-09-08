import { describe, expect, it } from 'vitest'
import { formatRelativeTimestamp } from './format'

describe('formatRelativeTimestamp', () => {
  const now = new Date('2026-09-08T14:32:00Z')

  it.each([
    ['2026-09-08T14:31:45Z', 'just now'],
    ['2026-09-08T14:30:00Z', '2 minutes ago'],
    ['2026-09-08T13:32:00Z', '1 hour ago'],
    ['2026-09-07T14:32:00Z', '1 day ago'],
    ['2026-09-01T14:32:00Z', '1 week ago'],
  ])('formats %s as %s', (timestamp, expected) => {
    expect(formatRelativeTimestamp(timestamp, now)).toBe(expected)
  })
})
