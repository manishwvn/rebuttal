import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

// vite.config.ts refuses to build when VITE_API_TOKEN is set: VITE_* values are public in the built bundle.
const frontendDir = fileURLToPath(new URL('..', import.meta.url))

for (const mode of ['production', 'staging']) {
  test(`a ${mode} build is refused while VITE_API_TOKEN is set, and writes nothing`, async () => {
    const outDir = test.info().outputPath(`guard-${mode}`)
    const build = spawnSync('npx', ['vite', 'build', '--mode', mode, '--outDir', outDir], {
      cwd: frontendDir,
      env: { ...process.env, VITE_API_TOKEN: 'a-token-that-must-not-ship' },
      encoding: 'utf8',
    })
    expect(build.status).not.toBe(0)
    expect(build.stderr).toContain('VITE_API_TOKEN is set for a build')
    expect(build.stderr).not.toContain('a-token-that-must-not-ship') // the message names the variable, never its value
    expect(existsSync(outDir)).toBe(false)
  })
}
