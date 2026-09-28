// Every backend call goes through apiFetch. Tokens live ONLY in httpOnly
// cookies set by the backend (never in localStorage/sessionStorage), so there
// is nothing to attach here: the browser sends them. On a 401 we try one
// silent refresh (deduplicated across concurrent callers), retry once, and if
// that fails announce 'sei:auth-expired' so the AuthProvider sends the user to
// /login.

const NO_REFRESH = ['/auth/login', '/auth/refresh', '/auth/register', '/auth/logout']
export const AUTH_EXPIRED_EVENT = 'sei:auth-expired'

let refreshing = null

export function notifyAuthExpired() {
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
}

// Resolves true if the session is valid after the attempt.
export function refreshSession() {
  if (!refreshing) {
    refreshing = fetch('/auth/refresh', { method: 'POST', credentials: 'same-origin' })
      .then(async (res) => {
        if (res.ok) return true
        // Another tab may have rotated the token a moment ago; the browser
        // then already holds the new cookies.
        const me = await fetch('/auth/me', { credentials: 'same-origin' })
        return me.ok
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

export async function apiFetch(input, init = {}) {
  const opts = { credentials: 'same-origin', ...init }
  const res = await fetch(input, opts)
  const path = typeof input === 'string' ? input.split('?')[0] : ''
  if (res.status !== 401 || NO_REFRESH.includes(path)) return res
  if (!(await refreshSession())) {
    notifyAuthExpired()
    return res
  }
  const retry = await fetch(input, opts)
  if (retry.status === 401) notifyAuthExpired()
  return retry
}

// JSON helper for forms: throws Error(detail) on a non-2xx response.
export async function apiJson(input, init = {}) {
  const res = await apiFetch(input, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
  })
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (!res.ok) {
    const detail = data?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? 'Please check the form fields.'
          : res.status === 429
            ? 'Too many attempts. Please wait and try again.'
            : `Request failed (${res.status})`
    const err = new Error(message)
    err.status = res.status
    throw err
  }
  return data
}
