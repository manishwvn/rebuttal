import type { ActionKind, PlannedAction, Proposal } from './types.ts'

export const REASON: Record<string, string> = {
  MERCHANDISE_OR_SERVICE_NOT_RECEIVED: 'Not received',
  MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED: 'Not as described',
  UNAUTHORISED: 'Unauthorized',
  CREDIT_NOT_PROCESSED: 'Refund not received',
  DUPLICATE_TRANSACTION: 'Charged twice',
}

export const RESOLUTION: Record<string, string> = {
  SHARE_TRACKING: 'Share tracking with the buyer',
  SUBMIT_EVIDENCE: 'Submit evidence to PayPal',
  OFFER_REPLACEMENT: 'Offer a free replacement',
  OFFER_PARTIAL_REFUND: 'Offer a partial refund',
  OFFER_RETURN_FOR_REFUND: 'Refund after the item is returned',
  ACCEPT_CLAIM: 'Accept and refund in full',
  SUBMIT_REFUND_PROOF: 'Send PayPal proof of the refund',
  ESCALATE: 'Ask PayPal to decide (escalate to a claim)',
  APPEAL: "Appeal PayPal's decision with new evidence",
}

export const reasonLabel = (reason: string) => REASON[reason] ?? reason
export const resolutionLabel = (resolution: string) => RESOLUTION[resolution] ?? resolution

export type DisplayStatus = 'new' | 'pending' | 'approved' | 'rejected' | 'executed' | 'failed' | 'interrupted'

// Proposal.status: PENDING | APPROVED (the PayPal call was interrupted, retry) | EXECUTED | REJECTED | FAILED | INTERRUPTED (a newer analysis stopped part-way; the fields are the previous proposal's)
export function displayStatus(proposal: Proposal | null): DisplayStatus {
  if (!proposal) return 'new'
  return proposal.status.toLowerCase() as DisplayStatus
}

export const STATUS_LABEL: Record<DisplayStatus, string> = {
  new: 'Not analyzed',
  pending: 'Pending',
  approved: 'Approved',
  rejected: 'Rejected',
  executed: 'Executed',
  failed: 'Failed',
  interrupted: 'Interrupted',
}

export const STATUS_TONE: Record<DisplayStatus, 'neutral' | 'warn' | 'accent' | 'good' | 'bad'> = {
  new: 'neutral',
  pending: 'warn',
  approved: 'accent',
  rejected: 'neutral',
  executed: 'good',
  failed: 'bad',
  interrupted: 'warn',
}

export const money = (value: number | string) => `$${Number(value).toFixed(2)}`

// A same-origin build has an empty API base, so name the page origin instead.
export const backendName = (base: string, origin: string): string => base || origin

export function hoursLabel(hours: number): string {
  const h = Math.max(0, hours)
  return h >= 48 ? `${Math.floor(h / 24)}d ${Math.round(h % 24)}h` : `${Math.round(h)}h`
}

// Time left to respond; negative hours mean the due date has passed.
export const deadlineLabel = (hours: number) => (hours < 0 ? 'Overdue' : `${hoursLabel(hours)} left to respond`)

export const urgency = (hours: number) => (hours < 48 ? 'bad' : hours < 96 ? 'warn' : 'good')

export const ageHours = (iso: string, now = Date.now()) => Math.max(0, (now - Date.parse(iso)) / 3_600_000)

// The PayPal Disputes endpoint each planned action calls (backend/rebuttal/paypal/client.py).
const ENDPOINT: Record<ActionKind, string> = {
  send_message: 'send-message',
  make_offer: 'make-offer',
  accept_claim: 'accept-claim',
  provide_evidence: 'provide-evidence',
  escalate: 'escalate',
  appeal: 'appeal',
}

export const endpointFor = (disputeId: string, action: PlannedAction) =>
  `POST /v1/customer/disputes/${disputeId}/${ENDPOINT[action.kind]}`

// The text the merchant can read and edit: the message or offer note the buyer receives, or the escalation note, which
// goes to PayPal and not to the buyer. Evidence has none.
export function actionText(action: PlannedAction): string | null {
  return action.params.message ?? action.params.note ?? null
}

// Who reads that text, so the case view names the right reader. Only the escalate note is addressed to PayPal.
export function textLabels(action: PlannedAction) {
  return action.kind === 'escalate'
    ? { draft: 'Note to PayPal', approved: 'Note you approved', summary: 'Note to PayPal' }
    : { draft: 'Message the buyer will receive', approved: 'Message you approved', summary: 'Message' }
}

export function actionAmount(action: PlannedAction, caseAmount: number): string | null {
  if (action.params.amount) return money(action.params.amount.value)
  if (action.kind === 'accept_claim') return money(caseAmount)
  return null
}
