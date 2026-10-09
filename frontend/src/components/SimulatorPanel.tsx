import { useEffect, useState } from 'react'
import { useApi } from '../apiContext'
import { reasonLabel } from '../labels'
import type { SimulatorCase } from '../types'

interface Props {
  /** Called with the new dispute id once the simulated dispute exists and has been analyzed. */
  onCreated: (disputeId: string) => Promise<void>
}

// Shown only when /api/health says mock mode: it seeds a labeled case into the mock sandbox and analyzes it.
export function SimulatorPanel({ onCreated }: Props) {
  const api = useApi()
  const [cases, setCases] = useState<SimulatorCase[]>([])
  const [choice, setChoice] = useState('agent_wrong_size')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .simulatorCases()
      .then(setCases)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [api])

  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      const proposal = await api.simulate(choice)
      await onCreated(proposal.dispute_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="block simulator" aria-labelledby="sim-title" data-testid="simulator">
      <div className="block-head">
        <h2 id="sim-title">Simulator</h2>
        <p>Mock sandbox only: create a labeled dispute and watch the agent handle it. Nothing leaves this machine.</p>
      </div>
      <div className="actions">
        <label htmlFor="sim-case" className="label">
          Case
        </label>
        <select id="sim-case" value={choice} onChange={(e) => setChoice(e.target.value)} disabled={busy || cases.length === 0}>
          {cases.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title} ({reasonLabel(c.reason)}
              {c.agent_purchase ? ', AI assistant' : ''})
            </option>
          ))}
        </select>
        <button type="button" className="primary" onClick={create} disabled={busy || cases.length === 0}>
          {busy ? 'Creating…' : 'Create dispute'}
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </section>
  )
}
