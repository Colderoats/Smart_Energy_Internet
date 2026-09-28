import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { EMAIL_RE } from '../auth/passwordPolicy'
import { navigate, safeNext } from '../auth/router'
import { Alert, Field, SubmitButton } from './AuthForm'

// Registration is invite-only. The inline "Register?" section accepts the
// full invite link or just its token and hands off to the existing
// /register?token= flow (RegisterPage), which validates it with the backend.
function parseInvite(value) {
  const v = value.trim()
  if (!v) return null
  try {
    const url = new URL(v, window.location.origin)
    const token = url.searchParams.get('token')
    if (token) return token
  } catch {
    /* not a URL: treat as a raw token */
  }
  return /^[A-Za-z0-9_-]{16,}$/.test(v) ? v : null
}

function RegisterInline() {
  const [open, setOpen] = useState(false)
  const [invite, setInvite] = useState('')
  const [error, setError] = useState(null)

  const go = (e) => {
    e.preventDefault()
    const token = parseInvite(invite)
    if (!token) {
      setError('Paste the full invite link you were sent, or its token.')
      return
    }
    navigate(`/register?token=${encodeURIComponent(token)}`)
  }

  return (
    <div className="border-t border-slate-200 pt-5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="text-sm font-medium text-indigo-600 hover:text-indigo-700"
      >
        Register?
      </button>
      {open && (
        <form onSubmit={go} noValidate className="mt-3 space-y-3">
          <p className="text-sm text-slate-500">
            Registration is invite-only. Paste the invite link an existing admin sent you.
          </p>
          <Field
            label="Invite link or token"
            value={invite}
            onChange={(e) => {
              setInvite(e.target.value)
              setError(null)
            }}
            placeholder="http://…/register?token=…"
            error={error}
            autoFocus
          />
          <button
            type="submit"
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-[15px] font-semibold text-slate-700 hover:bg-slate-50"
          >
            Continue
          </button>
        </form>
      )}
    </div>
  )
}

// Hero illustration: inline SVG (no external images). City at dusk with a
// solar array, wind turbines and a flowing power line.
function HeroArt() {
  const turbine = (x, y, s, dur) => (
    <g transform={`translate(${x} ${y}) scale(${s})`}>
      <path d="M-3 0 L3 0 L1.5 -120 L-1.5 -120 Z" fill="#e2e8f0" />
      <g transform="translate(0 -120)">
        <g>
          <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur={dur} repeatCount="indefinite" />
          {[0, 120, 240].map((a) => (
            <path key={a} transform={`rotate(${a})`} d="M0 0 L-4 -6 L0 -62 L4 -6 Z" fill="#f8fafc" />
          ))}
        </g>
        <circle r="5" fill="#cbd5e1" />
      </g>
    </g>
  )
  return (
    <svg viewBox="0 0 600 380" className="h-auto w-full" role="img" aria-label="Wind turbines and solar panels beside a city at dusk">
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#1e1b4b" />
          <stop offset="0.55" stopColor="#6d28d9" />
          <stop offset="1" stopColor="#f59e0b" />
        </linearGradient>
        <linearGradient id="panel" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1d4ed8" />
          <stop offset="1" stopColor="#0f172a" />
        </linearGradient>
      </defs>
      <rect width="600" height="380" rx="24" fill="url(#sky)" />
      <circle cx="455" cy="250" r="46" fill="#fbbf24" opacity="0.9" />
      {/* city skyline */}
      <g fill="#0f172a" opacity="0.9">
        <rect x="300" y="210" width="36" height="110" />
        <rect x="340" y="180" width="28" height="140" />
        <rect x="372" y="225" width="40" height="95" />
        <rect x="416" y="195" width="24" height="125" />
        <rect x="444" y="240" width="46" height="80" />
        <rect x="494" y="205" width="30" height="115" />
        <rect x="528" y="230" width="44" height="90" />
      </g>
      <g fill="#fde68a">
        {[
          [308, 222], [322, 240], [348, 196], [356, 226], [380, 240], [396, 262], [422, 210], [452, 256], [470, 272], [502, 220], [510, 250], [538, 246], [556, 266],
        ].map(([x, y]) => (
          <rect key={`${x}-${y}`} x={x} y={y} width="5" height="7" rx="1" />
        ))}
      </g>
      {/* ground */}
      <path d="M0 318 Q150 296 300 312 T600 314 V380 H0 Z" fill="#0b1733" />
      {turbine(80, 318, 1.05, '7s')}
      {turbine(165, 312, 0.8, '5.5s')}
      {turbine(235, 316, 0.62, '6.3s')}
      {/* solar array */}
      <g transform="translate(40 330)">
        {[0, 1, 2, 3].map((i) => (
          <g key={i} transform={`translate(${i * 58} 0) skewX(-18)`}>
            <rect width="50" height="24" rx="2" fill="url(#panel)" stroke="#93c5fd" strokeWidth="0.8" />
            <path d="M12.5 0V24M25 0V24M37.5 0V24M0 12H50" stroke="#93c5fd" strokeWidth="0.5" opacity="0.7" />
          </g>
        ))}
      </g>
      {/* power line to the city */}
      <path id="line" d="M270 340 C330 330 360 330 420 322" stroke="#fbbf24" strokeWidth="2" fill="none" strokeDasharray="4 6" opacity="0.8" />
      <circle r="4" fill="#fde68a">
        <animateMotion dur="2.4s" repeatCount="indefinite" path="M270 340 C330 330 360 330 420 322" />
      </circle>
    </svg>
  )
}

