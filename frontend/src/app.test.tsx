import { screen } from '@testing-library/react'
import { it, expect } from 'vitest'
import { renderAppAt } from './test/renderApp'

// Task 1's original smoke test rendered a static `<h1>Transaction
// Aggregator</h1>`. Task 7 turned `App` into a routed, session-aware shell:
// an anonymous visitor now lands on the owner sign-in view instead. The
// brand name still appears, in the app chrome shown once signed in (see
// connections.test.tsx); this test's job is just confirming the app boots
// and routes an anonymous visitor to sign-in.
it('routes an anonymous visitor to the owner sign-in form', async () => {
  renderAppAt('/')

  expect(
    await screen.findByRole('heading', { name: /find any credit-card transaction in seconds/i }),
  ).toBeInTheDocument()
})
