import { useEffect, useMemo, useState } from 'react'
import { ApiError, createDemoApi, resetDemoSession, startDemoSession } from '../api'
import { ApiContext } from '../apiContext'
import { Desk } from './Desk'
import './demo.css'

const STORAGE_KEY = 'rebuttal-demo-session'

// sessionStorage can be blocked or missing (private windows, cleared site data). Without it a reload starts a new session.
function storedSessionId(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function rememberSessionId(id: string) {
  try {
    sessionStorage.setItem(STORAGE_KEY, id)
  } catch {
    // Not remembered: a reload starts a new session.
  }
}

interface Session {
  id: string
  /** The session backend's health mode, e.g. "mock / rules". */
  mode: string
}

interface Problem {
  message: string
  /** Only a 429 from the start-up session offers Try again. A failed reset is retried with Reset demo. */
  rateLimited: boolean
}

function problemOf(e: unknown): Problem {
  if (e instanceof ApiError && e.status === 429) return { message: e.message, rateLimited: true }
  return { message: e instanceof Error ? e.message : String(e), rateLimited: false }
}

async function startSession(): Promise<Session> {
  const info = await startDemoSession()
  const health = await createDemoApi(info.session_id).health()
  return { id: info.session_id, mode: health.mode }
}

// Keeps the stored session while the server still knows it; any failure discards it and starts a new one.
async function resumeOrStart(): Promise<Session> {
  const stored = storedSessionId()
  if (stored) {
    try {
      const health = await createDemoApi(stored).health()
      return { id: stored, mode: health.mode }
    } catch {
      // Expired, unknown or unreachable: start over below.
    }
  }
  return startSession()
}

export function DemoApp() {
  const [session, setSession] = useState<Session | null>(null)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [generation, setGeneration] = useState(0)
  const [resetting, setResetting] = useState(false)

  const sessionId = session?.id ?? null
  const demoApi = useMemo(() => (sessionId ? createDemoApi(sessionId) : null), [sessionId])

  // Runs on mount and on Try again. React StrictMode runs this twice in development: the cleanup drops the result of
  // the superseded run, so the page and the stored id always come from the latest one.
  useEffect(() => {
    let latest = true
    resumeOrStart().then(
      (next) => {
        if (!latest) return
        rememberSessionId(next.id)
        setSession(next)
      },
      (e: unknown) => {
        if (latest) setProblem(problemOf(e))
      },
    )
    return () => {
      latest = false
    }
  }, [attempt])

  const tryAgain = () => {
    setProblem(null)
    setAttempt((n) => n + 1)
  }

  const reset = async () => {
    if (!session || resetting) return
    setResetting(true)
    setProblem(null)
    try {
      let next: Session
      try {
        const info = await resetDemoSession(session.id)
        next = { id: info.session_id, mode: session.mode }
      } catch (e) {
        // The session expired or is unknown: start a new one in its place.
        if (!(e instanceof ApiError && e.status === 404)) throw e
        next = await startSession()
      }
      rememberSessionId(next.id)
      setSession(next)
      setGeneration((n) => n + 1)
    } catch (e) {
      // Reset demo is the retry here, so a 429 does not offer Try again (that only re-runs start-up).
      setProblem({ ...problemOf(e), rateLimited: false })
    } finally {
      setResetting(false)
    }
  }

  return (
    <div className="wrap">
      <header className="bar">
        <div className="brand">
          <h1>Rebuttal</h1>
          <span>Judge demo</span>
          <a
            href="#"
            data-testid="exit-demo"
            onClick={(e) => {
              e.preventDefault()
              window.location.hash = ''
            }}
          >
            Exit demo
          </a>
        </div>
        <span className="badge" data-testid="mode-badge">
          demo · {session?.mode ?? 'connecting…'}
        </span>
      </header>

      <p className="note demo-banner" data-testid="demo-banner">
        This is a sandbox demo on an in-memory mock. No PayPal account is needed, and nothing is ever sent to PayPal. The demo
        resets itself after a while.
        <button type="button" className="ghost" data-testid="reset-demo" onClick={reset} disabled={!session || resetting}>
          Reset demo
        </button>
      </p>

      {problem && (
        <p role="alert" className="error" data-testid="demo-error">
          {problem.message}
          {problem.rateLimited && (
            <>
              {' '}
              <button type="button" className="ghost" onClick={tryAgain}>
                Try again
              </button>
            </>
          )}
        </p>
      )}

      {!session && !problem && <p className="note" data-testid="demo-loading">Starting the demo…</p>}

      {session && demoApi && (
        <ApiContext.Provider value={demoApi}>
          <div className="desk-panel">
            <Desk key={`${session.id}-${generation}`} simulator={true} />
          </div>
        </ApiContext.Provider>
      )}
    </div>
  )
}