const CHIPS = ['IoT', 'Digital Twin', 'AI', 'Blockchain']

export default function LoginPage({ search }) {
  const { login } = useAuth()
  const params = new URLSearchParams(search)
  const next = safeNext(params.get('next'))
  const registered = params.get('registered') === '1'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState({})
  const [serverError, setServerError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    const found = {}
    if (!EMAIL_RE.test(email.trim())) found.email = 'Enter a valid email address.'
    if (!password) found.password = 'Enter your password.'
    setErrors(found)
    setServerError(null)
    if (Object.keys(found).length) return
    setBusy(true)
    try {
      await login(email.trim(), password)
      navigate(next, { replace: true })
    } catch (err) {
      setServerError(
        err.status === 401
          ? 'Invalid credentials. After 5 failed attempts the account is locked for 15 minutes.'
          : err.message,
      )
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-svh bg-white lg:grid-cols-2">
      {/* LEFT: brand + hero */}
      <div className="flex flex-col justify-center gap-8 bg-[#0b1733] px-8 py-12 text-white lg:px-14">
        <div>
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500 text-sm font-bold">SEI</span>
          <h1 className="mt-6 text-3xl font-bold tracking-[0.08em] sm:text-4xl">SMART ENERGY INTERNET</h1>
          <p className="mt-2 text-lg text-slate-300">Path to a sustainable future</p>
        </div>
        <HeroArt />
        <div className="flex flex-wrap gap-2">
          {CHIPS.map((c) => (
            <span key={c} className="rounded-full border border-white/15 bg-white/5 px-3.5 py-1 text-sm font-medium text-slate-200">
              {c}
            </span>
          ))}
        </div>
      </div>

      {/* RIGHT: login */}
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <h2 className="text-3xl font-semibold text-slate-900">Login</h2>
          <p className="mt-1.5 text-sm text-slate-500">Access is limited to registered administrators.</p>
          <form onSubmit={submit} noValidate className="mt-8 space-y-5">
            {registered && <Alert kind="ok">Account created. Sign in with your new credentials.</Alert>}
            {serverError && <Alert>{serverError}</Alert>}
            <Field
              label="Email or username"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              error={errors.email}
              placeholder="you@example.com"
              autoFocus
            />
            <Field
              label="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              error={errors.password}
              placeholder="••••••••••••"
            />
            <SubmitButton busy={busy} busyLabel="Signing in…">
              Login
            </SubmitButton>
          </form>
          <div className="mt-6">
            <RegisterInline />
          </div>
        </div>
      </div>
    </div>
  )
}
