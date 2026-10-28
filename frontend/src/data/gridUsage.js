// SAMPLE DATASET: 7 days of hourly usage (kW) for the two main grids. SYNTHETIC and illustrative,
// not metered: a daily cycle + evening peak + weekend dip + seeded noise (deterministic, same every load).
// The forecast below is a plain seasonal average, not a trained model.

export const USAGE_PROVENANCE = 'Synthetic sample · 7 days hourly · not metered'
export const GRIDS = [
  { id: 'grid_1', label: 'Main grid', base: 3200, amp: 900, evening: 1100 },
  { id: 'grid_2', label: 'Main grid 2', base: 1500, amp: 420, evening: 520 },
]

function rng(seed) {
  let s = seed
  return () => ((s = (s * 1664525 + 1013904223) % 4294967296) / 4294967296) - 0.5
}

// usage[gridId] = 168 hourly values (day-major).
export const USAGE = Object.fromEntries(
  GRIDS.map((g, gi) => {
    const noise = rng(7 + gi)
    const vals = []
    for (let d = 0; d < 7; d++) {
      for (let h = 0; h < 24; h++) {
        let v = g.base + g.amp * Math.sin(((h - 6) / 24) * 2 * Math.PI) + (h >= 18 && h <= 21 ? g.evening : 0)
        if (d >= 5) v *= 0.92
        vals.push(Math.round(v + noise() * g.base * 0.06))
      }
    }
    return [g.id, vals]
  }),
)

const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length

// Seasonal-average forecast of the next 24 h from `history` (whole days, hourly): mean of each hour across days,
// scaled by how the latest day ran vs the all-day average (a simple level/trend correction).
export function forecastNextDay(history) {
  const days = history.length / 24
  const hourMean = Array.from({ length: 24 }, (_, h) => mean(Array.from({ length: days }, (_, d) => history[d * 24 + h])))
  const last = history.slice(-24)
  const scale = mean(last) / mean(hourMean)
  return hourMean.map((v) => Math.round(v * scale))
}

// Backtest: forecast the final day from the 6 days before it; return mean absolute % error.
export function backtestMape(history) {
  const pred = forecastNextDay(history.slice(0, -24))
  const actual = history.slice(-24)
  return mean(actual.map((a, i) => Math.abs(a - pred[i]) / a)) * 100
}
