// SEI design tokens. Colour = meaning, used the same way on every screen:
// energy sources have fixed hues; green/amber/red are reserved for status;
// violet is blockchain; indigo is the single UI accent.

export const SOURCE_COLORS = {
  solar: '#f59e0b', // amber
  wind: '#14b8a6', // teal
  hydro: '#3b82f6', // blue
  grid: '#64748b', // slate
  storage: '#64748b',
  bus: '#64748b',
}

export const STATUS_COLORS = {
  ok: '#16a34a',
  warn: '#d97706',
  bad: '#dc2626',
  idle: '#94a3b8',
}

export const CHAIN_COLOR = '#7c3aed' // violet
export const ACCENT = '#4f46e5' // indigo

export const SOURCE_LABELS = { solar: 'Solar', wind: 'Wind', hydro: 'Hydro', grid: 'Grid', bus: 'Bus' }

// health_status -> status tone used by pills, rings and node borders.
export const HEALTH_TONE = {
  normal: 'ok',
  warning: 'warn',
  fault_predicted: 'warn',
  fault: 'bad',
}

export const HEALTH_LABEL = {
  normal: 'Normal',
  warning: 'Warning',
  fault_predicted: 'Fault predicted',
  fault: 'Fault',
}

// Friendly display names for twin node ids (ids themselves are unchanged
// everywhere else). "Replayed" = Kelmarsh SCADA replay, never live.
export function nodeLabel(id) {
  if (!id) return '—'
  const m = id.match(/^wind_scada_kelmarsh_(\d+)$/)
  if (m) return `Kelmarsh T${m[1]}`
  return (
    {
      wind_01: 'Wind farm (live)',
      hydro_01: 'Hydro plant (live)',
      bus_a: 'Bus A',
      bus_b: 'Bus B',
      grid: 'Main grid',
      federated_server: 'FL server',
    }[id] ?? id
  )
}

// Recharts shared styling for the light theme.
export const CHART = {
  grid: '#e2e8f0',
  axis: '#64748b',
  tooltip: {
    contentStyle: {
      background: '#ffffff',
      border: '1px solid #e2e8f0',
      borderRadius: 12,
      fontSize: 13,
      boxShadow: '0 4px 12px rgba(15,23,42,0.08)',
    },
  },
}
