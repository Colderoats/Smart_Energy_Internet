import { Pill } from '../ui/components'

// Every number here is simulated; the real Kelmarsh results live on their own tab / endpoint.
export function SimPill({ className = '' }) {
  return (
    <Pill tone="info" dot={false} className={className}>
      Simulated
    </Pill>
  )
}

export function RealPill() {
  return (
    <Pill tone="ok" dot={false}>
      Real Kelmarsh SCADA (replayed)
    </Pill>
  )
}

export function Loading({ what }) {
  return <p className="py-8 text-center text-sm text-slate-500">Loading {what}…</p>
}

export function ErrorNote({ error }) {
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
      {error}
      <div className="mt-1 text-xs text-amber-700">Result files are generated offline by <span className="font-mono">experiments/run_all.py</span>; nothing here is invented client-side.</div>
    </div>
  )
}
