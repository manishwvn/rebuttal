// Shapes of the backend API (backend/rebuttal/app.py, Proposal.to_dict() in agent/pipeline.py, Decision in
// agent/reasoner.py). Field names are the backend's; nothing here is invented.

export type ActionKind = 'send_message' | 'make_offer' | 'provide_evidence' | 'accept_claim'

export interface Money {
  currency_code: string
  value: string
}

export interface PlannedAction {
  kind: ActionKind
  summary: string
  params: {
    message?: string
    note?: string
    offer_type?: string
    amount?: Money
    evidences?: { evidence_type: string; notes?: string }[]
    filename?: string
    [key: string]: unknown
  }
}

export interface Decision {
  resolution: string
  confidence: number
  reasoning: string[]
  buyer_wants: string
  message_to_buyer: string
  evidence_summary: string
  partial_refund_pct: number | null
  source: string
  guard_notes: string[]
}

export type Facts = Record<string, unknown> & {
  is_agent_purchase?: boolean
  agent_name?: string
  agent_instruction?: string
  agent_followed_instruction?: boolean
  assistant_misordered?: boolean
  item?: string
}

export interface CaseSummary {
  reason: string
  stage: string
  amount: number
  due: string | null
  hours_left: number | null
  buyer: string | null
  buyer_messages: string[]
  facts: Facts
  policies: string[]
  tool_calls: string[]
}

export type ProposalStatus = 'PENDING' | 'APPROVED' | 'EXECUTED' | 'REJECTED' | 'FAILED'

export interface ActionResult {
  action: string
  ok: boolean
  error?: string
  idempotency_key?: string
}

export interface Proposal {
  id: string
  dispute_id: string
  created: string
  decision: Decision
  actions: PlannedAction[]
  case_summary: CaseSummary
  status: ProposalStatus
  result: ActionResult[]
  /** The buyer text the merchant approved (their edit, or the draft approved as is); null before a decision, after a rejection and for evidence. */
  approved_message: string | null
  has_evidence_document: boolean
}

export interface Dispute {
  dispute_id: string
  create_time: string
  update_time: string
  reason: string
  status: string
  dispute_amount: Money
  dispute_life_cycle_stage: string
  dispute_channel: string
  proposal: Proposal | null
}

export interface AuditEntry {
  ts: string
  dispute_id: string
  step: string
  detail: Record<string, unknown>
}

export interface Health {
  ok: boolean
  mode: string
  auth: boolean
  database: boolean | null
}

export interface SimulatorCase {
  id: string
  title: string
  reason: string
  agent_purchase: boolean
}

// Analytics: GET /api/analytics/rows, /summary and /deadlines. Money is USD; per row, refunded + kept + open == amount.
export type AnalyticsStatus = 'NOT_ANALYZED' | 'PENDING' | 'APPROVED' | 'EXECUTED' | 'REJECTED' | 'FAILED' | 'INTERRUPTED'

export type AnalyticsOutcome = 'not_analyzed' | 'awaiting_merchant' | 'rejected' | 'failed' | 'refunded' | 'partially_refunded' | 'kept'

export interface AnalyticsRow {
  dispute_id: string
  /** PayPal reason code, e.g. MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED. */
  reason: string
  paypal_status: string
  created: string
  due: string | null
  product: string
  amount: number
  status: AnalyticsStatus
  outcome: AnalyticsOutcome
  refunded: number
  kept: number
  open: number
  model_resolution: string | null
  final_resolution: string | null
  agrees: 0 | 1 | null
  /** Always 1, so summing it counts disputes. */
  count: number
}

export interface AnalyticsSummary {
  generated_at: string
  totals: { disputes: number; analyzed: number; executed: number }
  by_status: Record<string, number>
  by_reason: { reason: string; count: number; amount: number }[]
  by_product: { product: string; count: number; amount: number }[]
  money: { currency: 'USD'; disputed: number; refunded: number; kept: number; open: number }
  /** rate is 0..1, or null when nothing has been compared. */
  agreement: { compared: number; agreed: number; rate: number | null; guard_changes: number }
}

export interface DeadlineRow {
  dispute_id: string
  reason: string
  amount: number
  status: string
  paypal_status: string
  due: string
  /** Negative when the deadline has passed. */
  hours_left: number
}

/** GET /api/analytics: the three parts come from one sweep of the disputes, so they agree with each other. */
export interface AnalyticsReport {
  rows: AnalyticsRow[]
  summary: AnalyticsSummary
  deadlines: DeadlineRow[]
}
