/**
 * Boots the same disposable demo environment used by `make preview`, with
 * stable credentials and the port Playwright expects.
 */
import { startPreviewEnvironment } from '../../scripts/preview-environment.mjs'

const PORT = Number(process.env.E2E_PORT ?? 8123)
const OWNER_EMAIL = 'e2e-owner@example.com'
const OWNER_PASSWORD = 'end-to-end-password-2026'

const preview = await startPreviewEnvironment({
  port: PORT,
  ownerEmail: OWNER_EMAIL,
  ownerPassword: OWNER_PASSWORD,
})

let shuttingDown = false
const shutdown = async () => {
  if (shuttingDown) return
  shuttingDown = true
  await preview.stop()
}
process.once('SIGTERM', shutdown)
process.once('SIGINT', shutdown)

await new Promise((resolveExit) => preview.server.once('exit', resolveExit))
await shutdown()
