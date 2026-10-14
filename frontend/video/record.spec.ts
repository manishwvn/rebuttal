// Records the demo video. One test drives the real dashboard (production build, mock backend, rules reasoner) through
// the shot list in shots.json, and leaves screen.webm and timeline.json in VIDEO_WORK_DIR. Captions come from
// overlay.ts, the cards from cards.ts, and the hold times from durations.json in VIDEO_WORK_DIR.
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Locator, type Page } from '@playwright/test'
import { setOverlay } from './overlay.ts'
import { closeCard, evalCard, pipelineCard, terminalCard } from './cards.ts'

interface Shot {
  id: string
  minSeconds: number
  narration: string
  badge: boolean
  tag?: string
}

interface Duration {
  narrationMs: number
  holdMs: number
}

interface Handler {
  card?: () => string
  run?: (page: Page) => Promise<void>
}

const DISPUTE = 'PP-D-2000'

const row = (page: Page) => page.locator(`[row-id="${DISPUTE}"]`)
const statusCell = (page: Page, disputeId: string) => page.locator(`[row-id="${disputeId}"] [col-id="status"]`)
const auditSteps = (page: Page) =>
  page
    .getByTestId('audit-trail')
    .locator('li')
    .evaluateAll((items) => items.map((li) => li.getAttribute('data-step')))

// Moves the mouse to the middle of an element in 25 steps, so the overlay cursor visibly travels.
// The element is scrolled into view first, so its middle is on screen and the cursor stays in the frame.
async function moveTo(page: Page, target: Locator): Promise<void> {
  await target.scrollIntoViewIfNeeded()
  const box = await target.boundingBox()
  if (!box) throw new Error('element has no bounding box, so the cursor cannot move to it')
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 25 })
}

// Smooth-scrolls an element into view, then waits for the scroll to finish.
async function smoothScroll(page: Page, target: Locator, block: ScrollLogicalPosition = 'center'): Promise<void> {
  await target.evaluate((el, position) => el.scrollIntoView({ behavior: 'smooth', block: position }), block)
  await page.waitForTimeout(700)
}

// The output the safety-tests card shows. Read before recording starts, so a missing run fails early.
function readPytestOutput(work: string): string {
  const file = join(work, 'pytest.txt')
  if (!existsSync(file)) throw new Error(`${file} is missing: save the pytest output there before recording`)
  const output = readFileSync(file, 'utf8')
  if (!/\b\d+ passed\b/.test(output)) throw new Error(`${file} has no pytest 'N passed' summary, so it is not a passing run`)
  if (/\b[1-9]\d* (failed|errors?)\b/.test(output)) throw new Error(`${file} reports failures or errors, so the card would show a failing run`)
  return output
}

