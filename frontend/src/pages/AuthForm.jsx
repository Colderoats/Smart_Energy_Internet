// Shared pieces for the /login and /register screens (dashboard styling).

export function AuthCard({ title, subtitle, children }) {
  return (
    <div className="flex min-h-svh items-center justify-center bg-slate-950 px-4 text-slate-100">
      <div className="w-full max-w-sm rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
        <p className="text-xs font-medium uppercase tracking-wide text-sky-400">Smart Energy Internet</p>
        <h1 className="mt-1 text-lg font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
        <div className="mt-5">{children}</div>
      </div>
    </div>
  )
}

export function Field({ label, error, ...props }) {
  return (
    <label className="block text-sm">
      <span className="text-slate-300">{label}</span>
      <input
        {...props}
        aria-invalid={error ? 'true' : 'false'}
        className={`mt-1 w-full rounded-md border bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:ring-2 focus:ring-sky-600 ${
          error ? 'border-red-500' : 'border-slate-700'
        }`}
      />
      {error && <span className="mt-1 block text-xs text-red-300">{error}</span>}
    </label>
  )
}

export function Alert({ kind = 'error', children }) {
  const styles =
    kind === 'error'
      ? 'border-red-800 bg-red-950/60 text-red-200'
      : 'border-emerald-800 bg-emerald-950/60 text-emerald-200'
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`rounded-md border px-3 py-2 text-sm ${styles}`}>
      {children}
    </div>
  )
}

export function SubmitButton({ busy, children, busyLabel }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="w-full rounded-md bg-sky-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {busy ? busyLabel : children}
    </button>
  )
}
