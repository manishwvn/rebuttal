import type { Locator, Page } from '@playwright/test'

// The suite shares one in-memory backend, so the inbox grows past what its fixed-height grid renders (rows are
// virtualised). Scroll the grid until the dispute's cell is rendered, then return it.
export async function inboxCell(page: Page, disputeId: string, colId: string): Promise<Locator> {
  const cell = page.locator(`[row-id="${disputeId}"] [col-id="${colId}"]`)
  const viewport = page.locator('[data-testid="inbox"] .ag-grid-viewport').first()
  for (let screen = 0; screen < 50 && (await cell.count()) === 0; screen++) {
    const atEnd = await viewport.evaluate((el, index) => {
      el.scrollTop = index * el.clientHeight
      return el.scrollTop + el.clientHeight >= el.scrollHeight
    }, screen)
    if (atEnd && (await cell.count()) === 0) break
  }
  return cell
}
