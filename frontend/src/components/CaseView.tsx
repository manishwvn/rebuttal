import { useState } from 'react'
import { api, ApiError } from '../api'
import {
  actionAmount,
  actionText,
  displayStatus,
  endpointFor,
  hoursLabel,
  money,
  reasonLabel,
  resolutionLabel,
  STATUS_LABEL,
  STATUS_TONE,
  urgency,
} from '../labels'
import type { AuditEntry, Dispute, PlannedAction, Proposal } from '../types'
import { AuditTrail } from './AuditTrail'
import { ConfirmDialog } from './ConfirmDialog'
import { FactsList } from './Facts'

interface Props {
  dispute: Dispute
  audit: AuditEntry[]
  /** Reload the inbox, the case and its audit trail after anything changed on the server. */
  onChanged: () => Promise<void>
}

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))

export function CaseView({ dispute, audit, onChanged }: Props) {
  const proposal = dispute.proposal
  return (
    <article className="case" data-testid="case-view" aria-live="polite">
      {proposal ? (
        <ProposalCase key={proposal.id} dispute={dispute} proposal={proposal} audit={audit} onChanged={onChanged} />
      ) : (
        <UnanalyzedCase dispute={dispute} audit={audit} onChanged={onChanged} />
      )}
    </article>
  )
}

function UnanalyzedCase({ dispute, audit, onChanged }: Omit<Props, 'dispute'> & { dispute: Dispute }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const analyze = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.analyze(dispute.dispute_id)
      await onChanged()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <header className="case-head">
        <div>
          <span className="label">{dispute.dispute_id}</span>
          <h2>{reasonLabel(dispute.reason)}</h2>
        </div>
        <span className="num amount">{money(dispute.dispute_amount.value)}</span>
      </header>
      <p className="note">The agent has not looked at this dispute yet. Analyzing only reads from PayPal; nothing is sent.</p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="button" className="primary" onClick={analyze} disabled={busy}>
          {busy ? 'Analyzing…' : 'Analyze dispute'}
        </button>
      </div>
      <section aria-labelledby="audit-title">
        <h3 id="audit-title">Audit trail</h3>
        <AuditTrail entries={audit} />
      </section>
    </>
  )
}

type Confirming = 'approve' | 'reject' | 'retry' | null

