import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Proxy targets match the API spec in docs/architecture.md (/nodes,
    // /ws/updates, /health) — no /api prefix. /twin/* is Module 2's
    // Digital Twin tab namespace (app/api/twin_routes.py).
    proxy: {
      '/nodes': 'http://localhost:8000',
      '/twin': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
