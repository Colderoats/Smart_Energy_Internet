import { useMemo, useState } from 'react'
import { CopyButton, EmptyState, Pill } from '../ui/components'
import { fmtNum, shortHash } from '../ui/format'
import { CHAIN_COLOR, nodeLabel } from '../ui/theme'

// Prosumer market views for the Blockchain / Redistribution screens. All values are real
// /market/* endpoint values (see hooks/useMarketSocket.js). Prosumers are SIMULATED
// buildings: solar estimated from live weather, load synthetic. Amounts are demo credits.

export const MARKET_NOTE = 'Prosumers are simulated buildings: solar estimated from live weather, load synthetic. Amounts are demo credits.'

const TX_STATUS = {
  planned: { label: 'Planned (off-chain)', tone: 'idle' },
  pending: { label: 'Pending', tone: 'warn' },
  in_block: { label: 'In block', tone: 'info' },
  confirmed: { label: 'Confirmed', tone: 'ok' },
  failed: { label: 'Failed', tone: 'bad' },
}

export function TxStatus({ status }) {
  const s = TX_STATUS[status] ?? { label: status ?? '—', tone: 'idle' }
  return <Pill tone={s.tone}>{s.label}</Pill>
}

function Hash({ value }) {
  if (!value) return <span className="text-slate-400">—</span>
  return (
    <span className="inline-flex items-center gap-0.5 font-mono text-xs text-slate-600" title={value}>
      {shortHash(value)}
      <CopyButton text={value} label="Copy" />
    </span>
  )
}

const credits = (milli) => (milli == null ? '—' : fmtNum(milli / 1000, 3))

