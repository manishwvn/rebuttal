import { useEffect, useState } from 'react'
import { api, getToken, setToken, UNAUTHORIZED_EVENT } from './api'
import { SignIn } from './components/SignIn'
import { DemoApp } from './components/DemoApp'
import { Dashboard } from './components/Dashboard'
import './App.css'
import './components/analytics/analytics.css'

type Route = 'dashboard' | 'demo'

// '#demo' opens the demo; any other address is the dashboard.
const routeFromHash = (): Route => (window.location.hash === '#demo' ? 'demo' : 'dashboard')

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash)

  // Following the 'Try the demo' link, typing a hash, and Back and forward all move between the two routes.
  useEffect(() => {
    const sync = () => setRoute(routeFromHash())
    window.addEventListener('hashchange', sync)
    window.addEventListener('popstate', sync)
    return () => {
      window.removeEventListener('hashchange', sync)
      window.removeEventListener('popstate', sync)
    }
  }, [])

  // The dashboard is not mounted on the demo route, so the demo makes no request to /api/disputes or /api/health.
  return route === 'demo' ? <DemoApp /> : <Gate />
}

// Shows the sign-in screen when the backend wants a token and none is held. An open backend (local development) or
// an unreachable one goes straight to the dashboard, which reports the problem itself.
function Gate() {
  const [state, setState] = useState<'checking' | 'open' | 'signin'>(() => (getToken() ? 'open' : 'checking'))

  useEffect(() => {
    if (state !== 'checking') return
    let live = true
    api.health().then(
      (h) => live && setState(h.auth ? 'signin' : 'open'),
      () => live && setState('open'),
    )
    return () => {
      live = false
    }
  }, [state])

  // A refused request means the token is wrong or was revoked: back to sign-in.
  useEffect(() => {
    const back = () => setState('signin')
    window.addEventListener(UNAUTHORIZED_EVENT, back)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, back)
  }, [])

  const signOut = () => {
    setToken(null)
    setState('signin')
  }

  if (state === 'checking') return <p className="note wrap">Connecting…</p>
  if (state === 'signin') return <SignIn onSignedIn={() => setState('open')} />
  return <Dashboard onSignOut={signOut} />
}
