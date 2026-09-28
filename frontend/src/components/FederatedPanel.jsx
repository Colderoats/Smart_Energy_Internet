import { useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useBlockchainSocket } from '../hooks/useBlockchainSocket'
import { useReportConnection } from '../ui/AppShell'
import Icon from '../ui/icons'
import { Button, Card, Details, Pill } from '../ui/components'
import { fmtNum } from '../ui/format'
import { ACCENT, CHART, SOURCE_COLORS, nodeLabel } from '../ui/theme'
import { FL_CLIENTS, FL_RUN_SNAPSHOT } from '../mocks/uiMocks'

// Federated Learning view. Training itself runs OFFLINE (Module 4, Flower);
// this panel REPLAYS that run round by round so the process is visible.
// Per-round client weights come from the FL_ROUND ledger records
// (GET /chain/records?event_type=FL_ROUND, recorded from round_log.json) when
// they exist, otherwise from the same run's snapshot in src/mocks/uiMocks.js.
// FedAvg's comparison curve and the train-loss curve are snapshot-only
// (not exposed by any endpoint).

const PHASES = [
  { id: 'training', label: 'Training locally', ms: 1800 },
  { id: 'uploading', label: 'Uploading updates', ms: 1300 },
  { id: 'aggregating', label: 'Aggregating (FedProx)', ms: 900 },
  { id: 'broadcast', label: 'Sending global model', ms: 1300 },
]

const NODE_STATUS = {
  training: { label: 'Training locally', tone: 'info' },
  uploading: { label: 'Uploading', tone: 'warn' },
  aggregating: { label: 'Aggregated', tone: 'ok' },
  broadcast: { label: 'Aggregated', tone: 'ok' },
  idle: { label: 'Idle', tone: 'idle' },
}

function useRounds() {
  const { records, connected } = useBlockchainSocket('FL_ROUND')
  const fromLedger = useMemo(() => {
    const byRound = new Map()
    for (const r of records) {
      const p = r.payload
      if (!p?.round) continue
      if (!byRound.has(p.round)) byRound.set(p.round, { p, record: r })
    }
    return [...byRound.values()]
      .sort((a, b) => a.p.round - b.p.round)
      .map(({ p, record }) => ({
        round: p.round,
        total: p.total_rounds,
        strategy: p.strategy_label,
        weights: p.client_weights ?? {},
        participants: p.participants ?? [],
        dropped: p.simulated_dropped_clients ?? [],
        valPrAuc: p.mean_val_pr_auc,
        updatedAt: record.created_at,
        blockNumber: record.block_number,
      }))
  }, [records])

  if (fromLedger.length > 0) return { rounds: fromLedger, source: 'ledger', connected }
  const snap = FL_RUN_SNAPSHOT
  return {
    source: 'snapshot',
    connected,
    rounds: snap.adaptiveWeights.map((w, i) => ({
      round: i + 1,
      total: snap.totalRounds,
      strategy: 'FedProx + adaptive weighting',
      weights: w,
      participants: Object.keys(w),
      dropped: [],
      valPrAuc: snap.adaptiveValPrAuc[i],
      updatedAt: null,
      blockNumber: null,
    })),
  }
}

function usePlayback(count) {
  const [idx, setIdx] = useState(0)
  const [phase, setPhase] = useState(0)
  const [playing, setPlaying] = useState(true)
  useEffect(() => {
    if (!playing || count === 0) return
    const t = setTimeout(() => {
      if (phase < PHASES.length - 1) setPhase(phase + 1)
      else {
        setPhase(0)
        setIdx((i) => (i + 1) % count)
      }
    }, PHASES[phase].ms)
    return () => clearTimeout(t)
  }, [playing, phase, count])
  return { idx: Math.min(idx, Math.max(0, count - 1)), phase: PHASES[phase].id, playing, setPlaying, setIdx, setPhase }
}

