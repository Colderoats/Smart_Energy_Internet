import { useEffect } from 'react'
import LiveDataTab from './tabs/LiveDataTab'
import DigitalTwinTab from './tabs/DigitalTwinTab'
import BlockchainTab from './tabs/BlockchainTab'
import InviteAdminPage from './pages/InviteAdminPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { navigate, safeNext, useLocation } from './auth/router'

// Each tab has its own URL under /dashboard so a user sent to /login comes
// back to the exact view they were on.
const TABS = [
  { id: 'live', label: 'Live Data' },
  { id: 'twin', label: 'Digital Twin' },
  { id: 'chain', label: 'Blockchain' },
  { id: 'invite', label: 'Invite admin' },
]

function Redirect({ to }) {
  useEffect(() => navigate(to, { replace: true }), [to])
  return null
}

function FullScreenMessage({ children }) {
  return (
    <div className="flex h-svh items-center justify-center bg-slate-950 text-sm text-slate-400">{children}</div>
  )
}

function Dashboard({ tab }) {
  const { user, logout } = useAuth()

  const signOut = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-svh flex-col bg-slate-950 text-slate-100">
      <header className="flex items-center justify-between gap-4 border-b border-slate-800 px-4 py-3">
        <div>
          <h1 className="text-lg font-semibold">Smart Energy Internet</h1>
          <p className="text-xs text-slate-400">
            Live wind/hydro + replayed SCADA data, and the digital twin's response
          </p>
        </div>
        <div className="flex items-center gap-4">
          <nav className="flex gap-1 rounded-lg bg-slate-900 p-1 text-sm">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => navigate(`/dashboard/${t.id}`)}
                className={`rounded-md px-3 py-1.5 font-medium transition-colors ${
                  tab === t.id ? 'bg-sky-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
          <div className="flex items-center gap-2 text-sm">
            <span className="hidden text-slate-400 md:inline" title="Signed in as">
              {user?.email}
            </span>
            <button
              onClick={signOut}
              className="rounded-md border border-slate-700 px-3 py-1.5 font-medium text-slate-300 transition-colors hover:border-slate-500 hover:text-white"
            >
              Log out
            </button>
          </div>
        </div>
      </header>

      {/* Only one tab is ever mounted at a time — they don't share state or
          a socket connection, per the requirement that these be genuinely
          separate views, not one graph with extra info bolted on. Tabs (and
          therefore their WebSockets) only mount once the session is known
          to be authenticated. */}
      {tab === 'live' && <LiveDataTab />}
      {tab === 'twin' && <DigitalTwinTab />}
      {tab === 'chain' && <BlockchainTab />}
      {tab === 'invite' && <InviteAdminPage />}
    </div>
  )
}

function Routes() {
  const { status } = useAuth()
  const { path, search } = useLocation()

  if (status === 'loading') return <FullScreenMessage>Checking session…</FullScreenMessage>

  if (path === '/register') return <RegisterPage search={search} />

  if (path === '/login') {
    if (status === 'authenticated') {
      return <Redirect to={safeNext(new URLSearchParams(search).get('next'))} />
    }
    return <LoginPage search={search} />
  }

  // Everything else is the dashboard, behind the guard.
  if (status !== 'authenticated') {
    const here = path.startsWith('/dashboard') ? path + search : '/dashboard/live'
    return <Redirect to={`/login?next=${encodeURIComponent(here)}`} />
  }

  const tab = path.match(/^\/dashboard\/([a-z]+)\/?$/)?.[1]
  if (!TABS.some((t) => t.id === tab)) return <Redirect to="/dashboard/live" />
  return <Dashboard tab={tab} />
}

function App() {
  return (
    <AuthProvider>
      <Routes />
    </AuthProvider>
  )
}

export default App
