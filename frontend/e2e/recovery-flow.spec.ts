import { expect, test, type Page } from '@playwright/test'

const OWNER_EMAIL = 'e2e-owner@example.com'
const OWNER_PASSWORD = 'end-to-end-password-2026'

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
  const email = page.getByLabel('Email')
  if ((await email.count()) > 0) {
    await email.fill(OWNER_EMAIL)
    await page.getByLabel('Password').fill(OWNER_PASSWORD)
    await page.getByRole('button', { name: 'Sign in' }).click()
  }
  await expect(
    page.getByRole('heading', { name: 'Connect your credit cards' }),
  ).toBeVisible()
}

async function connectAll(page: Page): Promise<void> {
  for (const bank of ['Capital One', 'Chase', 'Citi', 'Wells Fargo']) {
    const connect = page.getByRole('button', { name: `Connect ${bank}` })
    if ((await connect.count()) === 0) continue
    await connect.click()
    await page.getByRole('button', { name: /Approve & return/ }).click()
    await expect(
      page.getByRole('heading', { name: `Continue to ${bank}` }),
    ).toBeHidden()
  }
  await expect(page.getByText('4 of 4 connected')).toBeVisible()
  await expect
    .poll(async () => {
      const response = await page.request.get('/api/connections')
      const data = (await response.json()) as { banks: Array<{ state: string }> }
      return data.banks.every((bank) => bank.state === 'ready')
    })
    .toBe(true)
}

test('one failing bank never hides the healthy banks', async ({ page }) => {
  await signIn(page)
  await connectAll(page)
  await page.goto('/dashboard')
  await expect(page.getByRole('searchbox')).toBeVisible()

  // Fail only Citi's connection responses; every other call goes through.
  await page.route('**/api/connections', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    for (const bank of body.banks) {
      if (bank.bank === 'citi') {
        bank.state = 'needs_reconnect'
        bank.action = 'reconnect'
        bank.last_error_code = 'ITEM_LOGIN_REQUIRED'
        bank.message = 'This bank needs you to sign in again to keep syncing.'
      }
    }
    await route.fulfill({ response, json: body })
  })

  await page.goto('/connections')
  await expect(page.getByText(/needs you to sign in again/i)).toBeVisible()

  // Cached search across every card still works while one bank is broken.
  await page.goto('/dashboard')
  await page.getByRole('searchbox').fill('Paze')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page.getByText('10 matches for “Paze” across 8 cards')).toBeVisible()
})

test('cached search keeps working with the network offline', async ({ page, context }) => {
  await signIn(page)
  await connectAll(page)
  await page.goto('/dashboard')
  await page.getByRole('searchbox').fill('Paze')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page.getByText('10 matches for “Paze” across 8 cards')).toBeVisible()

  await context.setOffline(true)
  await page.evaluate(() => window.dispatchEvent(new Event('offline')))

  // The already-loaded results stay on screen rather than blanking out.
  await expect(page.getByText(/Paze · Urban Market/)).toBeVisible()
  await expect(page.getByText(/offline/i).first()).toBeVisible()

  await context.setOffline(false)
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
})

test('a provider outage leaves cached transactions searchable', async ({ page }) => {
  await signIn(page)
  await connectAll(page)

  // Plaid-facing writes fail; local reads are untouched.
  await page.route('**/api/connections/*/sync', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 'INSTITUTION_DOWN',
        message: 'This bank is temporarily unavailable.',
      }),
    }),
  )

  await page.goto('/dashboard')
  await page.getByRole('searchbox').fill('Paze')
  await page.getByRole('button', { name: 'Search', exact: true }).click()

  await expect(page.getByText('10 matches for “Paze” across 8 cards')).toBeVisible()
  await expect(page.getByRole('searchbox')).toBeEnabled()
})
