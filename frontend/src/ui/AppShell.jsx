import { createContext, useContext, useEffect, useState } from 'react'
import Icon from './icons'
import { NAV } from './nav'

// Layout shell: dark navy sidebar + light content area + top bar.
//
// The top bar's live indicator reflects the current page's own WebSocket.
// Pages call useReportConnection(connected); the shell opens no socket of its
// own and never polls.


const ConnectionContext = createContext(() => {})

// eslint-disable-next-line react-refresh/only-export-components
export function useReportConnection(connected) {
  const report = useContext(ConnectionContext)
  useEffect(() => {
    report(connected)
  }, [connected, report])
  useEffect(() => () => report(null), [report])
}

function initials(email) {
  const name = (email ?? '?').split('@')[0]
  const parts = name.split(/[._-]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '?') + (parts[1]?.[0] ?? '')).toUpperCase()
}

// eslint-disable-next-line react-refresh/only-export-components
export function displayName(email) {
  const name = (email ?? '').split('@')[0]
  return name
    .split(/[._-]+/)
    .filter(Boolean)
    .map((p) => p[0].toUpperCase() + p.slice(1))
    .join(' ')
}

export function Avatar({ email, size = 36 }) {
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-500 font-semibold text-white"
      style={{ width: size, height: size, fontSize: size * 0.38 }}
    >
      {initials(email)}
    </span>
  )
}

function Sidebar({ active, onNavigate, user, onLogout }) {
  return (
    <aside className="flex w-60 shrink-0 flex-col bg-[#0b1733] text-slate-300">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500 text-sm font-bold text-white">SEI</span>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-white">Smart Energy</div>
          <div className="text-xs text-slate-400">Internet</div>
        </div>
      </div>
      <nav className="flex-1 space-y-1 px-3 py-2">
        {NAV.map((item) => (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            aria-current={active === item.id ? 'page' : undefined}
            className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium transition-colors ${
              active === item.id ? 'bg-white/10 text-white' : 'text-slate-400 hover:bg-white/5 hover:text-slate-100'
            }`}
          >
            <Icon name={item.icon} size={18} />
            {item.label}
            {active === item.id && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-indigo-400" />}
          </button>
        ))}
      </nav>
      <div className="border-t border-white/10 p-4">
        <div className="flex items-center gap-3">
          <Avatar email={user?.email} />
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-sm font-medium text-white">{displayName(user?.email) || 'Admin'}</div>
            <div className="truncate text-xs text-slate-400">{user?.role ?? 'admin'}</div>
          </div>
          <button
            onClick={onLogout}
            title="Log out"
            aria-label="Log out"
            className="rounded-lg p-2 text-slate-400 hover:bg-white/10 hover:text-white"
          >
            <Icon name="logout" size={17} />
          </button>
        </div>
      </div>
    </aside>
  )
}

function LiveIndicator({ connected }) {
  if (connected == null) return null
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium ${
        connected ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
      }`}
    >
      <span className={`relative flex h-2 w-2`}>
        {connected && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${connected ? 'bg-emerald-500' : 'bg-red-500'}`} />
      </span>
      {connected ? 'Live' : 'Disconnected'}
    </span>
  )
}

export default function AppShell({ active, onNavigate, user, onLogout, children }) {
  const [connected, setConnected] = useState(null)
  const page = NAV.find((n) => n.id === active)
  return (
    <ConnectionContext.Provider value={setConnected}>
      <div className="flex h-svh bg-slate-50 text-slate-800">
        <Sidebar active={active} onNavigate={onNavigate} user={user} onLogout={onLogout} />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6">
            <h1 className="text-xl font-semibold text-slate-900">{page?.title}</h1>
            <div className="flex items-center gap-4">
              <LiveIndicator connected={connected} />
              <div className="flex items-center gap-2.5">
                <div className="hidden text-right leading-tight md:block">
                  <div className="text-sm font-medium text-slate-800">{displayName(user?.email) || 'Admin'}</div>
                  <div className="text-xs text-slate-500">{user?.email}</div>
                </div>
                <Avatar email={user?.email} size={34} />
              </div>
            </div>
          </header>
          <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
        </div>
      </div>
    </ConnectionContext.Provider>
  )
}
