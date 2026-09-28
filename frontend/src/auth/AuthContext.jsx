import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { AUTH_EXPIRED_EVENT, apiFetch, apiJson } from './api'

const AuthContext = createContext(null)

// status: 'loading' (checking the session cookie) | 'authenticated' | 'anonymous'
export function AuthProvider({ children }) {
  const [status, setStatus] = useState('loading')
  const [user, setUser] = useState(null)

  useEffect(() => {
    let cancelled = false
    apiFetch('/auth/me')
      .then(async (res) => {
        if (cancelled) return
        if (res.ok) {
          setUser((await res.json()).user)
          setStatus('authenticated')
        } else {
          setStatus('anonymous')
        }
      })
      .catch(() => !cancelled && setStatus('anonymous'))
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const expired = () => {
      setUser(null)
      setStatus('anonymous')
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, expired)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expired)
  }, [])

  const login = useCallback(async (email, password) => {
    const data = await apiJson('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
    setUser(data.user)
    setStatus('authenticated')
    return data.user
  }, [])

  const logout = useCallback(async () => {
    try {
      await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' })
    } finally {
      setUser(null)
      setStatus('anonymous')
    }
  }, [])

  const value = useMemo(() => ({ status, user, login, logout }), [status, user, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  return useContext(AuthContext)
}
