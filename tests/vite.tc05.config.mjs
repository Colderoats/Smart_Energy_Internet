// TC05 helper: same as frontend/vite.config.js but proxies to the isolated test backend (8100) and serves on 5190.
import path from 'node:path'
import { pathToFileURL } from 'node:url'
const fe = path.resolve(import.meta.dirname, '..', 'frontend')
const { defineConfig } = await import(pathToFileURL(path.join(fe, 'node_modules', 'vite', 'dist', 'node', 'index.js')).href)
const react = (await import(pathToFileURL(path.join(fe, 'node_modules', '@vitejs', 'plugin-react', 'dist', 'index.js')).href)).default
const tailwindcss = (await import(pathToFileURL(path.join(fe, 'node_modules', '@tailwindcss', 'vite', 'dist', 'index.mjs')).href)).default
const api = { target: 'http://localhost:8100', xfwd: true }
export default defineConfig({
  root: fe,
  cacheDir: path.resolve(import.meta.dirname, '.vite-cache'),
  plugins: [react(), tailwindcss()],
  server: {
    port: 5190, strictPort: true,
    proxy: Object.fromEntries(['/nodes', '/twin', '/chain', '/ai', '/testbed', '/market', '/p2p', '/auth', '/health'].map((p) => [p, api]).concat([['/ws', { target: 'ws://localhost:8100', ws: true, xfwd: true }]])),
  },
})