// Hub-and-spoke diagram. Client circle size scales with its adaptive weight.
function FederationDiagram({ round, phase }) {
  const W = 560
  const H = 340
  const hub = { x: W / 2, y: H / 2 }
  const spots = [
    { x: 95, y: 70 },
    { x: W - 95, y: 70 },
    { x: 95, y: H - 70 },
    { x: W - 95, y: H - 70 },
  ]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Federated training round diagram">
      {FL_CLIENTS.map((c, i) => {
        const s = spots[i]
        const active = round.participants.includes(c.id)
        const up = `M${s.x} ${s.y} L${hub.x} ${hub.y}`
        const down = `M${hub.x} ${hub.y} L${s.x} ${s.y}`
        return (
          <g key={c.id}>
            <line x1={s.x} y1={s.y} x2={hub.x} y2={hub.y} stroke="#cbd5e1" strokeWidth="2" strokeDasharray={active ? '0' : '4 5'} />
            {active && phase === 'uploading' && (
              <circle key={`u-${round.round}`} r="6" fill="#d97706">
                <animateMotion dur="1.2s" repeatCount="1" fill="freeze" path={up} />
              </circle>
            )}
            {active && phase === 'broadcast' && (
              <circle key={`d-${round.round}`} r="6" fill={ACCENT}>
                <animateMotion dur="1.2s" repeatCount="1" fill="freeze" path={down} />
              </circle>
            )}
          </g>
        )
      })}

      {/* global model hub */}
      <circle cx={hub.x} cy={hub.y} r="52" fill="#eef2ff" stroke={ACCENT} strokeWidth={phase === 'aggregating' ? 4 : 2} />
      <text x={hub.x} y={hub.y - 6} textAnchor="middle" fontSize="14" fontWeight="600" fill="#312e81">
        Global Model
      </text>
      <text x={hub.x} y={hub.y + 14} textAnchor="middle" fontSize="12" fill="#4f46e5">
        (FedProx)
      </text>

      {FL_CLIENTS.map((c, i) => {
        const s = spots[i]
        const w = round.weights[c.id] ?? 0
        const active = round.participants.includes(c.id)
        const r = 20 + 60 * w // weight 0.05 -> 23px, 0.35 -> 41px
        const status = active ? phase : 'idle'
        const ringColor = { training: ACCENT, uploading: '#d97706', aggregating: '#16a34a', broadcast: '#16a34a', idle: '#94a3b8' }[status]
        return (
          <g key={c.id}>
            <circle cx={s.x} cy={s.y} r={r} fill="#ffffff" stroke="#e2e8f0" strokeWidth="1.5" />
            <circle
              cx={s.x}
              cy={s.y}
              r={r + 6}
              fill="none"
              stroke={ringColor}
              strokeWidth="3"
              strokeDasharray={status === 'training' ? '10 7' : '0'}
              className={status === 'training' ? 'sei-spin' : ''}
            />
            <text x={s.x} y={s.y + 5} textAnchor="middle" fontSize="15" fontWeight="700" fill={SOURCE_COLORS.wind}>
              {c.id}
            </text>
            <text x={s.x} y={s.y + r + 24} textAnchor="middle" fontSize="12" fill="#475569">
              {`${(w * 100).toFixed(0)}% weight`}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function WeightsTable({ round, source }) {
  const max = Math.max(...Object.values(round.weights), 0.0001)
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs uppercase tracking-wide text-slate-500">
        <tr className="border-b border-slate-200">
          <th className="py-2.5 pr-3 font-medium">Node</th>
          <th className="w-[40%] py-2.5 pr-3 font-medium">Adaptive weight</th>
          <th className="py-2.5 pr-3 text-right font-medium">Local samples</th>
          <th className="py-2.5 font-medium">Last update</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {FL_CLIENTS.map((c) => {
          const w = round.weights[c.id] ?? 0
          return (
            <tr key={c.id}>
              <td className="py-3 pr-3">
                <div className="font-medium text-slate-800">{c.id}</div>
                <div className="text-xs text-slate-500">{nodeLabel(c.nodeId)}</div>
              </td>
              <td className="py-3 pr-3">
                <div className="flex items-center gap-2">
                  <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full rounded-full bg-indigo-500 transition-all duration-500" style={{ width: `${(w / max) * 100}%` }} />
                  </div>
                  <span className="w-12 text-right tabular-nums text-slate-700">{(w * 100).toFixed(1)}%</span>
                </div>
              </td>
              <td className="py-3 pr-3 text-right tabular-nums text-slate-700">{fmtNum(c.localSamples)}</td>
              <td className="py-3 text-slate-500">
                Round {round.round}
                {source === 'ledger' && round.blockNumber != null && <span className="text-violet-600"> · block #{round.blockNumber}</span>}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

export default function FederatedPanel() {
  const { rounds, source, connected } = useRounds()
  useReportConnection(connected)
  const { idx, phase, playing, setPlaying, setIdx, setPhase } = usePlayback(rounds.length)
  const round = rounds[idx]

  const chartData = useMemo(
    () =>
      FL_RUN_SNAPSHOT.fedavgValPrAuc.map((v, i) => ({
        round: i + 1,
        fedavg: v,
        adaptive: FL_RUN_SNAPSHOT.adaptiveValPrAuc[i],
        trainLoss: FL_RUN_SNAPSHOT.adaptiveTrainLoss[i],
        valLoss: FL_RUN_SNAPSHOT.adaptiveValNormLoss[i],
      })),
    [],
  )

  if (!round) return null
  const total = round.total ?? rounds.length
  const pct = (round.round / total) * 100

  return (
    <div className="space-y-5">
      {/* status strip */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-2xl border border-slate-200 bg-white px-5 py-4">
        <div className="min-w-[220px] flex-1">
          <div className="flex items-baseline justify-between">
            <span className="text-lg font-semibold text-slate-900">
              Round {round.round} <span className="font-normal text-slate-500">of {total}</span>
            </span>
            <span className="text-sm text-slate-500">{PHASES.find((p) => p.id === phase)?.label}</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-indigo-500 transition-all duration-500" style={{ width: `${pct}%` }} />
          </div>
        </div>
        <div className="text-sm">
          <div className="text-slate-500">Nodes participating</div>
          <div className="font-semibold text-slate-900">
            {round.participants.length} of {FL_CLIENTS.length}
          </div>
        </div>
        <div className="text-sm">
          <div className="text-slate-500">Last updated</div>
          <div className="font-semibold text-slate-900">{round.updatedAt ? new Date(round.updatedAt).toLocaleString() : 'Offline run'}</div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={() => setPlaying((p) => !p)}>
            {playing ? 'Pause' : 'Play'}
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setIdx(0)
              setPhase(0)
            }}
          >
            Restart
          </Button>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-5">
        <Card
          title="Model updates"
          subtitle={`${round.strategy}: only weights travel, never raw data`}
          className="xl:col-span-3"
          action={source === 'ledger' ? <Pill tone="chain">From ledger</Pill> : <Pill tone="idle">Offline snapshot</Pill>}
        >
          <FederationDiagram round={round} phase={phase} />
          <div className="mt-2 flex flex-wrap gap-2">
            {FL_CLIENTS.map((c) => {
              const st = NODE_STATUS[round.participants.includes(c.id) ? phase : 'idle']
              return (
                <span key={c.id} className="flex items-center gap-1.5 text-sm text-slate-600">
                  {c.id} <Pill tone={st.tone}>{st.label}</Pill>
                </span>
              )
            })}
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Replay of the offline Module 4 run (Flower, 4 clients = the 4 replayed Kelmarsh turbines). Circle size = the
            client's adaptive weight that round.
          </p>
        </Card>

        <Card title="Node contributions" subtitle={`Adaptive weights in round ${round.round}`} className="xl:col-span-2">
          <WeightsTable round={round} source={source} />
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="Model quality per round" subtitle="Validation PR-AUC (higher is better)">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="round" stroke={CHART.axis} fontSize={12} tickLine={false} />
                <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} width={48} />
                <Tooltip {...CHART.tooltip} formatter={(v) => fmtNum(v, 3)} labelFormatter={(l) => `Round ${l}`} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 13 }} />
                <ReferenceLine x={round.round} stroke="#c7d2fe" strokeWidth={2} />
                <Line name="FedAvg" dataKey="fedavg" stroke="#94a3b8" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line name="FedProx + adaptive" dataKey="adaptive" stroke={ACCENT} strokeWidth={2.5} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <Details label="About this metric">
            <p className="text-sm text-slate-600">
              Mean client validation PR-AUC per round, seed 3, from each run's round_log.json. Accuracy is not shown: with
              about 0.1% fault samples, a model that never predicts a fault scores 99.9%. Test-set results are in
              backend/ai/federated/artifacts/RESULTS.md.
            </p>
          </Details>
        </Card>

        <Card title="TA-GNN training loss" subtitle="FedProx + adaptive, mean over clients">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="round" stroke={CHART.axis} fontSize={12} tickLine={false} />
                <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} width={48} />
                <Tooltip {...CHART.tooltip} formatter={(v) => fmtNum(v, 3)} labelFormatter={(l) => `Round ${l}`} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 13 }} />
                <ReferenceLine x={round.round} stroke="#c7d2fe" strokeWidth={2} />
                <Line name="Train loss" dataKey="trainLoss" stroke={ACCENT} strokeWidth={2.5} dot={false} isAnimationActive={false} />
                <Line name="Validation loss (normalised)" dataKey="valLoss" stroke="#f59e0b" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
            <Icon name="brain" size={14} /> Snapshot of the offline run; not exposed by an API yet.
          </p>
        </Card>
      </div>
    </div>
  )
}
