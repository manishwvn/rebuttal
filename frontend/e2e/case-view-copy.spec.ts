import { expect, test, type Page } from '@playwright/test'

const EDITED = 'Hi Lena, sorry about the mix-up. We will ship a medium right away. Juniper & Oak'
const NO_ALTERNATIVE_NOTE =
  'OFFER_REPLACEMENT is not possible on this dispute and there is no close alternative; the merchant must resolve it in Resolution Center.'

type Proposal = { decision: { resolution: string; guard_notes: string[] } } & Record<string, unknown>
type Dispute = { proposal: Proposal | null } & Record<string, unknown>

async function simulate(page: Page, caseId: string): Promise<string> {
  await page.goto('/')
  await expect(page.getByTestId('mode-badge')).toContainText('mock')
  await page.getByLabel('Case').selectOption(caseId)
  await page.getByRole('button', { name: 'Create dispute' }).click()
  const caseView = page.getByTestId('case-view')
  await expect(caseView).toBeVisible()
  const disputeId = (await caseView.locator('.case-head .mono').innerText()).split(' ')[0]
  expect(disputeId).toMatch(/^PP-D-\d+$/)
  return disputeId
}

// The guard reaches the no-alternative branch only when PayPal allows neither a refund nor an accept, and no mock case
// does that. So this shapes what the dashboard receives: the resolution stays OFFER_REPLACEMENT with that guard note.
function noAlternative(proposal: Proposal): Proposal {
  return { ...proposal, decision: { ...proposal.decision, resolution: 'OFFER_REPLACEMENT', guard_notes: [NO_ALTERNATIVE_NOTE] } }
}

test('the approve dialog says a replacement is not possible, and the executed case shows the approved text', async ({ page }) => {
  await simulate(page, 'agent_wrong_size')
  const caseView = page.getByTestId('case-view')
  const drafted = await caseView.getByLabel(/Message the buyer will receive/).inputValue()
  expect(drafted.trim()).not.toBe('')

  await caseView.getByRole('button', { name: 'Approve', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByTestId('replacement-note')).toBeVisible()
  await expect(dialog.getByTestId('replacement-note')).toContainText('PayPal takes no replacement offer')
  await dialog.getByRole('button', { name: 'Approve and send' }).click()

  await expect(page.getByTestId('case-status')).toHaveText('Executed')
  await expect(caseView.getByText('Message you approved', { exact: true })).toBeVisible()
  await expect(caseView.getByText('your edited version')).toHaveCount(0)
  await expect(caseView.getByTestId('approved-text')).not.toBeEmpty()
  await expect(caseView.getByTestId('approved-text')).toContainText(drafted)
  await expect(caseView.getByText('Message the buyer will receive')).toHaveCount(0)
})

test('an executed message the merchant edited is labelled as their edited version', async ({ page }) => {
  await simulate(page, 'agent_wrong_size')
  const caseView = page.getByTestId('case-view')

  await caseView.getByLabel(/Message the buyer will receive/).fill(EDITED)
  await caseView.getByRole('button', { name: 'Approve with my edits' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Approve and send' }).click()

  await expect(page.getByTestId('case-status')).toHaveText('Executed')
  await expect(caseView.getByText('Message you approved (your edited version)', { exact: true })).toBeVisible()
  await expect(caseView.getByTestId('approved-text')).toHaveText(EDITED)
})

test('the approve dialog has no replacement note when the guard did not convert a replacement', async ({ page }) => {
  await simulate(page, 'inr_no_tracking')
  const caseView = page.getByTestId('case-view')

  await caseView.getByRole('button', { name: 'Approve', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByTestId('send-summary')).toBeVisible()
  // The case has no OFFER_REPLACEMENT guard note (the guard notes, when shown, are the only place one would appear).
  const notes = await caseView.getByTestId('guard-notes').allTextContents()
  expect(notes.join(' ')).not.toContain('OFFER_REPLACEMENT is not possible')
  await expect(dialog.getByTestId('replacement-note')).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toBeHidden()
})

test('no replacement note when the guard found no alternative and the offer stays a replacement', async ({ page }) => {
  await page.route('**/api/simulator/dispute/*', async (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    const res = await route.fetch()
    await route.fulfill({ response: res, json: noAlternative((await res.json()) as Proposal) })
  })
  await page.route('**/api/disputes', async (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    const res = await route.fetch()
    const disputes = (await res.json()) as Dispute[]
    const shaped = disputes.map((d) => (d.proposal ? { ...d, proposal: noAlternative(d.proposal) } : d))
    await route.fulfill({ response: res, json: shaped })
  })
  await simulate(page, 'agent_wrong_size')
  const caseView = page.getByTestId('case-view')
  await expect(caseView.getByTestId('guard-notes')).toContainText(NO_ALTERNATIVE_NOTE)

  await caseView.getByRole('button', { name: 'Approve', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByTestId('send-summary')).toBeVisible()
  await expect(dialog.getByTestId('replacement-note')).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toBeHidden()
})

test('the Reasoner row says so when the audit has no decide entry', async ({ page }) => {
  await page.route('**/api/audit/*', async (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    const res = await route.fetch()
    const body = (await res.json()) as { step: string }[]
    await route.fulfill({ response: res, json: body.filter((e) => e.step !== 'decide') })
  })
  await simulate(page, 'agent_wrong_size')

  await expect(page.getByTestId('case-view').getByTestId('reasoner-choice')).toHaveText('Not in the audit trail')
})
