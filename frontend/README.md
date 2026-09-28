# SEI frontend

React 19 + Vite + Tailwind v4 + React Flow (`@xyflow/react`) + Recharts. Dashboard for the Smart Energy
Internet platform; talks to the FastAPI backend through the Vite dev proxy (`vite.config.js`).

```
npm install
npm run dev     # http://localhost:5173 (backend expected on :8000)
npm run build
npm run lint    # oxlint
```

Layout: `src/ui/` design system and app shell, `src/tabs/` one file per sidebar view, `src/components/`
shared widgets (topology, charts, FL panel), `src/hooks/` data hooks (fetch once, then WebSocket push),
`src/auth/` session, API and socket helpers, `src/mocks/uiMocks.js` the only place for mock/snapshot data.

See ../ARCHITECTURE.md "Frontend structure (UI redesign)" for the view -> data-source map and
../PROGRESS.md "UI redesign" for what is mocked.
