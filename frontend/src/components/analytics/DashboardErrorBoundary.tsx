import { Component, type ReactNode } from 'react'

// Keeps a render error inside an AG Studio widget from unmounting the whole app.
// React error boundaries must be class components.
export class DashboardErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error) {
    console.error('Analytics dashboard failed to render', error)
  }

  render() {
    if (this.state.failed) {
      return (
        <p role="alert" className="error banner" data-testid="dashboard-error">
          The dashboard could not be displayed. Use Refresh to load it again.
        </p>
      )
    }
    return this.props.children
  }
}
