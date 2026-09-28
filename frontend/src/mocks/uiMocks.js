// UI mock adapter: the ONLY place the dashboard gets data that no backend
// endpoint exposes yet. Every export is tagged:
//   SNAPSHOT: real measured numbers copied from a repo artifact (static copy,
//             not fetched). Swap for an API when one exists.
//   MOCK:     invented placeholder. Replace with a real source. Screens show
//             a "Mock data" tag wherever a MOCK value is displayed.
// Listed in PROGRESS.md ("UI redesign" -> "Mocks").

// ---------------------------------------------------------------------------
// Federated learning (Grid Map -> Federated Learning tab)
// ---------------------------------------------------------------------------

// SNAPSHOT: backend/ai/federated/artifacts/runs/<run>/round_log.json, seed 3.
// Per-round mean client VALIDATION PR-AUC and mean client train loss.
// Used for the FedAvg vs FedProx + adaptive comparison (only the adaptive
// run is recorded on the ledger, so FedAvg's curve is only available here).
// Accuracy is deliberately not shown: with ~0.1% positive samples a model
// that never predicts a fault scores 99.9% accuracy (see RESULTS.md).
export const FL_RUN_SNAPSHOT = {
  source: 'backend/ai/federated/artifacts/runs/*_clean_s3/round_log.json (offline Module 4 run, seed 3)',
  totalRounds: 30,
  fedavgValPrAuc: [0.1283, 0.1166, 0.1014, 0.1384, 0.1318, 0.1217, 0.1186, 0.1149, 0.1061, 0.108, 0.1119, 0.1047, 0.1155, 0.1073, 0.1009, 0.1142, 0.1032, 0.1079, 0.1112, 0.0968, 0.1119, 0.0942, 0.0936, 0.0874, 0.0903, 0.0853, 0.0903, 0.0929, 0.092, 0.0821],
  adaptiveValPrAuc: [0.0188, 0.0863, 0.1116, 0.1211, 0.1226, 0.1246, 0.1266, 0.1205, 0.1251, 0.1224, 0.124, 0.1243, 0.1271, 0.1292, 0.1277, 0.1259, 0.1294, 0.1377, 0.141, 0.1438, 0.1441, 0.1456, 0.1457, 0.1483, 0.1417, 0.1387, 0.1393, 0.1395, 0.1449, 0.1404],
  adaptiveTrainLoss: [0.3875, 0.315, 0.299, 0.2905, 0.2861, 0.2802, 0.2719, 0.2704, 0.2674, 0.263, 0.2645, 0.2674, 0.257, 0.2635, 0.2564, 0.2578, 0.2526, 0.2533, 0.2542, 0.2491, 0.2555, 0.2562, 0.2463, 0.2522, 0.2496, 0.2495, 0.2491, 0.248, 0.2418, 0.2443],
  adaptiveValNormLoss: [1.7697, 1.2136, 1.0118, 0.9524, 0.9062, 0.8483, 1.044, 0.9564, 0.878, 0.9069, 0.8668, 0.8507, 0.8452, 0.8671, 0.8089, 0.792, 0.7931, 0.8411, 0.8177, 0.8035, 0.7984, 0.7816, 0.808, 0.9256, 0.804, 0.7586, 0.7948, 0.8286, 0.8144, 0.7919],
  // Adaptive per-client weights per round (same run; identical to the
  // FL_ROUND ledger records when those have been replayed).
  adaptiveWeights: [
    { T1: 0.05, T2: 0.3046, T3: 0.3227, T4: 0.3227 }, { T1: 0.05, T2: 0.3157, T3: 0.3172, T4: 0.3172 },
    { T1: 0.05, T2: 0.2742, T3: 0.3379, T4: 0.3379 }, { T1: 0.0508, T2: 0.276, T3: 0.3366, T4: 0.3366 },
    { T1: 0.0958, T2: 0.2819, T3: 0.3112, T4: 0.3112 }, { T1: 0.05, T2: 0.3288, T3: 0.2924, T4: 0.3288 },
    { T1: 0.1441, T2: 0.3053, T3: 0.2453, T4: 0.3053 }, { T1: 0.0738, T2: 0.3192, T3: 0.2879, T4: 0.3192 },
    { T1: 0.1134, T2: 0.3245, T3: 0.2375, T4: 0.3245 }, { T1: 0.0999, T2: 0.3316, T3: 0.2368, T4: 0.3316 },
    { T1: 0.1072, T2: 0.3201, T3: 0.2526, T4: 0.3201 }, { T1: 0.1285, T2: 0.318, T3: 0.2356, T4: 0.318 },
    { T1: 0.2116, T2: 0.2747, T3: 0.2391, T4: 0.2747 }, { T1: 0.1074, T2: 0.2935, T3: 0.2996, T4: 0.2996 },
    { T1: 0.0714, T2: 0.3387, T3: 0.2513, T4: 0.3387 }, { T1: 0.0925, T2: 0.3439, T3: 0.2196, T4: 0.3439 },
    { T1: 0.0748, T2: 0.3372, T3: 0.2507, T4: 0.3372 }, { T1: 0.1067, T2: 0.3199, T3: 0.2534, T4: 0.3199 },
    { T1: 0.1446, T2: 0.3009, T3: 0.2535, T4: 0.3009 }, { T1: 0.1853, T2: 0.2992, T3: 0.2164, T4: 0.2992 },
    { T1: 0.182, T2: 0.3047, T3: 0.2086, T4: 0.3047 }, { T1: 0.214, T2: 0.3099, T3: 0.1662, T4: 0.3099 },
    { T1: 0.1931, T2: 0.3042, T3: 0.1984, T4: 0.3042 }, { T1: 0.1511, T2: 0.2992, T3: 0.2504, T4: 0.2992 },
    { T1: 0.1179, T2: 0.3371, T3: 0.2079, T4: 0.3371 }, { T1: 0.0724, T2: 0.3519, T3: 0.2238, T4: 0.3519 },
    { T1: 0.1409, T2: 0.3142, T3: 0.2308, T4: 0.3142 }, { T1: 0.1063, T2: 0.3117, T3: 0.2702, T4: 0.3117 },
    { T1: 0.0877, T2: 0.327, T3: 0.2584, T4: 0.327 }, { T1: 0.1311, T2: 0.3182, T3: 0.2325, T4: 0.3182 },
  ],
}

