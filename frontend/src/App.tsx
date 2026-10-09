import { useEffect, useState } from 'react'
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
  return route === 'demo' ? <DemoApp /> : <Dashboard />
}
