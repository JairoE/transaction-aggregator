import { expect, test, type Page } from '@playwright/test'

const OWNER_EMAIL = 'e2e-owner@example.com'
const OWNER_PASSWORD = 'end-to-end-password-2026'

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  )
  expect(hasHorizontalOverflow, 'page must not scroll horizontally').toBe(false)
}

async function expectResponsiveBreakpoints(page: Page): Promise<void> {
  const originalViewport = page.viewportSize()
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await expectNoHorizontalOverflow(page)
  }
  if (originalViewport) {
    await page.setViewportSize(originalViewport)
  }
}

async function expectMinimumTextContrast(page: Page, selector: string): Promise<void> {
  const contrast = await page.locator(selector).first().evaluate((element) => {
    type Rgba = [number, number, number, number]

    const parseColor = (value: string): Rgba => {
      const channels = value.match(/[\d.]+/g)?.map(Number) ?? []
      return [channels[0] ?? 0, channels[1] ?? 0, channels[2] ?? 0, channels[3] ?? 1]
    }
    const composite = (front: Rgba, back: Rgba): Rgba => {
      const alpha = front[3] + back[3] * (1 - front[3])
      if (alpha === 0) return [0, 0, 0, 0]
      return [
        (front[0] * front[3] + back[0] * back[3] * (1 - front[3])) / alpha,
        (front[1] * front[3] + back[1] * back[3] * (1 - front[3])) / alpha,
        (front[2] * front[3] + back[2] * back[3] * (1 - front[3])) / alpha,
        alpha,
      ]
    }
    const luminance = ([red, green, blue]: Rgba) => {
      const linear = [red, green, blue].map((channel) => {
        const value = channel / 255
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    }

    let background: Rgba = [0, 0, 0, 0]
    let current: Element | null = element
    while (current) {
      background = composite(background, parseColor(getComputedStyle(current).backgroundColor))
      current = current.parentElement
    }
    background = composite(background, [255, 255, 255, 1])
    const foreground = composite(parseColor(getComputedStyle(element).color), background)
    const foregroundLuminance = luminance(foreground)
    const backgroundLuminance = luminance(background)
    return (
      (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
      (Math.min(foregroundLuminance, backgroundLuminance) + 0.05)
    )
  })

  expect(contrast, `${selector} text contrast`).toBeGreaterThanOrEqual(4.5)
}

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

test('owner signs in, views transactions, creates and views an alert, then signs out', async ({ page }, testInfo) => {
  await signIn(page)
  await connectAll(page)

  await expectMinimumTextContrast(page, '.app-header__link')
  await expectMinimumTextContrast(page, '.eyebrow')
  await expectMinimumTextContrast(page, '.status-chip')

  await page.getByRole('button', { name: 'View cards' }).click()
  await expect(page.getByRole('heading', { name: 'Your credit cards' })).toBeVisible()

  const card = page.getByRole('region', { name: /ending in 4812/i })
  const transaction = card.locator('.transaction-list__row').filter({
    hasText: 'Paze · Urban Market',
  }).first()
  await expect(transaction).toContainText('$64.18')
  await expectMinimumTextContrast(page, '.transaction-row__alert-link')
  await expectNoHorizontalOverflow(page)
  await transaction.getByRole('link', { name: 'Set alert for Paze · Urban Market' }).focus()
  await page.keyboard.press('Enter')

  await expect(page.getByRole('heading', { name: 'Set transaction-count alerts' })).toBeVisible()
  await expect(page.getByLabel(/keyword or phrase/i)).toHaveValue('Paze · Urban Market')
  await expect(page.getByRole('radio', { name: /selected cards/i })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: /capital one.*ending in 4812/i })).toBeChecked()
  await expectNoHorizontalOverflow(page)
  if (testInfo.project.name === 'desktop') {
    await expectResponsiveBreakpoints(page)
  }
  await page.getByLabel(/transaction threshold/i).fill('1')
  const matchingRules = page.locator('.limitation-rule').filter({ hasText: 'Paze · Urban Market' })
  const ruleCountBeforeSave = await matchingRules.count()
  const createResponse = page.waitForResponse((response) => (
    response.url().endsWith('/api/transaction-limitations')
      && response.request().method() === 'POST'
  ))
  await page.getByRole('button', { name: /save rule/i }).click()
  await expect((await createResponse).status()).toBe(201)
  await expect(matchingRules).toHaveCount(ruleCountBeforeSave + 1)

  await page.getByRole('link', { name: 'View cards', exact: true }).click()
  const alert = page.getByRole('region', { name: /ending in 4812/i }).getByRole('alert')
  await expect(alert).toContainText('Paze · Urban Market')
  await expect(alert).toContainText('0 pending')
  await expect(alert).toContainText('Informational only')
  await expectNoHorizontalOverflow(page)

  await page.getByRole('link', { name: /alerts & limits/i }).click()
  const enabledRule = page.locator('.limitation-rule')
    .filter({ hasText: 'Paze · Urban Market' })
    .filter({ hasText: 'Enabled' })
  await expect(enabledRule).toHaveCount(1)
  page.once('dialog', (dialog) => dialog.accept())
  await enabledRule.getByRole('button', { name: 'Delete' }).click()
  await expect(enabledRule).toHaveCount(0)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
  await expectNoHorizontalOverflow(page)
})
