import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { PlaidLinkOnSuccess, PlaidLinkOptionsWithLinkToken } from 'react-plaid-link'
import { server } from '../test/server'
import { renderAppAt } from '../test/renderApp'
import { runAxeSmokeTest } from '../test/axe'
import {
  authenticatedSessionHandler,
  connectionsHandler,
  makeConnectionsResponse,
  TEST_OWNER,
} from '../test/handlers'
import { continuationExpiry, saveLinkContinuation, readLinkContinuation } from './linkContinuation'
import { describeStatus } from './BankConnectionCard'

const usePlaidLinkMock = vi.fn()

vi.mock('react-plaid-link', () => ({
  usePlaidLink: (options: PlaidLinkOptionsWithLinkToken) => usePlaidLinkMock(options),
}))

function findCard(name: string): HTMLElement {
  const heading = screen.getByRole('heading', { name })
  const card = heading.closest('.bank-card')
  if (!card) {
    throw new Error(`Could not find a .bank-card ancestor for heading "${name}"`)
  }
  return card as HTMLElement
}

beforeEach(() => {
  usePlaidLinkMock.mockReset()
  usePlaidLinkMock.mockReturnValue({
    ready: false,
    open: vi.fn(),
    exit: vi.fn(),
    submit: vi.fn(),
    error: null,
  })
})