test('record the demo video', async ({ browser }) => {
  // The take runs for the full video, about three minutes, so the default 30 s test timeout would abort it.
  test.setTimeout(15 * 60_000)
  const work = process.env.VIDEO_WORK_DIR
  if (!work) throw new Error('VIDEO_WORK_DIR is not set: point it at the folder that receives screen.webm and timeline.json')

  const shots: Shot[] = (JSON.parse(readFileSync(join(import.meta.dirname, 'shots.json'), 'utf8')) as { shots: Shot[] }).shots
  const durations = JSON.parse(readFileSync(join(work, 'durations.json'), 'utf8')) as Record<string, Duration>
  const pytestOutput = readPytestOutput(work)

  const handlers: Record<string, Handler> = {
    hook: {
      run: async (page) => {
        await moveTo(page, row(page))
      },
    },
    open: {
      run: async (page) => {
        await moveTo(page, row(page))
        await row(page).click()
        await expect(page.getByRole('button', { name: 'Analyze dispute' })).toBeVisible()
        await expect(page.getByTestId('case-view')).toContainText('The agent has not looked at this dispute yet')
        await page.waitForTimeout(800)
      },
    },
    analyze: {
      run: async (page) => {
        const button = page.getByRole('button', { name: 'Analyze dispute' })
        await moveTo(page, button)
        await button.click()
        await expect(page.getByTestId('assistant-panel')).toBeVisible({ timeout: 60_000 })
        await expect(page.getByTestId('case-status')).toHaveText('Pending')
        await expect(statusCell(page, DISPUTE)).toHaveText('Pending')
        await page.waitForTimeout(800)
      },
    },
    mismatch: {
      run: async (page) => {
        await smoothScroll(page, page.getByTestId('case-view').locator('blockquote.quote').first(), 'start')
        await expect(page.getByTestId('assistant-instruction')).toContainText('navy linen shirt in medium')
        await expect(page.getByTestId('assistant-shipped')).toContainText('Size L')
        await expect(page.getByTestId('assistant-panel')).toContainText('did not match the instruction')
      },
    },
    facts: {
      run: async (page) => {
        const list = page.getByTestId('facts')
        await smoothScroll(page, list)
        for (const item of await list.locator('li').all()) await moveTo(page, item)
        // If "No duplicate charge found" fails, that is the simulator's duplicate-charge quirk: let the take fail.
        await expect(list).toContainText('Delivered to the address on the order')
        await expect(list).toContainText('No duplicate charge found')
      },
    },
    decision: {
      run: async (page) => {
        const choice = page.getByTestId('reasoner-choice')
        const finalAction = page.getByTestId('final-action')
        await moveTo(page, choice)
        await moveTo(page, finalAction)
        await expect(choice).toHaveText('Offer a free replacement')
        await expect(finalAction).toHaveText('Refund after the item is returned')
        await expect(page.getByTestId('case-view')).toContainText('Reasoner (rules)')
      },
    },
    guard: {
      run: async (page) => {
        await smoothScroll(page, page.getByTestId('guard-notes'))
        await page.waitForTimeout(5000)
        // The proposal card is the parent of the PayPal call line.
        await smoothScroll(page, page.getByTestId('paypal-call').locator('xpath=..'), 'start')
        await expect(page.getByTestId('guard-notes')).toContainText('OFFER_REPLACEMENT is not possible on this dispute')
        await expect(page.getByTestId('paypal-call')).toContainText('make-offer')
        await expect(page.getByTestId('paypal-call')).toContainText('REFUND_WITH_RETURN')
      },
    },
    edit: {
      run: async (page) => {
        const draft = page.getByLabel(/Message the buyer will receive/)
        await moveTo(page, draft)
        await draft.focus()
        await draft.evaluate((el) => {
          const area = el as HTMLTextAreaElement
          area.setSelectionRange(area.value.length, area.value.length)
        })
        await draft.pressSequentially(' Thank you for your patience.', { delay: 40 })
        await expect(page.getByRole('button', { name: 'Approve with my edits' })).toBeVisible()
      },
    },
    confirm: {
      run: async (page) => {
        const approve = page.getByRole('button', { name: 'Approve with my edits' })
        await moveTo(page, approve)
        await approve.click()
        const dialog = page.getByRole('dialog')
        await expect(dialog).toBeVisible()
        const summary = dialog.getByTestId('send-summary')
        await expect(summary).toContainText(`POST /v1/customer/disputes/${DISPUTE}/make-offer`)
        await expect(summary).toContainText('REFUND_WITH_RETURN')
        await expect(summary).toContainText('$48.00')
        await expect(dialog.getByTestId('send-message')).toHaveText(/Thank you for your patience\.$/)
      },
    },
    approved: {
      run: async (page) => {
        const dialog = page.getByRole('dialog')
        const send = dialog.getByRole('button', { name: 'Approve and send' })
        await moveTo(page, send)
        await send.click()
        await expect(dialog).toBeHidden()
        await expect(page.getByTestId('case-status')).toHaveText('Executed')
        await expect(statusCell(page, DISPUTE)).toHaveText('Executed')
        await page.waitForTimeout(800)
        await smoothScroll(page, page.getByTestId('audit-trail'), 'end')
        await expect.poll(() => auditSteps(page)).toEqual(['gather', 'decide', 'guard', 'propose', 'approve', 'execute', 'record'])
        await expect(page.getByTestId('audit-trail')).toContainText('Merchant approved with an edited message')
      },
    },
    'safety-graph': { card: () => pipelineCard() },
    'safety-tests': { card: () => terminalCard(pytestOutput) },
    'eval-held-out': { card: () => evalCard(1) },
    'eval-main': { card: () => evalCard(2) },
    'close-pitch': { card: () => closeCard(1) },
    'close-real': { card: () => closeCard(2) },
  }

  // Every shot needs a handler and a duration, and every handler needs a shot. Checked before the browser starts.
  const shotIds = new Set(shots.map((shot) => shot.id))
  for (const shot of shots) {
    if (!handlers[shot.id]) throw new Error(`shots.json shot "${shot.id}" has no handler in record.spec.ts`)
    if (!durations[shot.id]) throw new Error(`durations.json has no entry for shot "${shot.id}"`)
  }
  for (const id of Object.keys(handlers)) {
    if (!shotIds.has(id)) throw new Error(`handler "${id}" has no shot in shots.json`)
  }

  // A context of our own so the video is recorded. The config's use options reach only the built-in page fixture,
  // so baseURL is copied here, or page.goto('/') has no origin to resolve against.
  const context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
    viewport: { width: 1280, height: 720 },
    colorScheme: 'light',
    recordVideo: { dir: join(work, 'raw'), size: { width: 1280, height: 720 } },
  })
  const t0 = Date.now()
  const page = await context.newPage()

  // The footage is saved even when a step fails, so the failing take can still be inspected. The error still propagates.
  try {
    // Setup, not a shot: the mock runs on a fixed clock, so the inbox Age column is the same in every take.
    await page.clock.setFixedTime(new Date('2026-10-06T16:00:00Z'))
    await page.goto('/')
    await expect(page.getByTestId('mode-badge')).toContainText('mock / rules')
    await expect(row(page)).toBeVisible()
    await expect(page.locator('[row-id]')).toHaveCount(6)
    await expect(statusCell(page, DISPUTE)).toHaveText('Not analyzed')

    const timeline: { id: string; startMs: number; endMs: number }[] = []
    for (const shot of shots) {
      const handler = handlers[shot.id]
      const hold = durations[shot.id].holdMs
      if (handler.card) await page.setContent(handler.card())
      await setOverlay(page, { caption: shot.narration, badge: shot.badge, tag: shot.tag })
      const startMs = Date.now() - t0
      await handler.run?.(page)
      await page.waitForTimeout(Math.max(0, hold - (Date.now() - t0 - startMs)))
      timeline.push({ id: shot.id, startMs, endMs: Date.now() - t0 })
    }

    writeFileSync(join(work, 'timeline.json'), JSON.stringify(timeline, null, 2))
  } finally {
    await context.close()
    await page.video()!.saveAs(join(work, 'screen.webm'))
  }
})
