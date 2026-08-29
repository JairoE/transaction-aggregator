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
  const escapedElements = await page.locator('html, body, body *').evaluateAll((elements) => {
    const viewportWidth = window.innerWidth

    return elements.flatMap((element) => {
      const htmlElement = element as HTMLElement
      const styles = getComputedStyle(htmlElement)
      const bounds = htmlElement.getBoundingClientRect()
      const isRendered =
        styles.display !== 'none' &&
        styles.visibility !== 'hidden' &&
        Number(styles.opacity) !== 0 &&
        bounds.width > 0 &&
        bounds.height > 0
      const isScreenReaderOnly = htmlElement.closest('.sr-only') !== null

      if (
        !isRendered ||
        isScreenReaderOnly ||
        (bounds.left >= -0.5 && bounds.right <= viewportWidth + 0.5)
      ) {
        return []
      }

      const selector = htmlElement.id
        ? `${htmlElement.tagName.toLowerCase()}#${htmlElement.id}`
        : `${htmlElement.tagName.toLowerCase()}${Array.from(htmlElement.classList)
            .map((className) => `.${className}`)
            .join('')}`

      return [{ selector, left: bounds.left, right: bounds.right, viewportWidth }]
    })
  })

  expect(escapedElements, 'visible elements must stay within the device width').toEqual([])
}

test('setup journey is a left rail on desktop and a compact row on mobile', async ({ page }) => {
  await signIn(page)

  const layout = await page.evaluate(() => {
    const progress = document.querySelector<HTMLElement>('[aria-label="Setup progress"]')
    const content = document.querySelector<HTMLElement>('main')
    const steps = progress?.querySelector<HTMLOListElement>('ol')
    if (!progress || !content || !steps) {
      return null
    }

    const progressRect = progress.getBoundingClientRect()
    const contentRect = content.getBoundingClientRect()
    return {
      viewportWidth: window.innerWidth,
      progress: {
        bottom: progressRect.bottom,
        right: progressRect.right,
        width: progressRect.width,
      },
      content: { left: contentRect.left, top: contentRect.top },
      stepColumns: getComputedStyle(steps).gridTemplateColumns.split(' ').length,
    }
  })

  expect(layout).not.toBeNull()
  if (!layout) {
    return
  }

  if (layout.viewportWidth >= 900) {
    expect(layout.progress.right).toBeLessThanOrEqual(layout.content.left + 1)
    expect(layout.progress.width).toBeGreaterThanOrEqual(240)
  } else {
    expect(layout.progress.bottom).toBeLessThanOrEqual(layout.content.top + 1)
    expect(layout.stepColumns).toBe(4)
  }
  await expectNoHorizontalOverflow(page)
})