function ProposalCase({ dispute, proposal, audit, onChanged }: Props & { proposal: Proposal }) {
  const { decision, case_summary: summary } = proposal
  const facts = summary.facts
  const action = proposal.actions[0]
  const originalText = actionText(action)
  const status = displayStatus(proposal)
  const pending = proposal.status === 'PENDING'

  const [draft, setDraft] = useState(originalText ?? '')
  const [confirming, setConfirming] = useState<Confirming>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const trimmed = draft.trim()
  const edited = originalText !== null && trimmed !== originalText.trim()
  const messageToSend = edited ? trimmed : (originalText ?? '')
  const canApprove = originalText === null || trimmed !== ''

  // The reasoner's own pick comes from the audit log; the proposal only holds the final, guarded decision.
  const picked = [...audit].reverse().find((e) => e.step === 'decide')?.detail.resolution
  const reasonerChoice = typeof picked === 'string' ? picked : decision.resolution
  const guardChanged = reasonerChoice !== decision.resolution || decision.guard_notes.length > 0

  const openConfirm = (kind: Exclude<Confirming, null>) => {
    setError(null)
    setConfirming(kind)
  }

  const close = () => {
    if (!busy) setConfirming(null)
  }

  const confirm = async () => {
    setBusy(true)
    setError(null)
    try {
      if (confirming === 'approve') await api.approve(proposal.id, edited ? trimmed : null)
      else if (confirming === 'reject') await api.reject(proposal.id, rejectReason.trim())
      else if (confirming === 'retry') await api.retry(proposal.id)
      setConfirming(null)
      await onChanged()
    } catch (e) {
      setError(errorText(e))
      // A 409 means the proposal is no longer approvable: show why, and refresh so the screen matches the server.
      if (e instanceof ApiError && e.status === 409) await onChanged().catch(() => undefined)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <header className="case-head">
        <div>
          <span className="label">
            <span className="mono">{dispute.dispute_id}</span> · {summary.stage}
          </span>
          <h2>{reasonLabel(summary.reason)}</h2>
          <span className="muted">
            {summary.buyer ?? 'Buyer'} · <span className="num">{money(summary.amount)}</span> disputed
          </span>
        </div>
        <div className="pills">
          {summary.hours_left != null && <span className={`pill ${urgency(summary.hours_left)}`}>{hoursLabel(summary.hours_left)} left to respond</span>}
          <span className={`pill ${STATUS_TONE[status]}`} data-testid="case-status">
            {STATUS_LABEL[status]}
          </span>
        </div>
      </header>

      {summary.buyer_messages.length > 0 && (
        <blockquote className="quote">
          <span className="label">What the buyer said</span>
          <p>“{summary.buyer_messages[summary.buyer_messages.length - 1]}”</p>
        </blockquote>
      )}

      {facts.is_agent_purchase && (
        <section className="panel agent" data-testid="assistant-panel" aria-labelledby="assistant-title">
          <span className="label" id="assistant-title">
            Bought by the buyer’s AI assistant: instruction vs what shipped
          </span>
          <div className="versus">
            <div>
              <span className="label">{facts.agent_name ?? 'Assistant'} was told</span>
              <p data-testid="assistant-instruction">“{facts.agent_instruction}”</p>
            </div>
            <div>
              <span className="label">What shipped</span>
              <p data-testid="assistant-shipped">{facts.item}</p>
            </div>
          </div>
          <span className={`pill ${facts.agent_followed_instruction ? 'good' : 'bad'}`}>
            {facts.agent_followed_instruction ? 'The order matched the instruction' : 'The order did not match the instruction'}
          </span>
        </section>
      )}

      <div className="grid2">
        <section className="panel" aria-labelledby="facts-title">
          <h3 id="facts-title">Facts computed in code</h3>
          <FactsList facts={facts} />
        </section>
        <section className="panel" aria-labelledby="why-title">
          <h3 id="why-title">Why this proposal</h3>
          <dl className="compare">
            <dt>Reasoner ({decision.source})</dt>
            <dd data-testid="reasoner-choice">{resolutionLabel(reasonerChoice)}</dd>
            <dt>Final action</dt>
            <dd data-testid="final-action">
              <strong>{resolutionLabel(decision.resolution)}</strong>
            </dd>
            <dt>Confidence</dt>
            <dd>
              <span className="conf" title={`${Math.round(decision.confidence * 100)}%`}>
                <span className="track">
                  <span className="fill" style={{ width: `${Math.round(decision.confidence * 100)}%` }} />
                </span>
                <span className="num">{Math.round(decision.confidence * 100)}%</span>
              </span>
            </dd>
          </dl>
          <ul className="reasons">
            {decision.reasoning.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
          {guardChanged && decision.guard_notes.length > 0 && (
            <div className="guard" data-testid="guard-notes" role="note">
              <span className="label">Guard adjusted this</span>
              <ul>
                {decision.guard_notes.map((note, i) => (
                  <li key={i}>{note}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </div>

      <section className="proposal" aria-labelledby="proposal-title">
        <h3 id="proposal-title">{action.summary}</h3>
        <code className="call mono" data-testid="paypal-call">
          {callLine(dispute.dispute_id, action)}
        </code>

        {originalText !== null ? (
          <>
            <label htmlFor="draft" className="label">
              Message the buyer will receive {pending ? '(you can edit it)' : ''}
            </label>
            <textarea id="draft" value={draft} readOnly={!pending} onChange={(e) => setDraft(e.target.value)} rows={5} />
          </>
        ) : (
          <>
            <span className="label">Evidence summary sent to PayPal</span>
            <p className="evidence" data-testid="evidence-summary">
              {decision.evidence_summary}
            </p>
          </>
        )}

        {pending && (
          <div className="actions">
            <button type="button" className="primary" onClick={() => openConfirm('approve')} disabled={!canApprove}>
              {edited ? 'Approve with my edits' : 'Approve'}
            </button>
            <button type="button" className="ghost" onClick={() => openConfirm('reject')}>
              Reject
            </button>
            {!canApprove && <span className="muted">The message can’t be empty.</span>}
          </div>
        )}

        {proposal.status === 'APPROVED' && (
          <div className="actions">
            <p className="note">Approved, but sending to PayPal was interrupted. Retrying reads the dispute first and never repeats what already landed.</p>
            <button type="button" className="primary" onClick={() => openConfirm('retry')}>
              Retry sending
            </button>
          </div>
        )}

        {!pending && proposal.status !== 'APPROVED' && <Outcome proposal={proposal} />}
      </section>

      <section aria-labelledby="audit-title">
        <h3 id="audit-title">Audit trail</h3>
        <AuditTrail entries={audit} />
      </section>

      {confirming === 'approve' && (
        <ConfirmDialog
          title={edited ? 'Send this to PayPal with your edits?' : 'Send this to PayPal?'}
          confirmLabel="Approve and send"
          busy={busy}
          error={error}
          onConfirm={confirm}
          onCancel={close}
        >
          <SendSummary dispute={dispute} action={action} amount={actionAmount(action, summary.amount)} message={originalText === null ? null : messageToSend} edited={edited} />
        </ConfirmDialog>
      )}
      {confirming === 'retry' && (
        <ConfirmDialog title="Retry sending to PayPal?" confirmLabel="Retry" busy={busy} error={error} onConfirm={confirm} onCancel={close}>
          <SendSummary dispute={dispute} action={action} amount={actionAmount(action, summary.amount)} message={originalText === null ? null : messageToSend} edited={false} />
        </ConfirmDialog>
      )}
      {confirming === 'reject' && (
        <ConfirmDialog title="Reject this proposal?" confirmLabel="Reject" tone="danger" busy={busy} error={error} onConfirm={confirm} onCancel={close}>
          <p>
            <strong>Nothing will be sent to PayPal.</strong> The proposal is closed and the dispute stays open for you to handle yourself.
          </p>
          <label htmlFor="reject-reason" className="label">
            Reason (kept in the audit trail)
          </label>
          <textarea id="reject-reason" value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} rows={3} />
        </ConfirmDialog>
      )}
    </>
  )
}

function callLine(disputeId: string, action: PlannedAction): string {
  const extra: string[] = []
  if (action.params.offer_type) extra.push(`offer_type ${action.params.offer_type}`)
  if (action.params.evidences?.[0]) extra.push(`${action.params.evidences[0].evidence_type} + evidence PDF`)
  return [endpointFor(disputeId, action), ...extra].join('  ·  ')
}

function SendSummary({ dispute, action, amount, message, edited }: { dispute: Dispute; action: PlannedAction; amount: string | null; message: string | null; edited: boolean }) {
  return (
    <>
      <p>Approving makes exactly this one call to the PayPal sandbox:</p>
      <dl className="compare" data-testid="send-summary">
        <dt>Call</dt>
        <dd className="mono">{endpointFor(dispute.dispute_id, action)}</dd>
        <dt>Action</dt>
        <dd>{action.summary}</dd>
        {action.params.offer_type && (
          <>
            <dt>Offer type</dt>
            <dd className="mono">{action.params.offer_type}</dd>
          </>
        )}
        <dt>Amount</dt>
        <dd>{amount ?? 'No money moves with this call'}</dd>
        <dt>{message === null ? 'Evidence' : 'Message'}</dt>
        <dd>
          {message === null ? (
            <>{action.params.evidences?.map((e) => e.evidence_type).join(', ')} with an evidence PDF ({action.params.filename})</>
          ) : (
            <>
              {edited && <span className="pill accent">Your edited version</span>}
              <blockquote className="quote" data-testid="send-message">
                {message}
              </blockquote>
            </>
          )}
        </dd>
      </dl>
    </>
  )
}

function Outcome({ proposal }: { proposal: Proposal }) {
  if (proposal.status === 'REJECTED') {
    return <p className="result rejected">Rejected. Nothing was sent to PayPal.</p>
  }
  const failed = proposal.result.filter((r) => !r.ok)
  if (proposal.status === 'FAILED' || failed.length > 0) {
    return (
      <p className="result failed" role="alert">
        PayPal refused the call{failed[0]?.error ? `: ${failed[0].error}` : '.'}
      </p>
    )
  }
  return <p className="result">Sent to PayPal. {proposal.actions[0].summary}.</p>
}
