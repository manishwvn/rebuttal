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
