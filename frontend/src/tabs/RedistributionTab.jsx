import { useMemo, useRef, useState } from 'react'
import BlockchainTab from './BlockchainTab'
import { useBlockchainSocket } from '../hooks/useBlockchainSocket'
import { useDigitalTwinSocket } from '../hooks/useDigitalTwinSocket'
import { useReportConnection } from '../ui/AppShell'
import Icon, { SourceIcon } from '../ui/icons'
import { Card, CopyButton, Details, EmptyState, Pill } from '../ui/components'
import { fmtNum, shortHash } from '../ui/format'
import { nodeLabel } from '../ui/theme'

// Redistribution (Blockchain). Presentation over existing data only:
//  - flow cards and block strip: GET /chain/records + chain_record pushes
//    (useBlockchainSocket, unfiltered, newest 50).
//  - trade table: its own useBlockchainSocket('P2P_TRADE'), because trades are
//    easily pushed out of the unfiltered newest-50 by fault/FL records.
//  - topology timeline: GET /twin/decisions + twin_decision pushes, joined to
//    the ENERGY_REDISTRIBUTION record that put each decision on chain
//    (payload.twin_decision_id = "<node_id>@<decision time>").
//  - the full ledger explorer below is the existing Blockchain tab, restyled.
// P2P trades are SIMULATED (POST /chain/simulate-trade) and settled in demo
// credits; amounts are shown with a ₹ sign for illustration and every trade
// carries a "Simulated" tag.

const TRADE_STATUS = (r) => (r.status === 'confirmed' ? 'Sold' : r.status === 'failed' ? 'Not sold' : 'Pending')

