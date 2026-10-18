import { useCallback, useEffect, useRef, useState } from 'react'
import { useApi } from '../apiContext'
import type { AuditEntry, Dispute } from '../types'
import { CaseView } from './CaseView'
import { Inbox } from './Inbox'
import { SimulatorPanel } from './SimulatorPanel'

// An error with no text still gets a banner: an empty message would render an empty alert.
const message = (e: unknown) => (e instanceof Error ? e.message : String(e)) || 'The request failed'

// The dispute desk: the inbox and the open case. Its disputes and audit reads come from useApi().
export function Desk({ simulator, initialId }: { simulator: boolean; initialId?: string }) {
  const api = useApi()
  const [disputes, setDisputes] = useState<Dispute[] | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [error, setError] = useState<string | null>(null)

  // Only the newest audit request may set the trail: a slow older response (another dispute, or the same one before
  // a decision) must not overwrite it.
  const openId = useRef<string | null>(null)
  const auditRequest = useRef(0)
  const loadAudit = useCallback(async (disputeId: string) => {
    const request = ++auditRequest.current
    const entries = await api.audit(disputeId)
    if (request === auditRequest.current && openId.current === disputeId) setAudit(entries)
  }, [api])

  const refresh = useCallback(
    async (focus?: string) => {
      const list = await api.disputes()
      setDisputes(list)
      const next = focus ?? openId.current
      if (next && list.some((d) => d.dispute_id === next)) {
        openId.current = next
        setSelectedId(next)
        await loadAudit(next)
      }
    },
    [api, loadAudit],
  )

  // The first load and the Retry button share this. A failed load leaves disputes null with the error set, which the
  // inbox shows as a failed state with Retry.
  // initialId opens that case once, when the load finds it and the user has not picked a case yet.
  const loadDisputes = useCallback(
    () =>
      api.disputes().then(
        (list) => {
          setDisputes(list)
          setError(null)
          if (initialId && openId.current === null && list.some((d) => d.dispute_id === initialId)) {
            openId.current = initialId
            setSelectedId(initialId)
            loadAudit(initialId).catch((e: unknown) => setError(message(e)))
          }
        },
        (e: unknown) => setError(message(e)),
      ),
    [api, initialId, loadAudit],
  )

  useEffect(() => {
    void loadDisputes()
    // Load once on mount.
  }, [loadDisputes])

  const retry = () => {
    setError(null)
    loadDisputes()
  }

  const select = (disputeId: string) => {
    openId.current = disputeId
    setSelectedId(disputeId)
    setAudit([])
    loadAudit(disputeId).catch((e: unknown) => setError(message(e)))
  }

  const changed = useCallback(async () => {
    try {
      await refresh()
      setError(null)
    } catch (e) {
      setError(message(e))
    }
  }, [refresh])

  const created = async (disputeId: string) => {
    setAudit([])
    await refresh(disputeId)
  }

  const selected = disputes?.find((d) => d.dispute_id === selectedId) ?? null
  const waiting = disputes?.filter((d) => d.proposal?.status === 'PENDING').length ?? 0

  return (
    <>
      {error !== null && (
        <p role="alert" className="error banner" data-testid="app-error">
          {error}
        </p>
      )}

      {simulator && <SimulatorPanel onCreated={created} />}

      <section className="block" aria-labelledby="inbox-title">
        <div className="block-head">
          <h2 id="inbox-title">Inbox</h2>
          <p data-testid="waiting">
            {waiting} {waiting === 1 ? 'proposal' : 'proposals'} waiting for you
          </p>
        </div>
        <Inbox
          disputes={disputes ?? []}
          loading={disputes === null && error === null}
          failed={disputes === null && error !== null}
          selectedId={selectedId}
          onSelect={select}
        />
      </section>

      {selected ? (
        <CaseView dispute={selected} audit={audit} onChanged={changed} />
      ) : disputes === null ? (
        error === null ? (
          <p className="note empty loading" role="status">
            Loading disputes…
          </p>
        ) : (
          <p className="note empty">
            Could not load disputes.{' '}
            <button type="button" className="ghost" data-testid="inbox-retry" onClick={retry}>
              Retry
            </button>
          </p>
        )
      ) : disputes.length === 0 ? (
        <p className="note empty">
          {simulator
            ? 'No disputes yet. Use the simulator above to create one and watch the agent handle it.'
            : 'No disputes yet. New ones appear here when PayPal sends a dispute webhook.'}
        </p>
      ) : (
        <p className="note empty">Pick a dispute in the inbox to see what the agent proposes.</p>
      )}
    </>
  )
}
