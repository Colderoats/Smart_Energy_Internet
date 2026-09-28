import { useEffect } from 'react'
import DashboardTab from './tabs/DashboardTab'
import GridMapTab from './tabs/GridMapTab'
import SourcesTab from './tabs/SourcesTab'
import RedistributionTab from './tabs/RedistributionTab'
import AIInsightsTab from './tabs/AIInsightsTab'
import AnalyticsTab from './tabs/AnalyticsTab'
import SettingsTab from './tabs/SettingsTab'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { navigate, safeNext, useLocation } from './auth/router'
import AppShell from './ui/AppShell'
import { NAV } from './ui/nav'

// Each view has its own URL under /dashboard so a user sent to /login comes
// back to the exact view they were on. Sidebar order and ids: ui/AppShell NAV.
// Pre-redesign URLs still work: they redirect to the view that now holds them
// (Live Data + Digital Twin -> Grid Map toggles, Invite admin -> Settings).
const LEGACY_TABS = { live: 'home', twin: 'map', invite: 'settings' }

function Redirect({ to }) {
  useEffect(() => navigate(to, { replace: true }), [to])
  return null
}

function FullScreenMessage({ children }) {
  return (
    <div className="flex h-svh items-center justify-center bg-slate-50 text-sm text-slate-500">{children}</div>
  )
}

function Dashboard({ tab, search }) {
  const { user, logout } = useAuth()

  const signOut = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  // Only one view is ever mounted at a time; each opens its own socket(s)
  // through its existing hook, and only once the session is authenticated.
  return (
    <AppShell active={tab} onNavigate={(id) => navigate(`/dashboard/${id}`)} user={user} onLogout={signOut}>
      {tab === 'home' && <DashboardTab />}
      {tab === 'map' && <GridMapTab search={search} />}
      {tab === 'sources' && <SourcesTab />}
      {tab === 'chain' && <RedistributionTab />}
      {tab === 'ai' && <AIInsightsTab />}
      {tab === 'analytics' && <AnalyticsTab />}
      {tab === 'settings' && <SettingsTab search={search} onLogout={signOut} />}
    </AppShell>
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
    const here = path.startsWith('/dashboard') ? path + search : '/dashboard/home'
    return <Redirect to={`/login?next=${encodeURIComponent(here)}`} />
  }

  const tab = path.match(/^\/dashboard\/([a-z]+)\/?$/)?.[1]
  if (LEGACY_TABS[tab]) {
    const view = tab === 'twin' ? '?view=twin' : tab === 'invite' ? '?tab=admins' : ''
    return <Redirect to={`/dashboard/${LEGACY_TABS[tab]}${view}`} />
  }
  if (!NAV.some((t) => t.id === tab)) return <Redirect to="/dashboard/home" />
  return <Dashboard tab={tab} search={search} />
}

function App() {
  return (
    <AuthProvider>
      <Routes />
    </AuthProvider>
  )
}

export default App
