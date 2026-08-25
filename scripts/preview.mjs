#!/usr/bin/env node

import { randomBytes } from 'node:crypto'

import { startPreviewEnvironment } from './preview-environment.mjs'

const OWNER_EMAIL = 'preview@example.com'

async function main() {
  const ownerPassword = `preview-${randomBytes(12).toString('base64url')}`
  const preview = await startPreviewEnvironment({
    port: process.env.PREVIEW_PORT,
    publicBaseUrl: process.env.PREVIEW_BASE_URL,
    ownerEmail: OWNER_EMAIL,
    ownerPassword,
  })

  const lines = [
    '',
    'Transaction Aggregator preview is ready.',
    `Open: ${preview.publicUrl}`,
    `Email: ${preview.ownerEmail}`,
    `Password: ${preview.ownerPassword}`,
  ]
  if (preview.publicUrl !== preview.localUrl) {
    lines.push(`Tunnel target: ${preview.localUrl}`)
  }
  lines.push(
    '',
    'This preview uses disposable demo data. Press Ctrl-C to stop it and remove the data.',
    '',
  )
  process.stdout.write(`${lines.join('\n')}\n`)

  let shuttingDown = false
  const shutdown = async () => {
    if (shuttingDown) return
    shuttingDown = true
    await preview.stop()
  }
  process.once('SIGINT', shutdown)
  process.once('SIGTERM', shutdown)

  const exitCode = await new Promise((resolveExit) => {
    preview.server.once('exit', (code, signal) => {
      resolveExit(shuttingDown ? 0 : code ?? (signal ? 1 : 0))
    })
  })
  await shutdown()
  process.exitCode = exitCode
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error)
  process.stderr.write(`Preview failed: ${message}\n`)
  process.exitCode = 1
})
