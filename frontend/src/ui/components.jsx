import { useState } from 'react'
import Icon from './icons'

// Shared presentation primitives. Light content area, rounded 14px cards,
// soft shadows, 14px+ body text, large key numbers with small muted labels.

export function Card({ title, subtitle, action, children, className = '', bodyClassName = '' }) {
  return (
    <section className={`rounded-2xl border border-slate-200 bg-white shadow-[0_1px_3px_rgba(15,23,42,0.06)] ${className}`}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 px-5 pt-4">
          <div>
            {title && <h2 className="text-[15px] font-semibold text-slate-800">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={`px-5 pb-5 pt-3 ${bodyClassName}`}>{children}</div>
    </section>
  )
}

export function StatCard({ label, value, unit, icon, color = '#4f46e5', hint, mock }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_1px_3px_rgba(15,23,42,0.06)]">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-500">{label}</span>
        {icon && (
          <span className="flex h-9 w-9 items-center justify-center rounded-xl" style={{ background: `${color}1a`, color }}>
            <Icon name={icon} size={18} />
          </span>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="text-[30px] font-semibold leading-none tracking-tight text-slate-900">{value}</span>
        {unit && <span className="text-sm font-medium text-slate-500">{unit}</span>}
      </div>
      {(hint || mock) && (
        <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
          {mock && <MockTag />}
          {hint && <span>{hint}</span>}
        </div>
      )}
    </div>
  )
}

const PILL_TONES = {
  ok: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  warn: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  bad: 'bg-red-50 text-red-700 ring-red-600/20',
  idle: 'bg-slate-100 text-slate-600 ring-slate-500/20',
  info: 'bg-indigo-50 text-indigo-700 ring-indigo-600/20',
  chain: 'bg-violet-50 text-violet-700 ring-violet-600/20',
}

// Status pill. Named statuses map to a tone; anything else passes `tone`.
const NAMED = {
  Online: 'ok',
  Offline: 'bad',
  Training: 'info',
  Charging: 'warn',
  Sold: 'ok',
  'Not sold': 'bad',
  Pending: 'warn',
}

export function Pill({ children, tone, dot = true, className = '' }) {
  const t = tone ?? NAMED[children] ?? 'idle'
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${PILL_TONES[t]} ${className}`}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />}
      {children}
    </span>
  )
}

// Marks a value that comes from src/mocks/uiMocks.js, not a real source.
export function MockTag({ label = 'Mock data' }) {
  return (
    <span
      className="rounded-md border border-dashed border-slate-300 px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide text-slate-500"
      title="Placeholder from src/mocks/uiMocks.js, not from a real data source yet"
    >
      {label}
    </span>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="inline-flex rounded-xl bg-slate-100 p-1" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`rounded-lg px-4 py-1.5 text-sm font-medium transition-colors ${
            value === t.id ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

// Secondary information lives behind this expander.
export function Details({ label = 'Details', children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-700"
        aria-expanded={open}
      >
        {label}
        <Icon name="chevron" size={16} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  )
}

export function EmptyState({ icon = 'pulse', children }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-8 text-center text-sm text-slate-500">
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-400">
        <Icon name={icon} size={20} />
      </span>
      <div className="max-w-sm">{children}</div>
    </div>
  )
}

export function CopyButton({ text, label = 'Copy' }) {
  const [done, setDone] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setDone(true)
      setTimeout(() => setDone(false), 1500)
    } catch {
      /* clipboard blocked: the full value is in the title tooltip */
    }
  }
  return (
    <button
      onClick={copy}
      title={done ? 'Copied' : `${label}: ${text}`}
      className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700"
      aria-label={label}
    >
      <Icon name={done ? 'check' : 'copy'} size={15} />
    </button>
  )
}

export function Segmented({ options, value, onChange, size = 'md' }) {
  const pad = size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-sm'
  return (
    <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
      {options.map((o) => (
        <button
          key={o.id}
          onClick={() => onChange(o.id)}
          className={`rounded-md font-medium transition-colors ${pad} ${
            value === o.id ? 'bg-indigo-600 text-white' : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Button({ children, variant = 'primary', className = '', ...props }) {
  const styles = {
    primary: 'bg-indigo-600 text-white hover:bg-indigo-500',
    secondary: 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50',
    ghost: 'text-indigo-600 hover:bg-indigo-50',
    danger: 'border border-red-300 bg-white text-red-700 hover:bg-red-50',
  }[variant]
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    >
      {children}
    </button>
  )
}
