import { useEffect } from 'react'

// AG Studio picks its light or dark theme from data-ag-theme-mode on an ancestor. Follow the OS setting, as the page
// CSS does (App.css, index.css), so the dashboard matches the rest of the page.
export function useAgThemeMode() {
  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      document.documentElement.dataset.agThemeMode = query.matches ? 'dark' : 'light'
    }
    apply()
    query.addEventListener('change', apply)
    return () => query.removeEventListener('change', apply)
  }, [])
}