test('upcoming step descriptions meet minimum text contrast', async ({ page }) => {
  await signIn(page)

  const contrast = await page.evaluate(() => {
    const description = document.querySelector<HTMLElement>(
      '.journey-step.is-upcoming .journey-step__description',
    )
    const rail = document.querySelector<HTMLElement>('.journey-rail')
    if (!description || !rail) {
      return 0
    }

    const parseColor = (value: string): [number, number, number, number] => {
      const channels = value.match(/[\d.]+/g)?.map(Number) ?? []
      return [channels[0] ?? 0, channels[1] ?? 0, channels[2] ?? 0, channels[3] ?? 1]
    }
    const luminance = ([red, green, blue]: number[]) => {
      const linear = [red, green, blue].map((channel) => {
        const value = channel / 255
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    }

    const [red, green, blue, colorAlpha] = parseColor(getComputedStyle(description).color)
    const [bgRed, bgGreen, bgBlue] = parseColor(getComputedStyle(rail).backgroundColor)
    const alpha = colorAlpha * Number(getComputedStyle(description).opacity)
    const foreground = [
      red * alpha + bgRed * (1 - alpha),
      green * alpha + bgGreen * (1 - alpha),
      blue * alpha + bgBlue * (1 - alpha),
    ]
    const foregroundLuminance = luminance(foreground)
    const backgroundLuminance = luminance([bgRed, bgGreen, bgBlue])
    return (
      (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
      (Math.min(foregroundLuminance, backgroundLuminance) + 0.05)
    )
  })

  expect(contrast).toBeGreaterThanOrEqual(4.5)
})

test('owner connects four banks and searches every card at once', async ({ page }) => {
  const errors = watchForErrors(page)

  await signIn(page)

  for (const bank of BANKS) {
    await connectBank(page, bank)
  }
  await expect(page.getByText('4 of 4 connected')).toBeVisible()
  await expect
    .poll(async () => {
      const response = await page.request.get('/api/connections')
      const data = (await response.json()) as { banks: Array<{ state: string }> }
      return data.banks.every((bank) => bank.state === 'ready')
    })
    .toBe(true)

  await page.getByRole('button', { name: 'View cards' }).click()
  await expect(page.getByRole('heading', { name: 'Your credit cards' })).toBeVisible()

  const panelSurface = await page.locator('.card-panel').first().evaluate((panel) => {
    const styles = getComputedStyle(panel)
    return {
      backgroundColor: styles.backgroundColor,
      borderTopWidth: styles.borderTopWidth,
      borderRadius: styles.borderRadius,
      boxShadow: styles.boxShadow,
    }
  })
  expect(panelSurface).toEqual({
    backgroundColor: 'rgb(245, 245, 247)',
    borderTopWidth: '0px',
    borderRadius: '8px',
    boxShadow: 'none',
  })

  // Every authorized credit card gets its own panel.
  for (const mask of EXPECTED_MASKS) {
    await expect(
      page.getByRole('img', { name: new RegExp(`card ending in ${mask}$`, 'i') }),
    ).toBeVisible()
  }

  // Typing alone must not search.
  const search = page.getByRole('searchbox', { name: /Search transactions/i })
  await search.fill('Paze')
  await expect(page.getByRole('heading', { name: 'Your credit cards' })).toBeVisible()

  await page.getByRole('button', { name: 'Search', exact: true }).click()

  await expect(page.getByText('10 matches for “Paze” across 8 cards')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Search results' })).toBeVisible()

  // Every card stays in the grid, each reporting its own count.
  for (const mask of EXPECTED_MASKS) {
    await expect(
      page.getByRole('img', { name: new RegExp(`card ending in ${mask}$`, 'i') }),
    ).toBeVisible()
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

test('dashboard keeps every visible element inside a narrow mobile device', async ({ page }) => {
  await page.setViewportSize({ width: 280, height: 653 })
  await signIn(page)
  for (const bank of BANKS) {
    await connectBank(page, bank)
  }
  await page.goto('/dashboard')
  await expect(page.getByRole('img', { name: /card ending in/i }).first()).toBeVisible()

  await expectNoHorizontalOverflow(page)
})

test('every outlined card keeps its small accent label at AA contrast', async ({ page }) => {
  await signIn(page)
  for (const bank of BANKS) {
    await connectBank(page, bank)
  }
  await page.goto('/dashboard')
  await expect(page.getByRole('img', { name: /card ending in/i }).first()).toBeVisible()

  const contrastByBank = await page.locator('.credit-card-outline').evaluateAll((cards) => {
    const parseRgb = (value: string): [number, number, number] => {
      const channels = value.match(/[\d.]+/g)?.map(Number) ?? []
      return [channels[0] ?? 0, channels[1] ?? 0, channels[2] ?? 0]
    }
    const luminance = ([red, green, blue]: number[]) => {
      const linear = [red, green, blue].map((channel) => {
        const value = channel / 255
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    }

    return cards.map((card) => {
      const label = card.querySelector<HTMLElement>('.credit-card-outline__type')
      if (!label) return { bank: card.className, ratio: 0 }

      const foreground = luminance(parseRgb(getComputedStyle(label).color))
      const background = luminance(parseRgb(getComputedStyle(card).backgroundColor))
      return {
        bank: card.className,
        ratio: (Math.max(foreground, background) + 0.05) /
          (Math.min(foreground, background) + 0.05),
      }
    })
  })

  for (const result of contrastByBank) {
    expect(result.ratio, `${result.bank} accent-label contrast`).toBeGreaterThanOrEqual(4.5)
  }
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
