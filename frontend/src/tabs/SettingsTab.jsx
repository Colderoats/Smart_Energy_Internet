import { useEffect, useState } from 'react'
import { apiFetch } from '../auth/api'
import { useAuth } from '../auth/AuthContext'
import { MIN_LENGTH } from '../auth/passwordPolicy'
import InviteAdminPage from '../pages/InviteAdminPage'
import { Avatar, displayName } from '../ui/AppShell'
import Icon from '../ui/icons'
import { Button, Card, MockTag, Pill, Tabs } from '../ui/components'
import { MOCK_NOTIFICATION_PREFS } from '../mocks/uiMocks'

// Settings: admin profile + tabs. Profile data is GET /auth/me (via
// useAuth). "Admins" is the existing Invite admin page, unchanged. System
// status uses existing endpoints, fetched once on open (no polling).
// There is no profile-update or notification-preferences endpoint yet.

const TABS = [
  { id: 'profile', label: 'Profile' },
  { id: 'security', label: 'Security' },
  { id: 'notifications', label: 'Notifications' },
  { id: 'system', label: 'System' },
  { id: 'admins', label: 'Admins' },
]

function fmtDate(iso) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' }) : '—'
}

function Row({ label, children }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-800">{children}</span>
    </div>
  )
}

function ProfileCard({ user }) {
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-5 pt-2">
        <Avatar email={user?.email} size={72} />
        <div className="min-w-0 flex-1">
          <div className="text-xl font-semibold text-slate-900">{displayName(user?.email) || 'Admin'}</div>
          <div className="text-sm text-slate-500">{user?.email}</div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Pill tone="info" dot={false}>
              {user?.role ?? 'admin'}
            </Pill>
            <span className="text-sm text-slate-500">Member since {fmtDate(user?.created_at)}</span>
          </div>
        </div>
        <Button variant="secondary" disabled title="Not available yet: the backend has no profile-update endpoint">
          Edit Profile
        </Button>
      </div>
    </Card>
  )
}

function ProfileTab({ user }) {
  return (
    <Card title="Account details">
      <div className="divide-y divide-slate-100">
        <Row label="Name">{displayName(user?.email) || '—'}</Row>
        <Row label="Email">{user?.email}</Row>
        <Row label="Role">{user?.role}</Row>
        <Row label="Member since">{fmtDate(user?.created_at)}</Row>
        <Row label="Last sign-in">{user?.last_login_at ? new Date(user.last_login_at).toLocaleString() : '—'}</Row>
      </div>
    </Card>
  )
}

function SecurityTab({ onLogout }) {
  return (
    <Card title="Security" subtitle="How your admin session is protected">
      <div className="divide-y divide-slate-100">
        <Row label="Password">At least {MIN_LENGTH} characters, not a common password</Row>
        <Row label="Failed sign-ins">Locked for 15 min after 5 attempts</Row>
        <Row label="Session">15 min access token, renewed automatically for 7 days</Row>
        <Row label="Token storage">HttpOnly cookies only</Row>
        <Row label="Two-factor authentication">
          <Pill tone="idle">Not available yet</Pill>
        </Row>
      </div>
      <div className="mt-4">
        <Button variant="danger" onClick={onLogout}>
          <Icon name="logout" size={16} /> Log out of this device
        </Button>
      </div>
    </Card>
  )
}

function NotificationsTab() {
  const [prefs, setPrefs] = useState(MOCK_NOTIFICATION_PREFS)
  return (
    <Card title="Notifications" subtitle="Which events should alert you" action={<MockTag label="Not saved yet" />}>
      <ul className="divide-y divide-slate-100">
        {prefs.map((p) => (
          <li key={p.id} className="flex items-center justify-between gap-4 py-3">
            <div>
              <div className="text-sm font-medium text-slate-800">{p.label}</div>
              <div className="text-sm text-slate-500">{p.description}</div>
            </div>
            <button
              role="switch"
              aria-checked={p.on}
              aria-label={p.label}
              onClick={() => setPrefs((all) => all.map((x) => (x.id === p.id ? { ...x, on: !x.on } : x)))}
              className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${p.on ? 'bg-indigo-600' : 'bg-slate-300'}`}
            >
              <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${p.on ? 'left-[22px]' : 'left-0.5'}`} />
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function useSystemStatus() {
  const [s, setS] = useState({ health: undefined, chain: undefined, ai: undefined })
  useEffect(() => {
    let cancelled = false
    const get = (url, key) =>
      apiFetch(url)
        .then((res) => (res.ok ? res.json() : null))
        .catch(() => null)
        .then((data) => !cancelled && setS((prev) => ({ ...prev, [key]: data })))
    get('/health', 'health')
    get('/chain/status?check_integrity=false', 'chain')
    get('/ai/predictions', 'ai')
    return () => {
      cancelled = true
    }
  }, [])
  return s
}

function SystemTab() {
  const { health, chain, ai } = useSystemStatus()
  const status = (v, ok, label) => (v === undefined ? <Pill tone="idle">Checking…</Pill> : ok ? <Pill>Online</Pill> : <Pill>{label ?? 'Offline'}</Pill>)
  const services = [
    { name: 'Backend API', detail: 'FastAPI', icon: 'server', el: status(health, health?.status === 'ok') },
    { name: 'Database', detail: 'TimescaleDB', icon: 'server', el: status(health, health?.db === 'connected') },
    {
      name: 'Blockchain ledger',
      detail: chain ? `${chain.network_label ?? chain.network ?? ''}` : 'EnergyLedger contract',
      icon: 'block',
      el: status(chain, chain?.connected, chain?.enabled === false ? 'Disabled' : 'Offline'),
    },
    {
      name: 'AI model',
      detail: ai?.model?.name ? `${ai.model.name}${ai.model.source ? ` · ${ai.model.source}` : ''}` : 'TA-GNN',
      icon: 'brain',
      el: status(ai, ai?.model?.loaded, 'Not loaded'),
    },
    { name: 'Live data', detail: 'Open-Meteo API (wind/hydro) + Kelmarsh SCADA replay', icon: 'pulse', el: <Pill tone="idle" dot={false}>See Dashboard</Pill> },
  ]
  return (
    <Card title="Connected services" subtitle="Checked when this tab opened">
      <ul className="divide-y divide-slate-100">
        {services.map((s) => (
          <li key={s.name} className="flex items-center justify-between gap-4 py-3">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                <Icon name={s.icon} size={18} />
              </span>
              <div>
                <div className="text-sm font-medium text-slate-800">{s.name}</div>
                <div className="text-sm text-slate-500">{s.detail}</div>
              </div>
            </div>
            {s.el}
          </li>
        ))}
      </ul>
    </Card>
  )
}

export default function SettingsTab({ search, onLogout }) {
  const { user } = useAuth()
  const initial = new URLSearchParams(search).get('tab')
  const [tab, setTab] = useState(TABS.some((t) => t.id === initial) ? initial : 'profile')

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <ProfileCard user={user} />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === 'profile' && <ProfileTab user={user} />}
      {tab === 'security' && <SecurityTab onLogout={onLogout} />}
      {tab === 'notifications' && <NotificationsTab />}
      {tab === 'system' && <SystemTab />}
      {tab === 'admins' && <InviteAdminPage />}
    </div>
  )
}
