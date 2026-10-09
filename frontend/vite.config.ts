import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  // Everything in VITE_* is inlined into the built JavaScript, so a VITE_API_TOKEN in a build would be readable by
  // anyone who loads the dashboard, and it is the token that authorizes approve. loadEnv sees the same values the
  // build would bake in (the shell and the .env files), so this stops it before anything is written.
  if (command === 'build' && loadEnv(mode, process.cwd(), 'VITE_').VITE_API_TOKEN) {
    throw new Error(
      'VITE_API_TOKEN is set for a build. Values in VITE_* are public in the built bundle, so the backend token would ' +
        'ship to every visitor. Unset it (check your shell and frontend/.env*) and build again. Use the token with ' +
        '`npm run dev` only; a hosted dashboard needs a login first. See frontend/README.md.',
    )
  }
  return { plugins: [react()] }
})
