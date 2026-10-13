// Number formatting for the testbed views.
// mean ± std with sensible digits
export function fmt(v, unit = '', digits) {
  if (v == null || Number.isNaN(v)) return '—'
  const a = Math.abs(v)
  const d = digits ?? (a >= 1000 ? 0 : a >= 100 ? 1 : a >= 10 ? 2 : a >= 1 ? 3 : 4)
  return `${Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: 0 })}${unit && unit !== '' ? ` ${unit}` : ''}`
}
