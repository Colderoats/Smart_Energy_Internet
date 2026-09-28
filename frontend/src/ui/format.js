// Number / hash formatting shared by the SEI screens.

export function fmtNum(n, digits = 0) {
  if (n == null || Number.isNaN(n)) return '—'
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

export function shortHash(hash, n = 6) {
  if (!hash) return '—'
  return hash.length > 2 * n + 2 ? `${hash.slice(0, n + 2)}…${hash.slice(-n)}` : hash
}
