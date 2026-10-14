import type { Page } from '@playwright/test'

export interface OverlayOptions {
  caption: string
  badge?: boolean
  tag?: string
}

// Draws the recording overlay into the page: a caption bar, optional chips and a fake cursor. Playwright's video
// does not draw the pointer, so the cursor is a div that follows mousemove. The callback runs in the page, so it
// cannot see anything defined outside it: every constant it needs is declared inside.
export async function setOverlay(page: Page, o: OverlayOptions): Promise<void> {
  await page.evaluate((opts: OverlayOptions) => {
    const ROOT_ID = 'rb-overlay'
    const CURSOR_ID = 'rb-cursor'
    const BADGE_TEXT = 'Mock PayPal sandbox. Demo data.'
    const CHIP_CSS =
      'position:fixed;font-size:15px;background:rgba(255,255,255,0.92);color:#14202e;border:1px solid #d5dde6;border-radius:6px;padding:4px 10px'

    let root = document.getElementById(ROOT_ID)
    if (!root) {
      root = document.createElement('div')
      root.id = ROOT_ID
      root.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647'
      document.documentElement.append(root)
    }

    // Replace the caption and chips on every call. Keep the cursor so it does not jump back to the corner.
    for (const child of Array.from(root.children)) {
      if (child.id !== CURSOR_ID) child.remove()
    }

    const caption = document.createElement('div')
    caption.textContent = opts.caption
    caption.style.cssText =
      'position:fixed;left:0;right:0;bottom:24px;margin:0 auto;width:fit-content;max-width:1040px;box-sizing:border-box;padding:12px 20px;border-radius:10px;background:rgba(20,32,46,0.92);color:#fff;font-family:system-ui, sans-serif;font-size:24px;line-height:1.35'
    root.append(caption)

    const chips: [string, string][] = []
    if (opts.badge) chips.push([BADGE_TEXT, 'right:16px;bottom:112px'])
    if (opts.tag) chips.push([opts.tag, 'left:16px;bottom:112px'])
    for (const [text, position] of chips) {
      const chip = document.createElement('div')
      chip.textContent = text
      chip.style.cssText = `${CHIP_CSS};${position}`
      root.append(chip)
    }

    if (!document.getElementById(CURSOR_ID)) {
      const cursor = document.createElement('div')
      cursor.id = CURSOR_ID
      cursor.style.cssText =
        'position:fixed;left:0;top:0;width:16px;height:16px;box-sizing:border-box;border-radius:50%;background:#0e6b63;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.4)'
      root.append(cursor)
    }

    const w = window as Window & { __rbCursor?: boolean }
    if (!w.__rbCursor) {
      w.__rbCursor = true
      window.addEventListener('mousemove', (e) => {
        const cursor = document.getElementById(CURSOR_ID)
        if (!cursor) return
        cursor.style.left = `${e.clientX - 8}px`
        cursor.style.top = `${e.clientY - 8}px`
      })
    }
  }, o)
}
