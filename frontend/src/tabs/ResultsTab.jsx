import { useMemo, useState } from 'react'
import { Card, Details, EmptyState, Pill, StatCard, Tabs } from '../ui/components'
import Icon from '../ui/icons'
import { ErrorNote, Loading, RealPill, SimPill } from '../testbed/common'
import { fmt } from '../testbed/format'
import { useTestbed } from '../testbed/useTestbed'

// Results: every paper table next to the number measured on the simulated testbed. Paper values appear only
// as "Paper target". Nothing is computed client-side except the green/amber classification that the
// backend already sent (comparison.json) and the pipeline strip labels.

const PAPERS = [
  { id: 'journal', label: 'Journal' },
  { id: 'conference', label: 'Conference' },
  { id: 'kelmarsh', label: 'Real Kelmarsh data' },
]

const ROMAN = { I: 1, II: 2, III: 3, IV: 4, V: 5, VI: 6, VII: 7, VIII: 8, IX: 9, X: 10, XI: 11 }
function tableOrder(name) {
  const m = name.match(/Table ([IVX]+)/)
  return m ? ROMAN[m[1]] : name.startsWith('Abstract') ? 50 : 60
}

// The chain a number comes from, per table (labels only).
const PIPELINE = {
  'Table III': ['Topology built', 'Node / line counts', 'Structural check'],
  'Table IV': ['Testbed 24 h @ 5 s', 'Faults injected (4 types × 5)', 'TA-GNN 25 epochs', 'Validation loss / F1'],
  'Table V': ['Testbed 24 h @ 5 s', 'Faults injected (4 types × 5)', 'TA-GNN 250 epochs (± LRS)', 'Validation loss / F1'],
  'Table VI': ['Testbed 24 h @ 5 s', 'Faults injected', 'TA-GNN vs GCN', 'MAE / RMSE (kW)'],
  'Table VII': ['Held-out scenarios', 'Faults injected (4 types × 5)', 'Twin vs default scheme (pandapower)', 'F1 · T_rec · E_uns'],
  'Table VIII': ['Topology C, line 12–13 outage ×20', 'Twin evaluates Ω', 'Cost J → action a*', 'Sequence counts'],
  'Table IX': ['Measured Tables VI + VII', 'Percent improvement', 'Derived, not entered'],
  'Table X': ['One client per node', 'Local train + aggregate', 'FedAvg / FedProx / adaptive', 'Rounds · C_comm · loss · F1'],
  'Table XI': ['Trades on the testbed day', 'EnergyMarket on Hardhat', 'Receipts', 'Gas · latency'],
  Abstract: ['Measured Tables VI / VII / X', 'Max over topologies', 'Derived claim'],
  'Table II': ['Simulator', 'Samples per node', 'Structural check'],
  'Table IV (conf)': ['5 simulated datasets', 'Faults from injection log', 'Risk score Eqs. 1–4', 'AUC · P · R · F1 · FAR'],
  'Table V (conf)': ['Full year', '5-fold blocked CV', 'F1 at fixed τ', 'By season / load'],
  'Table VI (conf)': ['6 clients', 'FedAvg / FedProx / adaptive', 'IID · Dirichlet α', 'Test RMSE · rounds'],
  'Table VII (conf)': ['Same partitions', 'LSTM · GRU · GCN · TGNN · TA-GNN', '3 seeds', 'RMSE · MAE · R²'],
  'Table VIII (conf)': ['5–50 registered nodes', 'EnergyMarket settle()', '5 rounds × 3 repeats', 'Latency · gas · tx/s'],
}

function Pipeline({ steps }) {
  if (!steps) return null
  return (
    <ol className="flex flex-wrap items-center gap-1.5 text-xs text-slate-600" aria-label="How this table is produced">
      {steps.map((s, i) => (
        <li key={s} className="flex items-center gap-1.5">
          <span className="rounded-md bg-slate-100 px-2 py-1 font-medium">{s}</span>
          {i < steps.length - 1 && <Icon name="arrow" size={12} className="text-slate-400" />}
        </li>
      ))}
    </ol>
  )
}

function meas(r) {
  const v = r.measured_rounded ?? r.measured
  if (v == null) return '—'
  const base = fmt(v, r.unit && r.unit !== '%' ? r.unit : '')
  const unit = r.unit === '%' ? ' %' : ''
  return r.std != null && r.n > 1 ? `${base}${unit} ± ${fmt(r.std, '')}` : `${base}${unit}`
}

