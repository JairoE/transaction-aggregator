/**
 * Boots a throwaway API for the end-to-end suite: a fresh SQLite file, the
 * migrations applied, one owner created, and ENVIRONMENT=demo so the
 * deterministic fixture bank is used instead of Plaid.
 */
import { execFileSync, spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const PORT = process.env.E2E_PORT ?? '8123'
const repoRoot = resolve(import.meta.dirname, '..', '..')
const backend = join(repoRoot, 'backend')
const dataDir = mkdtempSync(join(tmpdir(), 'ta-e2e-'))
const dbPath = join(dataDir, 'e2e.db')

export const OWNER_EMAIL = 'e2e-owner@example.com'
export const OWNER_PASSWORD = 'end-to-end-password-2026'

const env = {
  ...process.env,
  ENVIRONMENT: 'demo',
  DATABASE_URL: `sqlite+aiosqlite:///${dbPath}`,
  APPLICATION_SECRET: randomBytes(36).toString('base64url'),
  TOKEN_ENCRYPTION_KEY: randomBytes(32).toString('base64url'),
  TOKEN_ENCRYPTION_KEY_VERSION: '1',
  PUBLIC_BASE_URL: `http://127.0.0.1:${PORT}`,
  PLAID_CLIENT_ID: 'e2e-not-used',
  PLAID_SECRET: 'e2e-not-used',
  TRUSTED_HOSTS: '127.0.0.1,localhost',
  ENABLE_BACKGROUND_WORKER: 'true',
  SYNC_INTERVAL_MINUTES: '60',
}

const uv = (args, options = {}) =>
  execFileSync('uv', ['run', '--directory', backend, ...args], {
    env,
    stdio: 'inherit',
    ...options,
  })

uv(['alembic', 'upgrade', 'head'])
execFileSync(
  'uv',
  ['run', '--directory', backend, 'python', '-m', 'app.cli', 'create-owner',
   '--email', OWNER_EMAIL, '--password-stdin'],
  { env, input: `${OWNER_PASSWORD}\n`, stdio: ['pipe', 'inherit', 'inherit'] },
)

const server = spawn(
  'uv',
  ['run', '--directory', backend, 'uvicorn', '--factory', 'app.main:create_app',
   '--host', '127.0.0.1', '--port', PORT],
  { env, stdio: 'inherit' },
)

const shutdown = () => {
  server.kill('SIGTERM')
  try {
    rmSync(dataDir, { recursive: true, force: true })
  } catch {
    // best effort
  }
}
process.on('SIGTERM', shutdown)
process.on('SIGINT', shutdown)
process.on('exit', shutdown)