// (a) Registered prosumers
export function RegistrationsTable({ prosumers, highlight }) {
  if (!prosumers.length) return <EmptyState icon="chain">Waiting for the prosumer list…</EmptyState>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-500">
          <tr className="border-b border-slate-200">
            <th className="py-2 pr-3 font-medium">Node</th>
            <th className="py-2 pr-3 font-medium">Address</th>
            <th className="py-2 pr-3 font-medium">Registration tx</th>
            <th className="py-2 pr-3 text-right font-medium">Block</th>
            <th className="py-2 pr-3 text-right font-medium">Gas</th>
            <th className="py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {prosumers.map((p) => {
            const r = p.registration
            return (
              <tr key={p.node_id} id={`reg-${p.node_id}`} className={highlight === p.node_id ? 'bg-violet-50 ring-1 ring-violet-300' : ''} data-testid="registration-row">
                <td className="py-2.5 pr-3 font-medium text-slate-800">
                  {nodeLabel(p.node_id)}
                  <div className="font-mono text-[11px] font-normal text-slate-400">{p.node_id}</div>
                </td>
                <td className="py-2.5 pr-3">{p.address ? <Hash value={p.address} /> : <span className="text-slate-400">—</span>}</td>
                <td className="py-2.5 pr-3"><Hash value={r?.tx_hash} /></td>
                <td className="py-2.5 pr-3 text-right tabular-nums">{r?.block_number != null ? `#${r.block_number}` : '—'}</td>
                <td className="py-2.5 pr-3 text-right tabular-nums">{r?.gas_used != null ? fmtNum(r.gas_used) : '—'}</td>
                <td className="py-2.5"><TxStatus status={r?.status ?? 'planned'} /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// (b) Live order book for the current interval
export function OrderBook({ orders, interval, now }) {
  const offers = orders.filter((o) => o.side === 'offer').sort((a, b) => a.price_milli - b.price_milli)
  const bids = orders.filter((o) => o.side === 'bid').sort((a, b) => b.price_milli - a.price_milli)
  const left = interval ? Math.max(0, Math.ceil((new Date(interval.ends_at).getTime() - now) / 1000)) : null
  const Side = ({ title, rows, tone }) => (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide" style={{ color: tone }}>{title}</div>
      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">None this interval.</p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">
          {rows.map((o) => (
            <li key={o.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm" data-testid="order-row">
              <span className="min-w-[110px] font-medium text-slate-800">{nodeLabel(o.node_id)}</span>
              <span className="tabular-nums text-slate-700">{fmtNum(o.qty_wh / 1000, 3)} kWh</span>
              <span className="tabular-nums text-slate-700">@ {fmtNum(o.price_milli / 1000, 2)}</span>
              {o.remaining_wh != null && o.remaining_wh < o.qty_wh && <span className="text-xs text-slate-500">{fmtNum(o.remaining_wh / 1000, 3)} left</span>}
              <span className="ml-auto flex items-center gap-2">
                <TxStatus status={o.status} />
                {o.block_number != null && <span className="text-xs text-violet-700">#{o.block_number}</span>}
                <Hash value={o.tx_hash} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
  return (
    <div>
      <p className="mb-2 text-sm text-slate-600">
        {interval ? <>Interval #{interval.id} · {left != null ? `${left}s left` : ''} · status <span className="font-medium">{interval.status}</span></> : 'No interval yet.'}
        <span className="text-slate-400"> · prices are demo credits per kWh; the trade price is the seller's ask.</span>
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        <Side title="Offers (sellers, ask ↑)" rows={offers} tone="#16a34a" />
        <Side title="Bids (buyers, max ↓)" rows={bids} tone="#d97706" />
      </div>
    </div>
  )
}

// (c) Trade journey per settlement
const STEP_DOT = {
  done: 'bg-emerald-500 text-emerald-950',
  active: 'bg-amber-400 text-amber-950 animate-pulse',
  pending: 'bg-slate-200 text-slate-600',
  failed: 'bg-red-500 text-red-950',
}

function Journey({ trade, onOpenRecord }) {
  return (
    <ol className="relative ml-2 space-y-3 border-l border-slate-300 pl-6" data-testid="trade-journey">
      {trade.journey.map((s, i) => (
        <li key={s.key} className="relative">
          <span className={`absolute -left-[34px] flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${STEP_DOT[s.status]}`}>
            {s.status === 'done' ? '✓' : s.status === 'failed' ? '✕' : i + 1}
          </span>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold text-slate-800">{s.label}</span>
            {s.key === 'mirrored' ? (
              s.extra?.ledger_record_id != null ? (
                <button onClick={() => onOpenRecord?.(s.extra.ledger_record_id)} className="rounded-md bg-violet-50 px-2 py-0.5 text-xs font-semibold text-violet-700 hover:bg-violet-100">
                  P2P_TRADE #{s.extra.ledger_record_id} · open record & Verify →
                </button>
              ) : (
                <span className="text-xs text-slate-500">{trade.status === 'settled' ? 'waiting for the ledger' : 'after settlement'}</span>
              )
            ) : (
              <>
                {s.tx_hash && <Hash value={s.tx_hash} />}
                {s.block != null && <span className="text-xs text-violet-700">block #{s.block}</span>}
                {s.gas != null && <span className="text-xs text-slate-500">gas {fmtNum(s.gas)}</span>}
                {!s.tx_hash && s.status !== 'done' && <span className="text-xs text-slate-400">not sent yet</span>}
              </>
            )}
          </div>
          {s.key === 'registered' && Array.isArray(s.extra) && (
            <div className="mt-0.5 space-y-0.5 text-xs text-slate-500">
              {s.extra.map((e) => (
                <div key={e.who}>
                  {nodeLabel(e.who)}: {e.block != null ? `block #${e.block}, gas ${fmtNum(e.gas)}` : 'not registered yet'} {e.tx_hash && <span className="font-mono">({shortHash(e.tx_hash)})</span>}
                </div>
              ))}
            </div>
          )}
        </li>
      ))}
    </ol>
  )
}

export function TradeJourney({ trades, onOpenRecord }) {
  const [openId, setOpenId] = useState(null)
  const list = trades
  const selected = list.find((t) => t.id === openId) ?? list[0]
  if (!list.length) return <EmptyState icon="rupee">No live-market trades yet. A trade needs one prosumer with surplus and another with a deficit.</EmptyState>
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,320px)_1fr]">
      <ul className="max-h-[420px] divide-y divide-slate-100 overflow-y-auto rounded-xl border border-slate-200">
        {list.map((t) => (
          <li key={t.id}>
            <button onClick={() => setOpenId(t.id)} className={`w-full px-3 py-2 text-left text-sm ${selected?.id === t.id ? 'bg-violet-50' : 'hover:bg-slate-50'}`} data-testid="trade-row">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-slate-800">{nodeLabel(t.seller)} → {nodeLabel(t.buyer)}</span>
                <Pill tone={t.status === 'settled' ? 'ok' : t.status === 'failed' ? 'bad' : 'warn'}>{t.status === 'settled' ? 'Settled' : t.status === 'failed' ? 'Failed' : 'In progress'}</Pill>
              </div>
              <div className="text-xs text-slate-500">
                Interval #{t.interval_id} · {fmtNum((t.settled_wh ?? t.matched_wh) / 1000, 3)} kWh @ {fmtNum(t.price_milli / 1000, 2)}
                {t.pay_milli != null && ` = ${credits(t.pay_milli)} demo credits`}
              </div>
            </button>
          </li>
        ))}
      </ul>
      {selected && (
        <div className="rounded-xl border border-slate-200 p-4">
          <div className="mb-3 text-sm text-slate-700">
            <span className="font-semibold">{nodeLabel(selected.seller)}</span> sold to <span className="font-semibold">{nodeLabel(selected.buyer)}</span>:{' '}
            matched {fmtNum(selected.matched_wh / 1000, 3)} kWh
            {selected.meter_seller_wh != null && <>, metered {fmtNum(selected.meter_seller_wh / 1000, 3)} / {fmtNum((selected.meter_buyer_wh ?? 0) / 1000, 3)} kWh (seller / buyer, computed from simulated readings)</>}
            {selected.pay_milli != null && <>, paid <span className="font-semibold">{credits(selected.pay_milli)} demo credits</span> (= price × min(q_seller, q_buyer))</>}.
          </div>
          <Journey trade={selected} onOpenRecord={onOpenRecord} />
          {selected.error && <p className="mt-2 text-xs text-red-700">{selected.error}</p>}
        </div>
      )}
    </div>
  )
}

// (d) Market events feed (used by the "Market events" filter of the ledger explorer)
const KIND = {
  registered: { label: 'Registered', cls: 'bg-violet-50 text-violet-700' },
  offer: { label: 'Offer', cls: 'bg-emerald-50 text-emerald-700' },
  bid: { label: 'Bid', cls: 'bg-amber-50 text-amber-700' },
  matched: { label: 'Matched', cls: 'bg-indigo-50 text-indigo-700' },
  metered: { label: 'Metered', cls: 'bg-sky-50 text-sky-700' },
  settled: { label: 'Settled', cls: 'bg-emerald-50 text-emerald-700' },
  mirrored: { label: 'Ledger', cls: 'bg-violet-50 text-violet-700' },
}

// eslint-disable-next-line react-refresh/only-export-components
export function buildMarketEvents(market) {
  const ev = []
  for (const p of market.prosumerList) {
    const r = p.registration
    if (r?.tx_hash || r?.block_number != null) ev.push({ id: `reg-${p.node_id}`, kind: 'registered', text: `${nodeLabel(p.node_id)} registered`, tx: r.tx_hash, block: r.block_number, gas: r.gas_used, status: r.status })
  }
  for (const o of Object.values(market.orders)) {
    if (!o.tx_hash) continue
    ev.push({ id: `o-${o.id}`, kind: o.side, text: `${nodeLabel(o.node_id)} ${o.side === 'offer' ? 'offers' : 'bids'} ${fmtNum(o.qty_wh / 1000, 3)} kWh @ ${fmtNum(o.price_milli / 1000, 2)}`, tx: o.tx_hash, block: o.block_number, gas: o.gas_used, status: o.status })
  }
  for (const t of market.trades) {
    const who = `${nodeLabel(t.seller)} → ${nodeLabel(t.buyer)}`
    if (t.match_tx_hash) ev.push({ id: `m-${t.id}`, kind: 'matched', text: `${who} matched ${fmtNum(t.matched_wh / 1000, 3)} kWh`, tx: t.match_tx_hash, block: t.match_block, gas: t.match_gas, status: t.match_block != null ? 'confirmed' : 'pending' })
    if (t.meter_tx_hash) ev.push({ id: `me-${t.id}`, kind: 'metered', text: `${who} metered ${fmtNum((t.meter_seller_wh ?? 0) / 1000, 3)} / ${fmtNum((t.meter_buyer_wh ?? 0) / 1000, 3)} kWh`, tx: t.meter_tx_hash, block: t.meter_block, gas: t.meter_gas, status: t.meter_block != null ? 'confirmed' : 'pending' })
    if (t.settle_tx_hash) ev.push({ id: `s-${t.id}`, kind: 'settled', text: `${who} settled ${fmtNum((t.settled_wh ?? 0) / 1000, 3)} kWh = ${credits(t.pay_milli)} demo credits`, tx: t.settle_tx_hash, block: t.settle_block, gas: t.settle_gas, status: t.settle_block != null ? 'confirmed' : 'pending' })
    if (t.ledger_record_id != null) ev.push({ id: `l-${t.id}`, kind: 'mirrored', text: `${who} mirrored to the ledger`, ledger: t.ledger_record_id, block: t.settle_block, status: 'confirmed' })
  }
  return ev.sort((a, b) => (b.block ?? 1e12) - (a.block ?? 1e12) || String(b.id).localeCompare(String(a.id)))
}

export function MarketEventFeed({ market, onOpenRecord }) {
  const events = useMemo(() => buildMarketEvents(market), [market])
  if (!events.length) return <p className="p-4 text-sm text-slate-500">No market events yet.</p>
  return (
    <ul className="divide-y divide-slate-100" data-testid="market-event-feed">
      {events.map((e) => {
        const k = KIND[e.kind] ?? KIND.matched
        return (
          <li key={e.id} className="px-4 py-2.5 text-xs">
            <div className="flex items-center gap-2">
              <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${k.cls}`}>{k.label}</span>
              <span className="text-slate-800">{e.text}</span>
            </div>
            <div className="mt-1 flex items-center gap-2 text-slate-500">
              <TxStatus status={e.status} />
              {e.block != null && <span className="text-violet-700">block #{e.block}</span>}
              {e.gas != null && <span>gas {fmtNum(e.gas)}</span>}
              {e.tx && <Hash value={e.tx} />}
              {e.ledger != null && (
                <button onClick={() => onOpenRecord?.(e.ledger)} className="font-medium text-violet-700 hover:underline">
                  ledger record #{e.ledger} →
                </button>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

// The full "Prosumer market" section of the Blockchain view: (a) + (b) + (c).
export default function ProsumerMarketPanel({ market, onOpenRecord, highlight }) {
  const { status } = market
  return (
    <div className="space-y-6 overflow-y-auto p-5" data-testid="prosumer-market-panel">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="font-semibold" style={{ color: CHAIN_COLOR }}>EnergyMarket contract</span>
        <span className="font-mono text-xs text-slate-600">{shortHash(status?.contract?.contract_address, 8)}</span>
        {status?.contract?.contract_address && <CopyButton text={status.contract.contract_address} label="Copy contract address" />}
        {status && <Pill tone={status.connected ? 'ok' : 'bad'}>{status.connected ? 'Connected' : 'Chain unreachable'}</Pill>}
        <span className="text-slate-500">
          {status?.counts?.market_intervals ?? 0} intervals · {status?.counts?.settled_trades ?? 0} settled trades · every {status?.interval_seconds ?? '—'}s
        </span>
      </div>
      <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">{MARKET_NOTE} Metering is computed from the simulated readings of each interval.</p>
      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-800">Registered prosumers</h3>
        <RegistrationsTable prosumers={market.prosumerList} highlight={highlight} />
      </section>
      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-800">Order book · current interval</h3>
        <OrderBook orders={market.currentOrders} interval={market.latestInterval} now={market.now} />
      </section>
      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-800">Trade journey</h3>
        <TradeJourney trades={market.trades} onOpenRecord={onOpenRecord} />
      </section>
    </div>
  )
}
