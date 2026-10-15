import { expect, test } from '@playwright/test'

// WCAG 2.x contrast of the theme tokens in index.css, checked in both colour schemes. Reads the computed token values
// from the page, so it needs no backend data: it only loads the dashboard.
const PAIRS: [fg: string, bg: string][] = [
  ['ink', 'bg'],
  ['ink', 'surface'],
  ['ink', 'raised'],
  ['ink', 'accent-soft'],
  ['muted', 'bg'],
  ['muted', 'surface'],
  ['muted', 'raised'],
  ['muted', 'accent-soft'],
  ['accent', 'bg'],
  ['accent', 'surface'],
  ['accent', 'accent-soft'],
  ['good', 'good-soft'],
  ['good', 'surface'],
  ['warn', 'warn-soft'],
  ['warn', 'surface'],
  ['bad', 'bad-soft'],
  ['bad', 'surface'],
  ['on-accent', 'accent'],
  ['on-bad', 'bad'],
]
const TOKEN_NAMES = [...new Set(PAIRS.flat())]
const MIN_RATIO = 4.5

function relativeLuminance(hex: string): number {
  // The browser may hand back the short form (#fff) for a #ffffff token.
  const match = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex)
  if (!match) throw new Error(`expected a #rgb or #rrggbb token value, got "${hex}"`)
  const digits = match[1].length === 3 ? [...match[1]].map((c) => c + c).join('') : match[1]
  const value = parseInt(digits, 16)
  const [r, g, b] = [value >> 16, (value >> 8) & 255, value & 255].map((channel) => {
    const srgb = channel / 255
    return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrastRatio(a: string, b: string): number {
  const [lighter, darker] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x)
  return (lighter + 0.05) / (darker + 0.05)
}

for (const colorScheme of ['light', 'dark'] as const) {
  test(`theme text pairs reach ${MIN_RATIO}:1 in ${colorScheme} mode`, async ({ page }) => {
    await page.emulateMedia({ colorScheme })
    await page.goto('/')
    const tokens: Record<string, string> = await page.evaluate((names) => {
      const style = getComputedStyle(document.documentElement)
      return Object.fromEntries(names.map((name) => [name, style.getPropertyValue(`--${name}`).trim()]))
    }, TOKEN_NAMES)

    const failures: string[] = []
    for (const [fg, bg] of PAIRS) {
      const pair = `${colorScheme}: --${fg} (${tokens[fg]}) on --${bg} (${tokens[bg]})`
      try {
        const ratio = contrastRatio(tokens[fg], tokens[bg])
        if (ratio < MIN_RATIO) failures.push(`${pair} is ${ratio.toFixed(2)}:1, need ${MIN_RATIO}:1`)
      } catch (error) {
        failures.push(`${pair} cannot be measured: ${(error as Error).message}`)
      }
    }
    expect(failures, `contrast failures in ${colorScheme} mode`).toEqual([])
  })
}
