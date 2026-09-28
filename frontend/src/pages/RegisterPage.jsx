import { useState } from 'react'
import { apiJson } from '../auth/api'
import { EMAIL_RE, MIN_LENGTH, passwordProblem } from '../auth/passwordPolicy'
import { navigate } from '../auth/router'
import { Alert, AuthCard, Field, SubmitButton } from './AuthForm'

export default function RegisterPage({ search }) {
  const token = new URLSearchParams(search).get('token') || ''
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState({})
  const [serverError, setServerError] = useState(null)
  const [busy, setBusy] = useState(false)

  if (!token) {
    return (
      <AuthCard title="Invite required">
        <div className="space-y-4">
          <Alert>
            Registration is invite-only. Open the full invite link you were given, or ask an existing admin for a new
            one.
          </Alert>
          <button onClick={() => navigate('/login')} className="text-sm text-sky-400 hover:text-sky-300">
            Go to sign in
          </button>
        </div>
      </AuthCard>
    )
  }

  const submit = async (e) => {
    e.preventDefault()
    const found = {}
    if (!EMAIL_RE.test(email.trim())) found.email = 'Enter a valid email address.'
    const problem = passwordProblem(password)
    if (problem) found.password = problem
    if (confirm !== password) found.confirm = 'Passwords do not match.'
    setErrors(found)
    setServerError(null)
    if (Object.keys(found).length) return
    setBusy(true)
    try {
      await apiJson('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ token, email: email.trim(), password }),
      })
      navigate('/login?registered=1', { replace: true })
    } catch (err) {
      setServerError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard title="Create your admin account" subtitle="This invite link works once and expires after 48 hours.">
      <form onSubmit={submit} noValidate className="space-y-4">
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
          label={`Password (at least ${MIN_LENGTH} characters)`}
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
        />
        <Field
          label="Repeat password"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          error={errors.confirm}
        />
        <SubmitButton busy={busy} busyLabel="Creating account…">
          Create account
        </SubmitButton>
      </form>
    </AuthCard>
  )
}
