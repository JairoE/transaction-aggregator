import { expect, test, type Page } from '@playwright/test'

const OWNER_EMAIL = 'e2e-owner@example.com'
const OWNER_PASSWORD = 'end-to-end-password-2026'

const BANKS = ['Capital One', 'Chase', 'Citi', 'Wells Fargo'] as const
const EXPECTED_MASKS = [
  '4812', '9064', '1187', '2041', '7730', '3628', '5509', '6144',
] as const

/** Fails the test if the browser reported an error at any point. */
function watchForErrors(page: Page): { assertClean: () => void } {
  const problems: string[] = []
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() !== 'error') {
      return
    }
    // The app deliberately probes /api/auth/session while signed out; the
    // browser logs that 401 even though it is the expected answer.
    if (/Failed to load resource/.test(message.text())) {
      return
    }
    problems.push(`console: ${message.text()}`)
  })
  page.on('response', (response) => {
    const url = response.url()
    if (response.status() >= 500) {
      problems.push(`server error ${response.status()}: ${url}`)
    }
    if (
      url.includes('/api/') &&
      response.status() === 401 &&
      !url.includes('/api/auth/session')
    ) {
      problems.push(`unexpected 401: ${url}`)
    }
    if (response.status() === 404) {
      problems.push(`not found: ${url}`)
    }
  })
  return {
    assertClean: () => expect(problems, problems.join('\n')).toEqual([]),
  }
}

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Email').fill(OWNER_EMAIL)
  await page.getByLabel('Password').fill(OWNER_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(
    page.getByRole('heading', { name: 'Connect your credit cards' }),
  ).toBeVisible()
}

async function connectBank(page: Page, bank: string): Promise<void> {
  const connect = page.getByRole('button', { name: `Connect ${bank}` })
  if ((await connect.count()) === 0) {
    return // already connected by an earlier project run against this server
  }
  await connect.click()
  await expect(
    page.getByRole('heading', { name: `Continue to ${bank}` }),
  ).toBeVisible()
  await page.getByRole('button', { name: /Approve & return/ }).click()
  await expect(
    page.getByRole('heading', { name: `Continue to ${bank}` }),
  ).toBeHidden()
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  )
  expect(overflow, 'page must not scroll horizontally').toBe(false)
}

test('owner connects four banks and searches every card at once', async ({ page }) => {
  const errors = watchForErrors(page)

  await signIn(page)

  for (const bank of BANKS) {
    await connectBank(page, bank)
  }
  await expect(page.getByText('4 of 4 connected')).toBeVisible()

  await page.getByRole('button', { name: 'View dashboard' }).click()
  await expect(page.getByRole('heading', { name: 'Your credit cards' })).toBeVisible()

  // Every authorized credit card gets its own panel.
  for (const mask of EXPECTED_MASKS) {
    await expect(page.getByText(`··${mask}`)).toBeVisible()
  }

  // Typing alone must not search.
  const search = page.getByRole('searchbox', { name: /Search every card/i })
  await search.fill('Paze')
  await expect(page.getByRole('heading', { name: 'Your credit cards' })).toBeVisible()

  await page.getByRole('button', { name: 'Search', exact: true }).click()

  await expect(page.getByText('10 matches for “Paze” across 8 cards')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Search results' })).toBeVisible()

  // Every card stays in the grid, each reporting its own count.
  for (const mask of EXPECTED_MASKS) {
    await expect(page.getByText(`··${mask}`)).toBeVisible()
  }
  await expect(page.getByText(/^Paze · Urban Market$/)).toBeVisible()

  await expectNoHorizontalOverflow(page)

  // A term only one card has keeps the other seven visible with zero matches.
  await search.fill('Juniper')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page.getByText('1 match for “Juniper” across 8 cards')).toBeVisible()
  await expect(page.getByText('0 matches')).toHaveCount(7)

  // Clearing restores recent cached transactions everywhere.
  await search.fill('')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your credit cards' })).toBeVisible()

  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()

  errors.assertClean()
})

test('no Plaid secret or access token reaches the browser', async ({ page }) => {
  const bodies: string[] = []
  page.on('response', async (response) => {
    if (response.request().resourceType() === 'script' || response.url().includes('/api/')) {
      try {
        bodies.push(await response.text())
      } catch {
        // streamed or empty responses are fine to skip
      }
    }
  })

  await signIn(page)
  await connectBank(page, 'Capital One')
  await page.goto('/dashboard')
  await expect(page.getByRole('searchbox')).toBeVisible()

  const combined = bodies.join('\n')
  expect(combined).not.toContain('access-demo-')
  expect(combined).not.toContain('access-sandbox-')
  expect(combined).not.toContain('access-production-')
  expect(combined).not.toMatch(/PLAID_SECRET/)
})
