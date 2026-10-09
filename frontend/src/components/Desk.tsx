import { useCallback, useEffect, useRef, useState } from 'react'
import { useApi } from '../apiContext'
import type { AuditEntry, Dispute } from '../types'
import { CaseView } from './CaseView'
import { Inbox } from './Inbox'
import { SimulatorPanel } from './SimulatorPanel'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// The dispute desk: the inbox and the open case. Its data comes from the API that useApi() provides.
export function Desk({ simulator }: { simulator: boolean }) {
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

  useEffect(() => {
    api.disputes().then(setDisputes, (e: unknown) => setError(message(e)))
    // Load once on mount.
  }, [api])

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
      {error && (
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
        <Inbox disputes={disputes ?? []} selectedId={selectedId} onSelect={select} />
      </section>

      {selected ? (
        <CaseView dispute={selected} audit={audit} onChanged={changed} />
      ) : (
        <p className="note empty">{disputes === null ? 'Loading disputes…' : 'Pick a dispute in the inbox to see what the agent proposes.'}</p>
      )}
    </>
  )
}
