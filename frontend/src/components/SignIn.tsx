import { useState, type FormEvent } from 'react'
import { setToken, verifyToken } from '../api'

// The merchant pastes the API token the backend was started with. It is checked against the backend, then kept in
// sessionStorage only: never in the bundle, never in the URL.
export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [token, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const candidate = token.trim()
    if (!candidate) return
    setBusy(true)
    setError(null)
    try {
      if (await verifyToken(candidate)) {
        setToken(candidate)
        onSignedIn()
      } else {
        setError('That token was not accepted.')
      }
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : 'Could not reach the backend.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="wrap signin">
      <header className="bar">
        <div className="brand">
          <h1>Rebuttal</h1>
          <span>PayPal dispute desk</span>
        </div>
      </header>
      <form className="case signin-card" onSubmit={submit} data-testid="signin">
        <h2>Sign in</h2>
        <p className="note">Paste the API token of this deployment. It stays in this tab only.</p>
        <label htmlFor="api-token">API token</label>
        <input
          id="api-token"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={token}
          onChange={(e) => setValue(e.target.value)}
          data-testid="signin-token"
        />
        {error !== null && (
          <p role="alert" className="error" data-testid="signin-error">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="submit" className="primary" disabled={busy || !token.trim()} data-testid="signin-submit">
            {busy ? 'Checking…' : 'Sign in'}
          </button>
          <a href="#demo" className="demo-link" data-testid="try-demo">
            Try the demo
          </a>
        </div>
      </form>
    </div>
  )
}
