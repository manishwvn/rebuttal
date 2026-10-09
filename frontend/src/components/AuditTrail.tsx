import type { AuditEntry } from '../types'
import { resolutionLabel } from '../labels'

const text = (value: unknown) => (typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value))

// One readable line per audit step. Unknown steps fall back to their raw detail rather than being hidden.
function describe(entry: AuditEntry): string {
  const d = entry.detail
  switch (entry.step) {
    case 'gather':
      return `Read the dispute, order, tracking and policies (${Array.isArray(d.tool_calls) ? d.tool_calls.length : 0} lookups, read only)`
    case 'decide':
      return `${text(d.source)} chose ${resolutionLabel(text(d.resolution))}${typeof d.confidence === 'number' ? ` (confidence ${d.confidence})` : ''}`
    case 'guard':
      return Array.isArray(d.notes) && d.notes.length ? d.notes.map(text).join(' ') : 'Guard found nothing to change'
    case 'propose':
      return `Proposed: ${Array.isArray(d.actions) ? d.actions.map(text).join('; ') : ''}. Waiting for the merchant`
    case 'approve':
      return `Merchant approved${d.edited ? ' with an edited message' : ''}`
    case 'reject':
      return `Merchant rejected${d.reason ? `: ${text(d.reason)}` : ''}`
    case 'execute':
      // A retry reads the dispute first; when the first attempt had already landed, nothing is sent again.
      return `${d.reconciled ? 'Already at PayPal from the first attempt, not sent again' : 'Sent to PayPal'}: ${text(d.summary)}`
    case 'record':
      return `Recorded as ${text(d.status)}`
    default:
      return JSON.stringify(d)
  }
}

export function AuditTrail({ entries }: { entries: AuditEntry[] }) {
  if (entries.length === 0) return <p className="note">No audit entries yet.</p>
  return (
    <ol className="timeline" data-testid="audit-trail">
      {entries.map((entry, i) => (
        <li key={`${entry.ts}-${entry.step}-${i}`} data-step={entry.step}>
          <span className="step">{entry.step}</span>
          <span>
            {describe(entry)}
            <time className="sub" dateTime={entry.ts}>
              {new Date(entry.ts).toLocaleString()}
            </time>
          </span>
        </li>
      ))}
    </ol>
  )
}
