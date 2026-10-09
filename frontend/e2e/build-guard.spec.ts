import { spawnSync } from 'node:child_process'
import { existsSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

// vite.config.ts refuses to build when VITE_API_TOKEN is set: VITE_* values are public in the built bundle.
const frontendDir = fileURLToPath(new URL('..', import.meta.url))
const repoRoot = join(frontendDir, '..')
const vite = join(frontendDir, 'node_modules', '.bin', 'vite')
const TOKEN = 'a-token-that-must-not-ship'

function build(args: string[], cwd: string, env: Record<string, string | undefined>) {
  return spawnSync(vite, ['build', ...args], { cwd, env: { ...process.env, VITE_API_TOKEN: undefined, ...env }, encoding: 'utf8' })
}

function expectRefused(result: ReturnType<typeof build>, outDir: string) {
  expect(result.status).not.toBe(0)
  expect(result.stderr).toContain('VITE_API_TOKEN is set for a build')
  expect(result.stderr).not.toContain(TOKEN) // the message names the variable, never its value
  expect(existsSync(outDir)).toBe(false)
}

for (const mode of ['production', 'staging']) {
  test(`a ${mode} build is refused while VITE_API_TOKEN is set, and writes nothing`, async () => {
    const outDir = test.info().outputPath(`guard-${mode}`)
    expectRefused(build(['--mode', mode, '--outDir', outDir], frontendDir, { VITE_API_TOKEN: TOKEN }), outDir)
  })
}

test('a token in frontend/.env.production is refused even when vite build starts from the repo root', async () => {
  const outDir = test.info().outputPath('guard-env-file')
  const envFile = join(frontendDir, '.env.production')
  expect(existsSync(envFile)).toBe(false) // never overwrite a developer's own file
  writeFileSync(envFile, `VITE_API_TOKEN=${TOKEN}\n`)
  try {
    expectRefused(build([frontendDir, '--outDir', outDir], repoRoot, {}), outDir)
  } finally {
    rmSync(envFile, { force: true })
  }
  expect(existsSync(envFile)).toBe(false)
})
