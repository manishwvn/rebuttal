import type { Facts } from '../types'

type Mark = boolean | null // true = good for the merchant, false = against, null = neutral information

interface Row {
  mark: Mark
  text: string
}

// The computed facts (backend agent/facts.py). Read-only: the frontend never recomputes them.
function rows(f: Facts): Row[] {
  const out: Row[] = []
  const add = (mark: Mark, text: string) => out.push({ mark, text })
  const has = (key: string) => key in f

  add(Boolean(f.order_found), f.order_found ? `Order found: ${String(f.item)}` : 'No matching order in the store records')
  if (has('tracking_uploaded_to_paypal')) {
    add(Boolean(f.tracking_uploaded_to_paypal), f.tracking_uploaded_to_paypal ? 'Tracking is on the PayPal transaction' : 'No tracking on the PayPal transaction')
  }
  if (f.has_tracking) {
    const delivered = f.shipment_status === 'DELIVERED'
    add(
      delivered,
      `${String(f.carrier)} ${String(f.tracking_number)}: ${delivered ? `delivered ${String(f.delivered_on)}` : `${String(f.shipment_status).toLowerCase()}, last scan ${String(f.days_since_last_scan)} days ago`}`,
    )
    if (has('delivered_address_matches')) {
      add(Boolean(f.delivered_address_matches), f.delivered_address_matches ? 'Delivered to the address on the order' : 'Delivered to a different address than the order')
    }
  } else if (has('has_tracking')) {
    add(false, 'No tracking on file')
  }
  if (has('within_return_window')) add(null, f.within_return_window ? 'Inside the return window' : 'Outside the return window')
  if (has('buyer_asks_for_refund')) add(null, f.buyer_asks_for_refund ? 'Buyer asks for a refund' : 'Buyer has not asked for a refund')
  if (f.buyer_reports_damage) add(null, `Buyer reports damage; refund without return ${f.refund_without_return_eligible ? 'allowed' : 'not allowed'} for this item`)
  if (f.refund_issued) add(true, `Refund already issued (${Array.isArray(f.refund_ids) ? f.refund_ids.join(', ') : ''})`)
  if (f.return_received) add(true, 'Return received')
  if (has('matching_charges_same_day')) {
    add(!f.duplicate_charge_found, f.duplicate_charge_found ? `${String(f.matching_charges_same_day)} matching charges on the purchase day` : 'No duplicate charge found')
  }
  if (typeof f.days_since_purchase === 'number') add(null, `Purchased ${f.days_since_purchase} days ago`)
  return out
}

export function FactsList({ facts }: { facts: Facts }) {
  return (
    <ul className="facts" data-testid="facts">
      {rows(facts).map((row, i) => (
        <li key={i}>
          <span className={`mark ${row.mark === null ? 'info' : row.mark ? 'yes' : 'no'}`} aria-hidden="true">
            {row.mark === null ? 'i' : row.mark ? '✓' : '✕'}
          </span>
          <span>{row.text}</span>
        </li>
      ))}
    </ul>
  )
}
