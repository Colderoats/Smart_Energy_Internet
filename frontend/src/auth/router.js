import { useEffect, useState } from 'react'

// Minimal history-API router (no new dependency). Dashboard views live under
// /dashboard/* so they never collide with the Vite proxy prefixes
// (/nodes, /twin, /chain, /auth, ...).

const LOCATION_EVENT = 'sei:navigate'

function current() {
  return { path: window.location.pathname, search: window.location.search }
}

export function navigate(to, { replace = false } = {}) {
  if (replace) window.history.replaceState(null, '', to)
  else window.history.pushState(null, '', to)
  window.dispatchEvent(new Event(LOCATION_EVENT))
}

export function useLocation() {
  const [loc, setLoc] = useState(current)
  useEffect(() => {
    const update = () => setLoc(current())
    window.addEventListener('popstate', update)
    window.addEventListener(LOCATION_EVENT, update)
    return () => {
      window.removeEventListener('popstate', update)
      window.removeEventListener(LOCATION_EVENT, update)
    }
  }, [])
  return loc
}

// Only same-app dashboard paths are accepted as a post-login destination
// (prevents open redirects via ?next=).
export function safeNext(next) {
  return typeof next === 'string' && next.startsWith('/dashboard') && !next.startsWith('//')
    ? next
    : '/dashboard/live'
}