function HowComputed({ r, run }) {
  const m = run?.metrics?.[r.index]
  return (
    <div className="space-y-2 rounded-xl bg-slate-50 p-3 text-xs text-slate-700">
      <div>
        <span className="font-semibold">Formula: </span>
        {m?.formula || '—'} {m?.equation ? <span className="rounded bg-white px-1.5 py-0.5 font-mono">Eq. {m.equation}</span> : null}
      </div>
      {m?.inputs && Object.keys(m.inputs).length > 0 && (
        <div>
          <span className="font-semibold">Inputs plugged in: </span>
          {r.name.endsWith('_pct') && m.inputs
            ? Object.entries(m.inputs).map(([k, v]) => `${k.replace(/_/g, ' ')} = ${fmt(v)}`).join(' · ')
            : Object.entries(m.inputs).map(([k, v]) => `${k} = ${typeof v === 'number' ? fmt(v) : String(v)}`).join(' · ')}
        </div>
      )}
      <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
        <div><span className="font-semibold">Testbed / topology: </span>{r.topology ? `Topology ${r.topology}` : 'see conditions'}{m?.conditions ? ` · ${m.conditions}` : ''}</div>
        <div><span className="font-semibold">Split: </span>{m?.split || '—'}</div>
        <div><span className="font-semibold">Seeds / iterations: </span>{m?.seeds ? JSON.stringify(m.seeds) : '—'} (n = {r.n ?? 1})</div>
        <div><span className="font-semibold">Run: </span><span className="font-mono">{r.run_id}</span> · config <span className="font-mono">{r.config_hash}</span></div>
      </div>
      {m?.values && <div><span className="font-semibold">Per-seed values: </span>{m.values.map((v) => fmt(v)).join(', ')}</div>}
      {m?.note && <div className="text-slate-500">{m.note}</div>}
      {run?.config && <div><span className="font-semibold">Run settings: </span><span className="font-mono">{JSON.stringify(run.config).slice(0, 360)}</span></div>}
      <div>
        <a className="font-medium text-indigo-600 hover:underline" href={`/testbed/runs/${r.run_id}`} target="_blank" rel="noreferrer">
          Raw metrics JSON ({r.run_id})
        </a>
      </div>
    </div>
  )
}