function ChainBadge({ record }) {
  const onChain = record.status === 'confirmed' || record.status === 'included'
  const verified = record.verify_result === 'match'
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium ${
        onChain ? 'bg-violet-50 text-violet-700' : 'bg-slate-100 text-slate-500'
      }`}
      title={record.tx_hash ? `tx ${record.tx_hash}` : 'Not yet on chain'}
    >
      <Icon name="block" size={14} />
      {!onChain ? 'Waiting for chain' : verified ? 'Verified on chain' : 'Recorded on chain'}
      {record.block_number != null && <span className="text-violet-500">· #{record.block_number}</span>}
    </span>
  )
}

function Endpoint({ id, tone, caption }) {
  const styles = tone === 'surplus' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : tone === 'deficit' ? 'border-red-200 bg-red-50 text-red-700' : 'border-slate-200 bg-slate-50 text-slate-700'
  return (
    <div className={`flex min-w-0 flex-1 items-center gap-2.5 rounded-xl border px-3 py-2.5 ${styles}`}>
      <SourceIcon type={/hydro/.test(id ?? '') ? 'hydro' : /bus/.test(id ?? '') ? 'bus' : id === 'grid' ? 'grid' : 'wind'} size={20} />
      <div className="min-w-0 leading-tight">
        <div className="truncate text-sm font-semibold">{nodeLabel(id)}</div>
        <div className="text-xs opacity-80">{caption}</div>
      </div>
    </div>
  )
}

function FlowCard({ record, onOpen }) {
  const p = record.payload ?? {}
  const trade = record.event_type === 'P2P_TRADE'
  let left, right, qty, amount, title
  if (trade) {
    title = 'Peer-to-peer trade'
    left = { id: p.seller, tone: 'surplus', caption: 'Seller · surplus' }
    right = { id: p.buyer, tone: 'deficit', caption: 'Buyer · deficit' }
    qty = `${fmtNum(p.kwh, 2)} kWh`
    amount = p.settlement?.amount != null ? `₹ ${fmtNum(p.settlement.amount, 2)}` : null
  } else {
    const isolate = p.action === 'isolate'
    title = p.action === 'reroute' ? 'Self-healing reroute' : isolate ? 'Node isolated' : 'Output curtailed'
    left = { id: p.source_node, tone: 'deficit', caption: `Faulted · was via ${nodeLabel(p.previous_connection)}` }
    right = isolate
      ? { id: 'grid', tone: 'neutral', caption: 'Disconnected from grid' }
      : { id: p.target_node ?? p.previous_connection, tone: 'surplus', caption: 'Now carries the load' }
    qty = `${fmtNum(p.kw_affected)} kW`
  }
  return (
    <button onClick={() => onOpen(record.id)} className="w-full rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-[0_1px_3px_rgba(15,23,42,0.06)] transition-shadow hover:shadow-md">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-slate-800">{title}</span>
        <div className="flex items-center gap-2">
          {record.provenance === 'simulated' && <Pill tone="warn" dot={false}>Simulated</Pill>}
          <span className="text-xs text-slate-400">{new Date(record.created_at).toLocaleTimeString()}</span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Endpoint {...left} />
        <div className="flex shrink-0 flex-col items-center px-1 text-center">
          <span className="text-base font-semibold text-slate-900">{qty}</span>
          {amount && <span className="text-sm font-medium text-slate-600">{amount}</span>}
          <Icon name="arrow" size={22} className="text-slate-400" />
        </div>
        <Endpoint {...right} />
      </div>
      <div className="mt-3">
        <ChainBadge record={record} />
      </div>
    </button>
  )
}

const TYPE_DOT = {
  P2P_TRADE: '#f59e0b',
  ENERGY_REDISTRIBUTION: '#14b8a6',
  FAULT_ALERT: '#dc2626',
  FL_ROUND: '#7c3aed',
}

function BlockStrip({ records, onOpen }) {
  const [openBlock, setOpenBlock] = useState(null)
  const blocks = useMemo(() => {
    const byBlock = new Map()
    // Only the current contract deployment: after a local-chain restart,
    // block numbers from the earlier ledger would otherwise mix in.
    for (const r of records) {
      if (r.block_number == null || r.deployment_current === false) continue
      if (!byBlock.has(r.block_number)) byBlock.set(r.block_number, [])
      byBlock.get(r.block_number).push(r)
    }
    return [...byBlock.entries()].sort((a, b) => b[0] - a[0]).slice(0, 10)
  }, [records])

  if (blocks.length === 0) return <EmptyState icon="block">No records in a block yet.</EmptyState>
  const selected = blocks.find(([n]) => n === openBlock)
  return (
    <div>
      <div className="flex items-center gap-0 overflow-x-auto pb-2">
        {blocks.map(([n, recs], i) => (
          <div key={n} className="flex items-center">
            {i > 0 && <span className="h-0.5 w-5 shrink-0 bg-violet-200" />}
            <button
              onClick={() => setOpenBlock(openBlock === n ? null : n)}
              className={`w-28 shrink-0 rounded-xl border p-3 text-left transition-colors ${
                openBlock === n ? 'border-violet-400 bg-violet-50' : 'border-slate-200 bg-white hover:border-violet-300'
              }`}
            >
              <div className="flex items-center gap-1.5 text-violet-600">
                <Icon name="block" size={15} />
                <span className="text-sm font-semibold">#{n}</span>
              </div>
              <div className="mt-2 flex gap-1">
                {recs.slice(0, 6).map((r) => (
                  <span key={r.id} className="h-2 w-2 rounded-full" style={{ background: TYPE_DOT[r.event_type] ?? '#94a3b8' }} />
                ))}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {recs.length} record{recs.length === 1 ? '' : 's'}
              </div>
            </button>
          </div>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
        {Object.entries({ 'P2P trade': TYPE_DOT.P2P_TRADE, Redistribution: TYPE_DOT.ENERGY_REDISTRIBUTION, 'Fault alert': TYPE_DOT.FAULT_ALERT, 'FL round': TYPE_DOT.FL_ROUND }).map(([l, c]) => (
          <span key={l} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: c }} />
            {l}
          </span>
        ))}
      </div>
      {selected && (
        <ul className="mt-4 divide-y divide-slate-100 rounded-xl border border-slate-200">
          {selected[1].map((r) => (
            <li key={r.id}>
              <button onClick={() => onOpen(r.id)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm hover:bg-slate-50">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: TYPE_DOT[r.event_type] }} />
                <span className="min-w-0 flex-1 truncate text-slate-700">{r.summary}</span>
                <span className="text-xs text-indigo-600">Open</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function TradesTable({ trades, onOpen, hasMore, loadMore }) {
  if (trades.length === 0) {
    return <EmptyState icon="rupee">No trades yet. Use "Simulate P2P trade" in the ledger explorer below.</EmptyState>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-500">
          <tr className="border-b border-slate-200">
            <th className="py-2.5 pr-4 font-medium">Buyer</th>
            <th className="py-2.5 pr-4 font-medium">Seller</th>
            <th className="py-2.5 pr-4 text-right font-medium">Qty (kWh)</th>
            <th className="py-2.5 pr-4 text-right font-medium">Amount (₹)</th>
            <th className="py-2.5 pr-4 font-medium">Status</th>
            <th className="py-2.5 font-medium">Tx hash</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {trades.map((r) => {
            const p = r.payload ?? {}
            return (
              <tr key={r.id} className="cursor-pointer hover:bg-slate-50" onClick={() => onOpen(r.id)}>
                <td className="py-3 pr-4 font-medium text-slate-800">{nodeLabel(p.buyer)}</td>
                <td className="py-3 pr-4 text-slate-700">{nodeLabel(p.seller)}</td>
                <td className="py-3 pr-4 text-right tabular-nums">{fmtNum(p.kwh, 2)}</td>
                <td className="py-3 pr-4 text-right tabular-nums">{fmtNum(p.settlement?.amount, 2)}</td>
                <td className="py-3 pr-4">
                  <Pill>{TRADE_STATUS(r)}</Pill>
                </td>
                <td className="py-3" onClick={(e) => e.stopPropagation()}>
                  <span className="inline-flex items-center gap-1 font-mono text-xs text-slate-600">
                    {shortHash(r.tx_hash)}
                    {r.tx_hash && <CopyButton text={r.tx_hash} label="Copy tx hash" />}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-slate-500">
        Trades are simulated (no solar/EV hardware yet). Amounts are demo credits shown as ₹ for illustration; no real
        money moved.
      </p>
      {hasMore && (
        <button onClick={loadMore} className="mt-2 text-sm font-medium text-indigo-600 hover:text-indigo-700">
          Load older records
        </button>
      )}
    </div>
  )
}

const TOPO_EVENT = {
  reroute: { label: 'Self-healing reroute', icon: 'heal', color: '#14b8a6' },
  isolate: { label: 'Node removed from grid (line fault)', icon: 'alert', color: '#dc2626' },
  reduce_load_share: { label: 'Output curtailed', icon: 'gauge', color: '#d97706' },
}

function decisionKey(nodeId, time) {
  const t = new Date(time).getTime()
  return `${nodeId}@${Number.isNaN(t) ? time : t}`
}

function TopologyTimeline({ decisions, redistributions }) {
  const blockByDecision = useMemo(() => {
    const map = {}
    for (const r of redistributions) {
      const id = r.payload?.twin_decision_id
      if (!id) continue
      const at = id.lastIndexOf('@')
      map[decisionKey(id.slice(0, at), id.slice(at + 1))] = r
    }
    return map
  }, [redistributions])

  if (decisions.length === 0) {
    return <EmptyState icon="heal">No topology changes yet. They appear when the digital twin reacts to a fault.</EmptyState>
  }
  return (
    <ol className="relative space-y-5 border-l-2 border-slate-200 pl-6">
      {decisions.slice(0, 12).map((d, i) => {
        const ev = TOPO_EVENT[d.chosen_action] ?? { label: d.chosen_action, icon: 'nodes', color: '#64748b' }
        const rec = blockByDecision[decisionKey(d.node_id, d.time)]
        const via = d.chosen_params?.via
        const affected = [d.node_id, via].filter(Boolean)
        return (
          <li key={`${d.node_id}-${d.time}-${i}`} className="relative">
            <span
              className="absolute -left-[37px] flex h-7 w-7 items-center justify-center rounded-full bg-white ring-2"
              style={{ color: ev.color, '--tw-ring-color': ev.color }}
            >
              <Icon name={ev.icon} size={15} />
            </span>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold text-slate-800">{ev.label}</span>
              <span className="text-xs text-slate-500">{new Date(d.time).toLocaleString()}</span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm">
              {affected.map((n) => (
                <span key={n} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                  {nodeLabel(n)}
                </span>
              ))}
              {d.chosen_action === 'reduce_load_share' && d.chosen_params?.fraction != null && (
                <span className="text-xs text-slate-500">to {Math.round(d.chosen_params.fraction * 100)}% output</span>
              )}
              {rec ? (
                <span className="inline-flex items-center gap-1 text-xs font-medium text-violet-700">
                  <Icon name="block" size={13} />
                  {rec.block_number != null ? `Block #${rec.block_number}` : 'Waiting for a block'}
                </span>
              ) : (
                <span className="text-xs text-slate-400">Not on chain yet</span>
              )}
            </div>
            <div className="mt-1.5">
              <Details label="Why">
                <p className="text-sm text-slate-600">Trigger: {d.trigger_summary}</p>
                <p className="mt-1 text-sm text-slate-600">{d.reason}</p>
              </Details>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

