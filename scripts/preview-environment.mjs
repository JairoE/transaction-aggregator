import { execFileSync, spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdtempSync, rmSync } from 'node:fs'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const BACKEND_ROOT = join(REPO_ROOT, 'backend')
const DEFAULT_PORT = 8000
const STARTUP_TIMEOUT_MS = 30_000

const MIGRATION_SCRIPT = `
from alembic import command
from alembic.config import Config

config = Config(${JSON.stringify(join(BACKEND_ROOT, 'alembic.ini'))})
config.set_main_option("script_location", ${JSON.stringify(join(BACKEND_ROOT, 'alembic'))})
config.set_main_option("prepend_sys_path", ${JSON.stringify(BACKEND_ROOT)})
command.upgrade(config, "head")
`

function normalizePublicUrl(value, localUrl) {
  const parsed = new URL(value ?? localUrl)
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('PREVIEW_BASE_URL must use http:// or https://.')
  }
  if (
    parsed.username
    || parsed.password
    || parsed.pathname !== '/'
    || parsed.search
    || parsed.hash
  ) {
    throw new Error('PREVIEW_BASE_URL must be an origin without a path, query, or fragment.')
  }
  return parsed.origin
}

export function buildPreviewEnvironment({
  inheritedEnv = process.env,
  port,
  publicBaseUrl,
  databaseUrl,
  applicationSecret,
  tokenEncryptionKey,
}) {
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error('Preview port must be an integer from 1 through 65535.')
  }

  const localUrl = `http://127.0.0.1:${port}`
  const publicUrl = normalizePublicUrl(publicBaseUrl, localUrl)
  const publicHost = new URL(publicUrl).hostname
  const trustedHosts = [...new Set([publicHost, '127.0.0.1', 'localhost'])]

  return {
    localUrl,
    publicUrl,
    env: {
      ...inheritedEnv,
      ENVIRONMENT: 'demo',
      DATABASE_URL: databaseUrl,
      APPLICATION_SECRET: applicationSecret,
      TOKEN_ENCRYPTION_KEY: tokenEncryptionKey,
      TOKEN_ENCRYPTION_KEY_VERSION: '1',
      PUBLIC_BASE_URL: publicUrl,
      PLAID_CLIENT_ID: 'preview-not-used',
      PLAID_SECRET: 'preview-not-used',
      TRUSTED_HOSTS: trustedHosts.join(','),
      ENABLE_BACKGROUND_WORKER: 'true',
      SYNC_INTERVAL_MINUTES: '60',
    },
  }
}

function probePort(port) {
  return new Promise((resolveProbe, rejectProbe) => {
    const probe = createServer()
    probe.unref()
    probe.once('error', rejectProbe)
    probe.listen({ host: '127.0.0.1', port }, () => {
      const address = probe.address()
      const selectedPort = typeof address === 'object' && address ? address.port : port
      probe.close(() => resolveProbe(selectedPort))
    })
  })
}

async function selectPort(requestedPort) {
  if (requestedPort !== undefined) {
    const parsed = Number(requestedPort)
    if (!Number.isInteger(parsed) || parsed < 0 || parsed > 65_535) {
      throw new Error('PREVIEW_PORT must be an integer from 0 through 65535.')
    }
    return probePort(parsed)
  }

  try {
    return await probePort(DEFAULT_PORT)
  } catch (error) {
    if (error?.code !== 'EADDRINUSE') throw error
    return probePort(0)
  }
}

async function waitForHealth(localUrl, server) {
  const deadline = Date.now() + STARTUP_TIMEOUT_MS
  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(`Preview server exited during startup with code ${server.exitCode}.`)
    }
    try {
      const response = await fetch(`${localUrl}/api/health`)
      if (response.ok) return
    } catch {
      // The socket is expected to refuse connections until Uvicorn is ready.
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100))
  }
  throw new Error(`Preview server did not become ready within ${STARTUP_TIMEOUT_MS}ms.`)
}

async function waitForExit(server, timeoutMs) {
  if (server.exitCode !== null) return true
  return new Promise((resolveWait) => {
    const timer = setTimeout(() => {
      server.off('exit', onExit)
      resolveWait(false)
    }, timeoutMs)
    const onExit = () => {
      clearTimeout(timer)
      resolveWait(true)
    }
    server.once('exit', onExit)
  })
}

export async function startPreviewEnvironment({
  port,
  publicBaseUrl,
  ownerEmail,
  ownerPassword,
  stdio = 'inherit',
} = {}) {
  const selectedPort = await selectPort(port)
  const dataDir = mkdtempSync(join(tmpdir(), 'ta-preview-'))
  const dbPath = join(dataDir, 'preview.db')
  const configuration = buildPreviewEnvironment({
    port: selectedPort,
    publicBaseUrl,
    databaseUrl: `sqlite+aiosqlite:///${dbPath}`,
    applicationSecret: randomBytes(36).toString('base64url'),
    tokenEncryptionKey: randomBytes(32).toString('base64url'),
  })

  let server
  let stopPromise
  const stop = async () => {
    if (stopPromise) return stopPromise
    stopPromise = (async () => {
      if (server && server.exitCode === null) {
        server.kill('SIGTERM')
        if (!(await waitForExit(server, 3_000))) {
          server.kill('SIGKILL')
          await waitForExit(server, 1_000)
        }
      }
      rmSync(dataDir, { recursive: true, force: true })
    })()
    return stopPromise
  }

  try {
    // `cwd` must be BACKEND_ROOT, not dataDir: `python -m app.cli` and
    // uvicorn's `app.main:create_app` import string both resolve `app`
    // relative to the process's working directory, and dataDir is a scratch
    // temp dir holding only the SQLite file, not the `app` package. The
    // migration step is the exception — Alembic's own `prepend_sys_path`
    // config option (set to BACKEND_ROOT above) inserts it onto `sys.path`
    // itself, so it would still resolve `app` correctly either way; using
    // BACKEND_ROOT here too keeps all three invocations consistent.
    execFileSync(
      'uv',
      ['run', '--project', BACKEND_ROOT, 'python', '-c', MIGRATION_SCRIPT],
      { cwd: BACKEND_ROOT, env: configuration.env, stdio },
    )
    execFileSync(
      'uv',
      [
        'run', '--project', BACKEND_ROOT, 'python', '-m', 'app.cli',
        'create-owner', '--email', ownerEmail, '--password-stdin',
      ],
      {
        cwd: BACKEND_ROOT,
        env: configuration.env,
        input: `${ownerPassword}\n`,
        stdio: ['pipe', stdio, stdio],
      },
    )

    server = spawn(
      'uv',
      [
        'run', '--project', BACKEND_ROOT, 'uvicorn', '--factory',
        'app.main:create_app', '--host', '127.0.0.1', '--port', String(selectedPort),
      ],
      { cwd: BACKEND_ROOT, env: configuration.env, stdio },
    )
    await waitForHealth(configuration.localUrl, server)
  } catch (error) {
    await stop()
    throw error
  }

  return {
    ...configuration,
    dataDir,
    ownerEmail,
    ownerPassword,
    server,
    stop,
  }
}