function Row({ r }) {
  const [run, setRun] = useState(null)
  const tone = r.within === true ? 'ok' : r.within === false ? 'warn' : 'idle'
  const diff = r.abs_diff == null ? null : `${r.abs_diff >= 0 ? '+' : ''}${fmt(r.abs_diff)}${r.rel_diff != null ? ` (${r.rel_diff >= 0 ? '+' : ''}${(r.rel_diff * 100).toFixed(1)} %)` : ''}`
  const load = async () => {
    if (run) return
    const res = await fetch(`/testbed/runs/${r.run_id}`, { credentials: 'same-origin' })
    if (res.ok) setRun(await res.json())
  }
  return (
    <>
      <tr className="border-t border-slate-100 align-top">
        <td className="py-2 pr-3 text-sm text-slate-800">
          <div className="font-medium">{r.name.replace(/_/g, ' ')}{r.topology ? <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">Topology {r.topology}</span> : null}</div>
          <div className="text-[11px] text-slate-400">{r.target_id ?? 'no paper target'}</div>
        </td>
        <td className="py-2 pr-3 text-sm tabular-nums text-slate-900">
          <div className="flex flex-wrap items-center gap-1.5">{meas(r)}<SimPill className="!px-1.5 !py-0 !text-[10px]" /></div>
        </td>
        <td className="py-2 pr-3 text-sm tabular-nums text-slate-600">{r.paper == null ? '—' : <span title="Paper target">{fmt(r.paper, r.unit !== '%' ? r.unit : '')}{r.unit === '%' ? ' %' : ''}</span>}</td>
        <td className={`py-2 pr-3 text-sm tabular-nums ${r.within === false ? 'text-amber-700' : r.within ? 'text-emerald-700' : 'text-slate-500'}`}>{diff ?? '—'}</td>
        <td className="py-2 pr-3"><Pill tone={tone}>{r.status}</Pill></td>
        <td className="py-2 text-sm" onClick={load}>
          <Details label="How computed"><HowComputed r={r} run={run} /></Details>
        </td>
      </tr>
      {r.within === false && (
        <tr>
          <td colSpan={6} className="pb-2 text-xs text-amber-800">
            <span className="font-semibold">Why outside tolerance: </span>{r.reason || 'No explanation recorded for this target yet; see comparison.md.'}
          </td>
        </tr>
      )}
    </>
  )
}

function TableCard({ t, steps }) {
  return (
    <Card
      title={t.table}
      subtitle={`${t.within} of ${t.total} within ±5 % of the paper target${t.outside ? ` · ${t.outside} outside` : ''}`}
      action={<SimPill />}
    >
      <div className="mb-3"><Pipeline steps={steps} /></div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-slate-400">
              <th className="pb-1 pr-3 font-medium">Metric</th>
              <th className="pb-1 pr-3 font-medium">Measured</th>
              <th className="pb-1 pr-3 font-medium">Paper target</th>
              <th className="pb-1 pr-3 font-medium">Difference</th>
              <th className="pb-1 pr-3 font-medium">Tolerance</th>
              <th className="pb-1 font-medium" />
            </tr>
          </thead>
          <tbody>
            {t.rows.map((r) => (
              <Row key={`${r.run_id}-${r.index}`} r={r} />
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function PaperResults({ paper }) {
  const { data, error, loading } = useTestbed(`/testbed/results?paper=${paper}`)
  const tables = useMemo(() => [...(data?.tables ?? [])].sort((a, b) => tableOrder(a.table) - tableOrder(b.table)), [data])
  if (loading) return <Loading what="results" />
  if (error) return <ErrorNote error={error} />
  const within = tables.reduce((a, t) => a + t.within, 0)
  const outside = tables.reduce((a, t) => a + t.outside, 0)
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Within tolerance" value={within} icon="check" color="#16a34a" hint="measured vs paper, ±5 %" />
        <StatCard label="Outside tolerance" value={outside} icon="alert" color="#d97706" hint="reported, not tuned away" />
        <StatCard label="Tables" value={tables.length} icon="analytics" color="#4f46e5" hint={`${paper} paper`} />
      </div>
      {tables.length === 0 && <EmptyState>No results yet. Run <span className="font-mono">experiments/run_all.py</span>.</EmptyState>}
      {tables.map((t) => (
        <TableCard key={t.table} t={t} steps={PIPELINE[t.table.replace(/^Table /, 'Table ')] && paper === 'journal' ? PIPELINE[t.table] ?? PIPELINE[t.table.split(' /')[0]] : PIPELINE[`${t.table} (conf)`] ?? PIPELINE[t.table]} />
      ))}
    </div>
  )
}

function Kelmarsh() {
  const { data, error, loading } = useTestbed('/testbed/kelmarsh')
  if (loading) return <Loading what="Kelmarsh results" />
  if (error) return <ErrorNote error={error} />
  const m3 = data.module3
  return (
    <div className="space-y-5">
      <Card title="Module 3 – TA-GNN fault forecaster (real data)" subtitle="Read-only from the existing result artifacts; never mixed with the simulated testbed." action={<RealPill />}>
        {m3 ? (
          <>
            <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-5">
              <StatCard label="F1" value={fmt(m3.detection.f1, '', 3)} />
              <StatCard label="Precision" value={fmt(m3.detection.precision, '', 3)} />
              <StatCard label="Recall" value={fmt(m3.detection.recall, '', 3)} />
              <StatCard label="ROC AUC" value={fmt(m3.detection.roc_auc, '', 3)} />
              <StatCard label="PR AUC" value={fmt(m3.detection.pr_auc, '', 3)} />
            </div>
            <p className="mt-3 text-xs text-slate-500">{m3.model} · {m3.seeds} seeds · split {m3.split} · source {m3.source}</p>
          </>
        ) : (
          <EmptyState>No Module 3 results file found.</EmptyState>
        )}
      </Card>
      <Card title="Module 4 – federated runs (real data, replayed)" action={<RealPill />}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead><tr className="text-xs uppercase tracking-wide text-slate-400"><th className="pb-1">Run</th><th>Mode</th><th>μ</th><th>Rounds</th><th>Converged at</th><th>Best val PR-AUC</th><th>MB (float32)</th></tr></thead>
            <tbody>
              {data.module4.map((r) => (
                <tr key={r.run} className="border-t border-slate-100">
                  <td className="py-1.5 font-mono text-xs">{r.run}</td><td>{r.mode}</td><td>{r.mu}</td><td>{r.rounds}</td><td>{r.rounds_to_convergence ?? '—'}</td>
                  <td className="tabular-nums">{fmt(r.best_val_pr_auc, '', 3)}</td><td className="tabular-nums">{fmt(r.megabytes_float32, '', 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

export default function ResultsTab() {
  const [paper, setPaper] = useState('journal')
  return (
    <div className="mx-auto max-w-7xl space-y-5 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-500">
          Each paper table is reproduced from real runs on a <b>simulated testbed</b> and shown beside the number the paper reports (“Paper target”). The real Kelmarsh results are a separate tab and are never mixed with these.
        </p>
        <Tabs tabs={PAPERS} value={paper} onChange={setPaper} />
      </div>
      {paper === 'kelmarsh' ? <Kelmarsh /> : <PaperResults key={paper} paper={paper} />}
    </div>
  )
}
