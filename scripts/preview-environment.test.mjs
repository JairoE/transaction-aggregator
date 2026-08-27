import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  buildPreviewEnvironment,
  startPreviewEnvironment,
} from './preview-environment.mjs'

const TOKEN_KEY = 'a'.repeat(43)

test('local preview configuration supplies every required application setting', () => {
  const result = buildPreviewEnvironment({
    inheritedEnv: { PATH: '/usr/bin' },
    port: 8123,
    databaseUrl: 'sqlite+aiosqlite:////tmp/preview.db',
    applicationSecret: 's'.repeat(48),
    tokenEncryptionKey: TOKEN_KEY,
  })

  assert.equal(result.localUrl, 'http://127.0.0.1:8123')
  assert.equal(result.publicUrl, 'http://127.0.0.1:8123')
  assert.deepEqual(result.env, {
    PATH: '/usr/bin',
    ENVIRONMENT: 'demo',
    DATABASE_URL: 'sqlite+aiosqlite:////tmp/preview.db',
    APPLICATION_SECRET: 's'.repeat(48),
    TOKEN_ENCRYPTION_KEY: TOKEN_KEY,
    TOKEN_ENCRYPTION_KEY_VERSION: '1',
    PUBLIC_BASE_URL: 'http://127.0.0.1:8123',
    PLAID_CLIENT_ID: 'preview-not-used',
    PLAID_SECRET: 'preview-not-used',
    TRUSTED_HOSTS: '127.0.0.1,localhost',
    ENABLE_BACKGROUND_WORKER: 'true',
    SYNC_INTERVAL_MINUTES: '60',
  })
})

test('tunnel preview configuration trusts the public host and keeps a local target', () => {
  const result = buildPreviewEnvironment({
    inheritedEnv: {},
    port: 9000,
    publicBaseUrl: 'https://cards-preview.example.com/',
    databaseUrl: 'sqlite+aiosqlite:////tmp/preview.db',
    applicationSecret: 's'.repeat(48),
    tokenEncryptionKey: TOKEN_KEY,
  })

  assert.equal(result.localUrl, 'http://127.0.0.1:9000')
  assert.equal(result.publicUrl, 'https://cards-preview.example.com')
  assert.equal(result.env.PUBLIC_BASE_URL, 'https://cards-preview.example.com')
  assert.equal(
    result.env.TRUSTED_HOSTS,
    'cards-preview.example.com,127.0.0.1,localhost',
  )
})

test('preview starts without repository env or data and removes its temporary database', async () => {
  const preview = await startPreviewEnvironment({
    port: 0,
    ownerEmail: 'preview-test@example.com',
    ownerPassword: 'preview-test-password-2026',
    stdio: 'ignore',
  })

  try {
    assert.equal(existsSync(preview.dataDir), true)

    const health = await fetch(`${preview.localUrl}/api/health`)
    assert.equal(health.status, 200)
    assert.deepEqual(await health.json(), { status: 'ok' })

    const login = await fetch(`${preview.localUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        email: 'preview-test@example.com',
        password: 'preview-test-password-2026',
      }),
    })
    assert.equal(login.status, 200)
    assert.match(login.headers.get('set-cookie') ?? '', /ta_session=/)
  } finally {
    await preview.stop()
  }

  assert.equal(existsSync(preview.dataDir), false)
})

test('preview sweep removes only directories with a dead owner, leaving live or fresh ones alone', async () => {
  // A guaranteed-dead pid, obtained deterministically (no sleeps/timing):
  // spawn a trivial child and await its own exit before reusing its pid.
  const deadChild = spawn(process.execPath, ['-e', 'process.exit(0)'])
  await new Promise((resolveExit) => deadChild.once('exit', resolveExit))

  const deadOwnerDir = mkdtempSync(join(tmpdir(), 'ta-preview-'))
  writeFileSync(join(deadOwnerDir, 'preview.pid'), String(deadChild.pid))

  const liveOwnerDir = mkdtempSync(join(tmpdir(), 'ta-preview-'))
  writeFileSync(join(liveOwnerDir, 'preview.pid'), String(process.pid))

  const freshDir = mkdtempSync(join(tmpdir(), 'ta-preview-'))

  const preview = await startPreviewEnvironment({
    port: 0,
    ownerEmail: 'preview-sweep-test@example.com',
    ownerPassword: 'preview-test-password-2026',
    stdio: 'ignore',
  })

  try {
    assert.equal(existsSync(deadOwnerDir), false)
    assert.equal(existsSync(liveOwnerDir), true)
    assert.equal(existsSync(freshDir), true)
  } finally {
    await preview.stop()
    rmSync(liveOwnerDir, { recursive: true, force: true })
    rmSync(freshDir, { recursive: true, force: true })
  }
})

test('preview command exits successfully after a termination signal', async (t) => {
  const child = spawn(process.execPath, ['scripts/preview.mjs'], {
    cwd: new URL('..', import.meta.url),
    env: { ...process.env, PREVIEW_PORT: '0' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let stdout = ''
  let stderr = ''
  child.stdout.setEncoding('utf8')
  child.stderr.setEncoding('utf8')
  child.stdout.on('data', (chunk) => { stdout += chunk })
  child.stderr.on('data', (chunk) => { stderr += chunk })
  t.after(() => {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL')
  })

  const readyDeadline = Date.now() + 30_000
  while (!stdout.includes('Transaction Aggregator preview is ready.')) {
    if (child.exitCode !== null || child.signalCode !== null) {
      assert.fail(`Preview exited before it was ready.\n${stdout}\n${stderr}`)
    }
    if (Date.now() >= readyDeadline) {
      assert.fail(`Preview did not become ready.\n${stdout}\n${stderr}`)
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100))
  }

  child.kill('SIGTERM')
  const result = await new Promise((resolveExit) => {
    child.once('exit', (code, signal) => resolveExit({ code, signal }))
  })

  assert.deepEqual(result, { code: 0, signal: null })
})
