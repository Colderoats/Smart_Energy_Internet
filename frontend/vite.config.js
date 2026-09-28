import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const BACKEND = 'http://localhost:8000'
// xfwd: pass the browser's IP as X-Forwarded-For so the backend's per-IP
// login/register rate limits see real clients, not the proxy (the backend
// trusts that header only from 127.0.0.1 / ::1, see TRUSTED_PROXIES).
// The Origin header is passed through unchanged for the backend's CSRF check.
const api = { target: BACKEND, xfwd: true }

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Proxy targets match the API spec in docs/architecture.md (/nodes,
    // /ws/updates, /health) — no /api prefix. /twin/* is Module 2's
    // Digital Twin tab namespace (app/api/twin_routes.py). Dashboard pages
    // live under /dashboard/* so they never collide with these prefixes.
    proxy: {
      '/nodes': api,
      '/twin': api,
      // Module 5 Blockchain tab (app/api/chain_routes.py).
      '/chain': api,
      // Module 3 AI predictions + model card (app/api/ai_routes.py), read by
      // the AI Insights view. No SPA route starts with /ai.
      '/ai': api,
      // Admin authentication (app/api/auth_routes.py).
      '/auth': api,
      '/health': api,
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        xfwd: true,
      },
    },
  },
})
