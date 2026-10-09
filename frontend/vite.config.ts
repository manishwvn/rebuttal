import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// Everything in VITE_* is inlined into the built JavaScript, so a VITE_API_TOKEN in a build would be readable by
// anyone who loads the dashboard, and it is the token that authorizes approve. `config.env` is exactly what the build
// would inline (the shell and the .env* files of the Vite root, wherever `vite build` was started from), so this
// stops the build before anything is written.
function refuseApiTokenInBuild(): Plugin {
  return {
    name: 'refuse-api-token-in-build',
    configResolved(config) {
      if (config.command === 'build' && config.env.VITE_API_TOKEN) {
        throw new Error(
          'VITE_API_TOKEN is set for a build. Values in VITE_* are public in the built bundle, so the backend token would ' +
            'ship to every visitor. Unset it (check your shell and frontend/.env*) and build again. Use the token with ' +
            '`npm run dev` only; a hosted dashboard needs a login first. See frontend/README.md.',
        )
      }
    },
  }
}

// https://vite.dev/config/
export default defineConfig({ plugins: [react(), refuseApiTokenInBuild()] })
