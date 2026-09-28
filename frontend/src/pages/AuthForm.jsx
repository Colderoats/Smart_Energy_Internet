// Shared pieces for the /login and /register screens (light SEI styling).

export function AuthCard({ title, subtitle, children }) {
  return (
    <div className="flex min-h-svh items-center justify-center bg-slate-50 px-4 text-slate-800">
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-7 shadow-[0_8px_30px_rgba(15,23,42,0.08)]">
        <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">Smart Energy Internet</p>
        <h1 className="mt-1 text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
        <div className="mt-6">{children}</div>
      </div>
    </div>
  )
}

export function Field({ label, error, ...props }) {
  return (
    <label className="block text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      <input
        {...props}
        aria-invalid={error ? 'true' : 'false'}
        className={`mt-1.5 w-full rounded-xl border bg-white px-3.5 py-2.5 text-[15px] text-slate-900 outline-none transition-shadow placeholder:text-slate-400 focus:ring-4 focus:ring-indigo-100 ${
          error ? 'border-red-400 focus:border-red-500' : 'border-slate-300 focus:border-indigo-500'
        }`}
      />
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
    </label>
  )
}

export function Alert({ kind = 'error', children }) {
  const styles =
    kind === 'error' ? 'border-red-200 bg-red-50 text-red-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`rounded-xl border px-3.5 py-2.5 text-sm ${styles}`}>
      {children}
    </div>
  )
}

export function SubmitButton({ busy, children, busyLabel }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="w-full rounded-xl bg-indigo-600 px-3 py-2.5 text-[15px] font-semibold text-white shadow-sm transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {busy ? busyLabel : children}
    </button>
  )
}