// SNAPSHOT: backend/ai/federated/artifacts/partition_report.json
// (training samples per client shard; each client = one replayed turbine).
export const FL_CLIENTS = [
  { id: 'T1', nodeId: 'wind_scada_kelmarsh_1', localSamples: 96850 },
  { id: 'T2', nodeId: 'wind_scada_kelmarsh_2', localSamples: 98303 },
  { id: 'T3', nodeId: 'wind_scada_kelmarsh_3', localSamples: 97257 },
  { id: 'T4', nodeId: 'wind_scada_kelmarsh_4', localSamples: 97353 },
]

// SNAPSHOT: backend/ai/federated/artifacts/RESULTS.md, clean scenario,
// full-view test, mean over seeds 0-4. Honest numbers: test-set PR-AUC is at
// chance level (~0.0003) for every configuration; the gains are in the
// validation PR-AUC and ROC-AUC columns below.
export const FL_BASELINE_COMPARISON = [
  { metric: 'Validation PR-AUC', fedavg: 0.052, sei: 0.119 },
  { metric: 'Test ROC-AUC', fedavg: 0.256, sei: 0.392 },
  { metric: 'Fault localisation top-1', fedavg: 0.0, sei: 0.104 },
]

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

// MOCK: no consumption / load metering exists (no smart meters or EV
// hardware yet). Consumption is shown as a fixed share of generation.
// Replace with real metered demand.
export const MOCK_CONSUMPTION_RATIO = 0.82
export function mockConsumptionKw(generationKw) {
  return generationKw * MOCK_CONSUMPTION_RATIO
}

// ---------------------------------------------------------------------------
// AI Insights
// ---------------------------------------------------------------------------

// MOCK: TA-GNN is a fault forecaster; there is no demand-forecast model.
// 24 hourly points with an evening peak. Replace with a real demand model.
export function mockDemandForecast24h(now = new Date()) {
  const start = new Date(now)
  start.setMinutes(0, 0, 0)
  return Array.from({ length: 24 }, (_, i) => {
    const t = new Date(start.getTime() + i * 3600_000)
    const h = t.getHours()
    const base = 3200 + 900 * Math.sin(((h - 6) / 24) * 2 * Math.PI)
    const evening = h >= 18 && h <= 21 ? 1100 : 0
    return { hour: `${String(h).padStart(2, '0')}:00`, kw: Math.round(base + evening) }
  })
}

// ---------------------------------------------------------------------------
// Analytics
// ---------------------------------------------------------------------------

// MOCK: tariffs and emission factor are illustrative, not sourced.
export const MOCK_TARIFFS = { gridInrPerKwh: 8.5, seiInrPerKwh: 5.9 }
export const MOCK_CO2_TONNES_PER_MWH = 0.71

// MOCK: daily cost with SEI vs grid-only. No billing data exists.
export function mockCostSeries(days) {
  const out = []
  const today = new Date()
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today.getTime() - i * 86400_000)
    const kwh = 4200 + 700 * Math.sin(i / 3) + (i % 5) * 90
    out.push({
      label: d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }),
      grid: Math.round(kwh * MOCK_TARIFFS.gridInrPerKwh),
      sei: Math.round(kwh * MOCK_TARIFFS.seiInrPerKwh),
      kwh: Math.round(kwh),
    })
  }
  return out
}

// MOCK: share of demand still bought from the main grid, before vs with SEI.
export const MOCK_GRID_DEPENDENCY = { beforePct: 100, withSeiPct: 63 }

// MOCK: estimated downtime avoided per self-healing action (minutes). The
// twin reconfigures in software only; no outage duration is measured.
export const MOCK_DOWNTIME_MIN_PER_HEAL = 18

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

// MOCK: notification preferences are not stored anywhere yet (local state only).
export const MOCK_NOTIFICATION_PREFS = [
  { id: 'faults', label: 'Fault alerts', description: 'A node enters fault or fault-predicted state', on: true },
  { id: 'heal', label: 'Self-healing actions', description: 'The digital twin reroutes, isolates or curtails a node', on: true },
  { id: 'chain', label: 'Ledger confirmations', description: 'A record is confirmed on the blockchain', on: false },
  { id: 'fl', label: 'Federated rounds', description: 'A federated training round is recorded', on: false },
]