export default function RedistributionTab() {
  const { records, connected } = useBlockchainSocket(null)
  const { records: trades, hasMore, loadMore } = useBlockchainSocket('P2P_TRADE')
  const { decisions } = useDigitalTwinSocket()
  useReportConnection(connected)
  const [selected, setSelected] = useState(null)
  const explorerRef = useRef(null)

  const open = (id) => {
    setSelected(id)
    explorerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const flows = [...trades.slice(0, 2), ...records.filter((r) => r.event_type === 'ENERGY_REDISTRIBUTION')]
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    .slice(0, 4)
  const redistributions = records.filter((r) => r.event_type === 'ENERGY_REDISTRIBUTION')

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <Card title="Recent redistributions" subtitle="Energy moving from surplus to deficit nodes, each backed by a ledger record">
        {flows.length === 0 ? (
          <EmptyState icon="chain">No redistributions or trades yet.</EmptyState>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {flows.map((r) => (
              <FlowCard key={r.id} record={r} onOpen={open} />
            ))}
          </div>
        )}
      </Card>

      <Card title="Recent blocks" subtitle="Click a block to see the records it holds">
        <BlockStrip records={records} onOpen={open} />
      </Card>

      <Card title="Transactions" subtitle="Peer-to-peer energy trades">
        <TradesTable trades={trades} onOpen={open} hasMore={hasMore} loadMore={loadMore} />
      </Card>

      <Card title="Topology changes on chain" subtitle="Self-healing reconfigurations by the digital twin, and the block that records each one">
        <TopologyTimeline decisions={decisions} redistributions={redistributions} />
      </Card>

      <div ref={explorerRef} className="scroll-mt-4">
        <Card title="Ledger explorer" subtitle="Every record, its journey onto the chain, and integrity verification" bodyClassName="!p-0 !pt-3">
          <div className="flex h-[720px] flex-col overflow-hidden rounded-b-2xl border-t border-slate-200">
            <BlockchainTab selected={selected} onSelect={setSelected} />
          </div>
        </Card>
      </div>
    </div>
  )
}
