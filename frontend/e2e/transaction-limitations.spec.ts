import { expect, test, type Page } from '@playwright/test'

const OWNER_EMAIL = 'e2e-owner@example.com'
const OWNER_PASSWORD = 'end-to-end-password-2026'

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Email').fill(OWNER_EMAIL)
  await page.getByLabel('Password').fill(OWNER_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Connect your credit cards' })).toBeVisible()
}

async function connectAll(page: Page): Promise<void> {
  for (const bank of ['Capital One', 'Chase', 'Citi', 'Wells Fargo']) {
    const connect = page.getByRole('button', { name: `Connect ${bank}` })
    if ((await connect.count()) === 0) continue
    await connect.click()
    await page.getByRole('button', { name: /Approve & return/ }).click()
    await expect(page.getByRole('heading', { name: `Continue to ${bank}` })).toBeHidden()
  }
  await expect
    .poll(async () => {
      const response = await page.request.get('/api/connections')
      const data = (await response.json()) as { banks: Array<{ state: string }> }
      return data.banks.every((bank) => bank.state === 'ready')
    })
    .toBe(true)
}

test('owner creates and disables a dashboard transaction alert', async ({ page }) => {
  await signIn(page)
  await connectAll(page)
  await page.goto('/transaction-limitations')

  await page.getByLabel(/keyword or phrase/i).fill('Urban Market')
  await page.getByLabel(/transaction threshold/i).fill('1')
  await page.getByRole('radio', { name: /all cards/i }).check()
  await page.getByRole('button', { name: /save rule/i }).click()
  await expect(page.getByRole('heading', { name: 'Urban Market' }).last()).toBeVisible()

  await page.getByRole('link', { name: 'View cards', exact: true }).click()
  const card = page.getByRole('region', { name: /ending in 4812/i })
  await expect(card.getByRole('alert')).toContainText('Urban Market')
  await expect(card.getByRole('alert')).toContainText('0 pending')

  await page.getByRole('link', { name: /alerts & limits/i }).click()
  const rule = page.locator('.limitation-rule').filter({ hasText: 'Urban Market' }).last()
  await rule.getByRole('button', { name: 'Disable' }).click()
  await expect(rule.getByText('Disabled')).toBeVisible()

  await page.getByRole('link', { name: 'View cards', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Urban Market' })).toHaveCount(0)
})
