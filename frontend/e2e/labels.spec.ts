import { expect, test } from '@playwright/test'
import { STATUS_LABEL, STATUS_TONE, displayStatus, textLabels } from '../src/labels.ts'
import type { ActionKind, PlannedAction, Proposal } from '../src/types.ts'

const action = (kind: ActionKind): PlannedAction => ({ kind, summary: '', params: {} })

test('the escalation note is labelled as a note to PayPal, not a message the buyer receives', () => {
  expect(textLabels(action('escalate'))).toEqual({
    draft: 'Note to PayPal',
    approved: 'Note you approved',
    summary: 'Note to PayPal',
  })
})

test('every other text-bearing action is labelled as a message to the buyer', () => {
  for (const kind of ['send_message', 'make_offer', 'accept_claim'] as const) {
    expect(textLabels(action(kind)).draft).toBe('Message the buyer will receive')
    expect(textLabels(action(kind)).summary).toBe('Message')
  }
})

test('an interrupted proposal is labelled Interrupted with a warning tone', () => {
  const p = { status: 'INTERRUPTED' } as unknown as Proposal
  expect(displayStatus(p)).toBe('interrupted')
  expect(STATUS_LABEL.interrupted).toBe('Interrupted')
  expect(STATUS_TONE.interrupted).toBe('warn')
  expect(displayStatus(null)).toBe('new')
})
