import { useEffect, useState } from 'react'
import { apiFetch } from '../auth/api'

// GET a /testbed/* endpoint (admin session cookie, same-origin through the Vite proxy).
// Returns { data, error, loading }. A 404 means the result file has not been generated yet
// (run experiments/run_all.py); the message from the backend says so.
export function useTestbed(path) {
  const [state, setState] = useState({ data: null, error: null, loading: Boolean(path) })

  useEffect(() => {
    if (!path) return undefined
    let alive = true
    apiFetch(path)
      .then(async (res) => {
        const body = await res.json().catch(() => ({}))
        if (!alive) return
        if (!res.ok) setState({ data: null, error: body.detail ?? `HTTP ${res.status}`, loading: false })
        else setState({ data: body, error: null, loading: false })
      })
      .catch((e) => alive && setState({ data: null, error: String(e), loading: false }))
    return () => {
      alive = false
    }
  }, [path])

  return path ? state : { data: null, error: null, loading: false }
}
