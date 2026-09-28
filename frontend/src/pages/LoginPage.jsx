import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { EMAIL_RE } from '../auth/passwordPolicy'
import { navigate, safeNext } from '../auth/router'
import { Alert, AuthCard, Field, SubmitButton } from './AuthForm'

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
    <AuthCard title="Admin sign in" subtitle="Access is limited to registered administrators.">
      <form onSubmit={submit} noValidate className="space-y-4">
        {registered && <Alert kind="ok">Account created. Sign in with your new credentials.</Alert>}
        {serverError && <Alert>{serverError}</Alert>}
        <Field
          label="Email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={errors.email}
          autoFocus
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
        />
        <SubmitButton busy={busy} busyLabel="Signing in…">
          Sign in
        </SubmitButton>
        <p className="text-xs text-slate-500">New admins join through an invite link from an existing admin.</p>
      </form>
    </AuthCard>
  )
}