describe('bank connections', () => {
  it('has no detectable accessibility violations on the connections view', async () => {
    server.use(authenticatedSessionHandler(), connectionsHandler(makeConnectionsResponse()))
    const { container } = renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    await runAxeSmokeTest(container)
  })

  it('requires trial-slot confirmation before requesting a Link token for a production connection', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(makeConnectionsResponse()),
      http.post('/api/connections/link-token', async ({ request }) => {
        const body = (await request.json()) as { bank: string; confirm_trial_slot: boolean }
        if (!body.confirm_trial_slot) {
          return HttpResponse.json(
            {
              code: 'TRIAL_SLOT_UNCONFIRMED',
              message:
                'Connecting a real bank permanently consumes one of the 10 Plaid Trial Item slots. Confirm to continue.',
            },
            { status: 409 },
          )
        }
        return HttpResponse.json({
          link_token: 'link-demo-capital-one-new-confirmed',
          bank: 'capital-one',
          mode: 'new',
          consumes_trial_slot: true,
          production_item_count: 1,
          production_item_limit: 10,
        })
      }),
    )
    const user = userEvent.setup()
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    const card = findCard('Capital One')
    await user.click(within(card).getByRole('button', { name: /connect capital one/i }))

    expect(
      await within(card).findByText(/uses one of your 10 plaid trial item slots/i),
    ).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(within(card).getByRole('button', { name: /confirm & continue/i }))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(
      within(screen.getByRole('dialog')).getByRole('heading', { name: /continue to capital one/i }),
    ).toBeInTheDocument()
  })

  it('exchanges the public token after a successful demo Link approval', async () => {
    let connected = false
    server.use(
      authenticatedSessionHandler(),
      http.get('/api/connections', () =>
        HttpResponse.json(
          makeConnectionsResponse(
            connected
              ? [
                  {
                    bank: 'chase',
                    connected: true,
                    connection_id: 'conn-chase-1',
                    card_count: 2,
                    institution_name: 'Chase',
                  },
                ]
              : [],
          ),
        ),
      ),
      http.post('/api/connections/link-token', () =>
        HttpResponse.json({
          link_token: 'link-demo-chase-new-abc123',
          bank: 'chase',
          mode: 'new',
          consumes_trial_slot: false,
          production_item_count: 0,
          production_item_limit: 10,
        }),
      ),
      http.post('/api/connections/exchange', async ({ request }) => {
        const body = await request.json()
        expect(body).toEqual({
          bank: 'chase',
          public_token: 'public-demo-chase',
          institution_id: 'ins_3',
          institution_name: 'Chase',
        })
        connected = true
        return HttpResponse.json({
          connection_id: 'conn-chase-1',
          bank: 'chase',
          institution_name: 'Chase',
          card_count: 2,
          sync_job_id: null,
        })
      }),
    )
    const user = userEvent.setup()
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    const card = findCard('Chase')
    await user.click(within(card).getByRole('button', { name: /connect chase/i }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: /continue to chase/i })).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: /approve & return/i }))

    expect(await within(card).findByText(/2 credit cards loaded/i)).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: /^connected$/i })).toBeDisabled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('reinitializes real Plaid Link with the stored token and current redirect URI after an OAuth redirect', async () => {
    saveLinkContinuation(TEST_OWNER.id, {
      bank: 'chase',
      linkToken: 'link-oauth-continuation-token',
      expiresAt: continuationExpiry(),
    })
    let capturedOptions: PlaidLinkOptionsWithLinkToken | null = null
    usePlaidLinkMock.mockImplementation((options: PlaidLinkOptionsWithLinkToken) => {
      capturedOptions = options
      return { ready: true, open: vi.fn(), exit: vi.fn(), submit: vi.fn(), error: null }
    })

    let exchangeBody: unknown = null
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(makeConnectionsResponse()),
      http.post('/api/connections/exchange', async ({ request }) => {
        exchangeBody = await request.json()
        return HttpResponse.json({
          connection_id: 'conn-chase-1',
          bank: 'chase',
          institution_name: 'Chase',
          card_count: 2,
          sync_job_id: null,
        })
      }),
    )

    renderAppAt('/oauth-return')
    await screen.findByText(/finishing your bank connection/i)

    expect(capturedOptions).not.toBeNull()
    expect(capturedOptions!.token).toBe('link-oauth-continuation-token')
    expect(capturedOptions!.receivedRedirectUri).toBe(window.location.href)

    const onSuccess = capturedOptions!.onSuccess as PlaidLinkOnSuccess
    await act(async () => {
      onSuccess('public-token-from-oauth', {
        institution: { institution_id: 'ins_3', name: 'Chase' },
        accounts: [],
        link_session_id: 'session-1',
      })
    })

    expect(await screen.findByRole('heading', { name: /connect your credit cards/i })).toBeInTheDocument()
    expect(exchangeBody).toEqual({
      bank: 'chase',
      public_token: 'public-token-from-oauth',
      institution_id: 'ins_3',
      institution_name: 'Chase',
    })
    expect(readLinkContinuation(TEST_OWNER.id)).toBeNull()
  })

  it('returns safely to the connections page without exchanging when the OAuth continuation is absent', async () => {
    let exchangeCalls = 0
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(makeConnectionsResponse()),
      http.post('/api/connections/exchange', () => {
        exchangeCalls += 1
        return HttpResponse.json(
          { code: 'UNEXPECTED', message: 'should not be called' },
          { status: 500 },
        )
      }),
    )

    renderAppAt('/oauth-return')

    expect(
      await screen.findByRole('heading', { name: /connect your credit cards/i }),
    ).toBeInTheDocument()
    expect(exchangeCalls).toBe(0)
    expect(usePlaidLinkMock).not.toHaveBeenCalled()
  })

  it('returns safely to the connections page without exchanging when the OAuth continuation has expired', async () => {
    saveLinkContinuation(TEST_OWNER.id, {
      bank: 'chase',
      linkToken: 'link-expired-token',
      expiresAt: new Date(Date.now() - 60_000).toISOString(),
    })
    let exchangeCalls = 0
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(makeConnectionsResponse()),
      http.post('/api/connections/exchange', () => {
        exchangeCalls += 1
        return HttpResponse.json(
          { code: 'UNEXPECTED', message: 'should not be called' },
          { status: 500 },
        )
      }),
    )

    renderAppAt('/oauth-return')

    expect(
      await screen.findByRole('heading', { name: /connect your credit cards/i }),
    ).toBeInTheDocument()
    expect(exchangeCalls).toBe(0)
    expect(readLinkContinuation(TEST_OWNER.id)).toBeNull()
  })

  it('offers Reconnect and Disconnect for an already-connected bank instead of a second Connect', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(
        makeConnectionsResponse([
          {
            bank: 'citi',
            connected: true,
            connection_id: 'conn-citi-1',
            card_count: 1,
            institution_name: 'Citi',
          },
        ]),
      ),
    )
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    const card = findCard('Citi')
    expect(within(card).getByRole('button', { name: /^connected$/i })).toBeDisabled()
    expect(within(card).getByRole('button', { name: /reconnect/i })).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: /disconnect/i })).toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: /^connect citi/i })).not.toBeInTheDocument()
  })

  it('reveals View dashboard once all four banks are connected', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(
        makeConnectionsResponse(
          (['capital-one', 'chase', 'citi', 'wells-fargo'] as const).map((bank) => ({
            bank,
            connected: true,
            connection_id: `conn-${bank}`,
            card_count: 2,
          })),
        ),
      ),
    )
    const user = userEvent.setup()
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    const dashboardButton = screen.getByRole('button', { name: /view dashboard/i })
    await user.click(dashboardButton)

    expect(await screen.findByRole('heading', { name: /your credit cards/i })).toBeInTheDocument()
  })

  it('does not reveal View dashboard until all four banks are connected', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(
        makeConnectionsResponse([
          { bank: 'capital-one', connected: true, connection_id: 'conn-co', card_count: 2 },
        ]),
      ),
    )
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    expect(screen.queryByRole('button', { name: /view dashboard/i })).not.toBeInTheDocument()
  })

  it('keeps a failed bank error scoped to its own card and leaves the others usable', async () => {
    server.use(
      authenticatedSessionHandler(),
      connectionsHandler(makeConnectionsResponse()),
      http.post('/api/connections/link-token', async ({ request }) => {
        const body = (await request.json()) as { bank: string }
        if (body.bank === 'citi') {
          return HttpResponse.json(
            { code: 'PROVIDER_UNAVAILABLE', message: 'Citi is temporarily unavailable. Try again shortly.' },
            { status: 502 },
          )
        }
        return HttpResponse.json({
          link_token: `link-demo-${body.bank}-new-x`,
          bank: body.bank,
          mode: 'new',
          consumes_trial_slot: false,
          production_item_count: 0,
          production_item_limit: 10,
        })
      }),
    )
    const user = userEvent.setup()
    renderAppAt('/connections')
    await screen.findByRole('heading', { name: /connect your credit cards/i })

    const citiCard = findCard('Citi')
    await user.click(within(citiCard).getByRole('button', { name: /connect citi/i }))

    expect(await within(citiCard).findByRole('alert')).toHaveTextContent(
      /citi is temporarily unavailable/i,
    )

    const chaseCard = findCard('Chase')
    const capitalOneCard = findCard('Capital One')
    const wellsFargoCard = findCard('Wells Fargo')
    expect(within(chaseCard).queryByRole('alert')).not.toBeInTheDocument()
    expect(within(capitalOneCard).queryByRole('alert')).not.toBeInTheDocument()
    expect(within(wellsFargoCard).queryByRole('alert')).not.toBeInTheDocument()
    expect(within(chaseCard).getByRole('button', { name: /connect chase/i })).toBeEnabled()
  })

  describe('secret handling', () => {
    let consoleLogSpy: ReturnType<typeof vi.spyOn>
    let consoleErrorSpy: ReturnType<typeof vi.spyOn>
    let consoleWarnSpy: ReturnType<typeof vi.spyOn>

    beforeEach(() => {
      consoleLogSpy = vi.spyOn(console, 'log').mockImplementation(() => {})
      consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    })

    afterEach(() => {
      consoleLogSpy.mockRestore()
      consoleErrorSpy.mockRestore()
      consoleWarnSpy.mockRestore()
    })

    it('never renders or logs the Link token, public token, or access token', async () => {
      const secretLinkToken = 'link-demo-wells-fargo-new-SUPER-SECRET-TOKEN'
      const secretPublicToken = 'public-demo-wells-fargo'
      let connected = false
      server.use(
        authenticatedSessionHandler(),
        http.get('/api/connections', () =>
          HttpResponse.json(
            makeConnectionsResponse(
              connected
                ? [
                    {
                      bank: 'wells-fargo',
                      connected: true,
                      connection_id: 'conn-wf-1',
                      card_count: 2,
                      institution_name: 'Wells Fargo',
                    },
                  ]
                : [],
            ),
          ),
        ),
        http.post('/api/connections/link-token', () =>
          HttpResponse.json({
            link_token: secretLinkToken,
            bank: 'wells-fargo',
            mode: 'new',
            consumes_trial_slot: false,
            production_item_count: 0,
            production_item_limit: 10,
          }),
        ),
        http.post('/api/connections/exchange', () => {
          connected = true
          return HttpResponse.json({
            connection_id: 'conn-wf-1',
            bank: 'wells-fargo',
            institution_name: 'Wells Fargo',
            card_count: 2,
            sync_job_id: null,
          })
        }),
      )
      const user = userEvent.setup()
      const { container } = renderAppAt('/connections')
      await screen.findByRole('heading', { name: /connect your credit cards/i })

      const card = findCard('Wells Fargo')
      await user.click(within(card).getByRole('button', { name: /connect wells fargo/i }))

      const dialog = await screen.findByRole('dialog')
      expect(container.innerHTML).not.toContain(secretLinkToken)

      await user.click(within(dialog).getByRole('button', { name: /approve & return/i }))
      await within(card).findByText(/2 credit cards loaded/i)

      expect(container.innerHTML).not.toContain(secretLinkToken)
      expect(container.innerHTML).not.toContain(secretPublicToken)

      for (const spy of [consoleLogSpy, consoleErrorSpy, consoleWarnSpy]) {
        for (const call of spy.mock.calls) {
          const serialized = call.map((arg) => String(arg)).join(' ')
          expect(serialized).not.toContain(secretLinkToken)
          expect(serialized).not.toContain(secretPublicToken)
        }
      }
    })
  })

  describe('describeStatus', () => {
    const baseBank = {
      action: 'none',
      bank: 'chase' as const,
      cache_as_of: null,
      card_count: 0,
      connected: false,
      connection_id: null,
      consent_expiration_at: null,
      display_name: 'Chase',
      institution_name: null,
      last_error_code: null,
      last_provider_update_at: null,
      last_successful_sync_at: null,
      lifecycle_status: 'disconnected',
      message: 'Not connected.',
      refresh_supported: true,
      state: 'disconnected',
    }

    it('reports Connecting while the Link token request is in flight', () => {
      const result = describeStatus(baseBank, { kind: 'requesting-link' })
      expect(result.chipText).toBe('Connecting…')
      expect(result.statusLine).toBe('Connecting…')
    })

    it('reports loading progress while the exchange is finishing', () => {
      const result = describeStatus(baseBank, { kind: 'finishing' })
      expect(result.statusLine).toBe('Loading transactions…')
    })

    it('reports Ready once cards have loaded', () => {
      const result = describeStatus(
        { ...baseBank, connected: true, card_count: 2 },
        { kind: 'idle' },
      )
      expect(result.chipText).toBe('Connected')
      expect(result.statusLine).toBe('2 credit cards loaded')
    })

    it('reports Needs attention when the connection has a recorded error', () => {
      const result = describeStatus(
        { ...baseBank, connected: true, last_error_code: 'ITEM_LOGIN_REQUIRED' },
        { kind: 'idle' },
      )
      expect(result.chipText).toBe('Needs attention')
    })

    it('reports Not connected before any connection exists', () => {
      const result = describeStatus(baseBank, { kind: 'idle' })
      expect(result.chipText).toBe('Not connected')
      expect(result.statusLine).toBe('Ready to connect')
    })
  })
})
