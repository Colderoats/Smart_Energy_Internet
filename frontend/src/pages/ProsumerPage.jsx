import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiJson } from '../auth/api'
import { useAuth } from '../auth/AuthContext'
import { navigate } from '../auth/router'
import { useMarketSocket } from '../hooks/useMarketSocket'
import { Button, Card, CopyButton, EmptyState, Pill } from '../ui/components'
import { fmtNum, shortHash } from '../ui/format'
import { CHAIN_COLOR, nodeLabel } from '../ui/theme'

// /prosumer: the page a prosumer lands on after login. One building, own node only (the backend
// scopes every /p2p/* call to the session's node). Live updates come from useMarketSocket (the
// socket pushes market_* messages; this page re-reads /p2p/* when they arrive, there is no polling).
const BANNER = 'Simulated building: solar estimated from live weather, load synthetic. Amounts are demo credits.'

const ROLE_TONE = { surplus: 'ok', deficit: 'warn', balanced: 'idle' }
// Trade status chip: pending -> matched -> settled (failed if the contract rejected a step).
const TRADE_TONE = { pending: 'warn', matched: 'info', settled: 'ok', failed: 'bad' }
const ORDER_TONE = { planned: 'idle', pending: 'warn', in_block: 'info', confirmed: 'chain', failed: 'bad' }
const ORDER_LABEL = { planned: 'planned', pending: 'pending', in_block: 'in block', confirmed: 'on chain', failed: 'failed' }

const credits = (milli) => fmtNum(milli / 1000, 3)

function OrderCard({ title, subtitle, priceLabel, enabled, why, maxKwh, bounds, defaultPrice, onSubmit, prefix }) {
  const [kwh, setKwh] = useState('')
  const [price, setPrice] = useState('')
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState(null)
  const shownPrice = price === '' ? (defaultPrice ?? '') : price

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setFeedback(null)
    try {
      const note = await onSubmit(Number(kwh), Number(shownPrice))
      setFeedback({ ok: true, text: note })
      setKwh('')
    } catch (err) {
      setFeedback({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const input = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm disabled:bg-slate-100 disabled:text-slate-400'
  return (
    <Card title={title} subtitle={subtitle} className={enabled ? '' : 'opacity-70'}>
      <form onSubmit={submit} className="space-y-3" data-testid={`${prefix}-card`}>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-sm font-medium text-slate-600">
            Quantity (kWh)
            <input
              name={`${prefix}-kwh`}
              data-testid={`${prefix}-kwh`}
              type="number"
              step="0.001"
              min="0"
              max={maxKwh || undefined}
              value={kwh}
              onChange={(e) => setKwh(e.target.value)}
              disabled={!enabled || busy}
              className={input}
              required
            />
          </label>
          <label className="text-sm font-medium text-slate-600">
            {priceLabel} (credits/kWh)
            <input
              name={`${prefix}-price`}
              data-testid={`${prefix}-price`}
              type="number"
              step="0.01"
              min={bounds?.min}
              max={bounds?.max}
              value={shownPrice}
              onChange={(e) => setPrice(e.target.value)}
              disabled={!enabled || busy}
              className={input}
              required
            />
          </label>
        </div>
        <p className="text-xs text-slate-500">
          {enabled
            ? `Up to ${fmtNum(maxKwh, 3)} kWh this interval · price ${bounds?.min}–${bounds?.max} credits/kWh. Trades at the seller's ask.`
            : why}
        </p>
        <Button type="submit" disabled={!enabled || busy || !kwh} data-testid={`${prefix}-submit`}>
          {busy ? 'Placing…' : title}
        </Button>
        {feedback && (
          <p role={feedback.ok ? 'status' : 'alert'} data-testid={`${prefix}-feedback`} className={`text-sm ${feedback.ok ? 'text-emerald-700' : 'text-red-700'}`}>
            {feedback.text}
          </p>
        )}
      </form>
    </Card>
  )
}

function Th({ children, right }) {
  return <th className={`px-3 py-2 text-xs font-medium text-slate-500 ${right ? 'text-right' : 'text-left'}`}>{children}</th>
}

function BookTable({ book }) {
  const rows = useMemo(() => {
    const side = (list, label) => list.map((o) => ({ ...o, label, key: `o${o.id}` }))
    return [...side(book?.offers ?? [], 'Offer'), ...side(book?.bids ?? [], 'Bid')]
  }, [book])
  const queued = book?.queued ?? []
  if (!rows.length && !queued.length) {
    return <EmptyState icon="market">No open orders in this interval yet. Orders appear when the next interval opens.</EmptyState>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="book-table">
        <thead className="border-b border-slate-200">
          <tr>
            <Th>Side</Th>
            <Th>Building</Th>
            <Th right>Open kWh</Th>
            <Th right>Price</Th>
            <Th>Status</Th>
            <Th right>Block</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {queued.map((q) => (
            <tr key={`q${q.id}`} className="bg-indigo-50/60" data-testid="book-queued">
              <td className="px-3 py-2 font-medium">{q.side === 'offer' ? 'Offer' : 'Bid'}</td>
              <td className="px-3 py-2">You</td>
              <td className="px-3 py-2 text-right tabular-nums">{fmtNum(q.qty_wh / 1000, 3)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{credits(q.price_milli)}</td>
              <td className="px-3 py-2"><Pill tone="info">queued · next interval</Pill></td>
              <td className="px-3 py-2 text-right text-slate-400">—</td>
            </tr>
          ))}
          {rows.map((o) => (
            <tr key={o.key} className={o.mine ? 'bg-violet-50/60' : ''}>
              <td className="px-3 py-2 font-medium">{o.label}</td>
              <td className="px-3 py-2">{o.mine ? 'You' : nodeLabel(o.node_id)}{o.manual && <span className="ml-1 text-xs text-slate-400">manual</span>}</td>
              <td className="px-3 py-2 text-right tabular-nums">{fmtNum(o.remaining_wh / 1000, 3)} <span className="text-slate-400">/ {fmtNum(o.qty_wh / 1000, 3)}</span></td>
              <td className="px-3 py-2 text-right tabular-nums">{credits(o.price_milli)}</td>
              <td className="px-3 py-2"><Pill tone={ORDER_TONE[o.status] ?? 'idle'}>{ORDER_LABEL[o.status] ?? o.status}</Pill></td>
              <td className="px-3 py-2 text-right tabular-nums">{o.block_number ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TradesTable({ trades }) {
  if (!trades.length) return <EmptyState icon="market">No trades yet. Place an order, it is matched when the next interval opens.</EmptyState>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="trades-table">
        <thead className="border-b border-slate-200">
          <tr>
            <Th>Trade</Th>
            <Th>Side</Th>
            <Th>Counterparty</Th>
            <Th right>kWh</Th>
            <Th right>Price</Th>
            <Th right>Credits</Th>
            <Th>Status</Th>
            <Th right>Block</Th>
            <Th>Tx</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {trades.map((t) => (
            <tr key={t.id} data-testid="trade-row" data-status={t.status}>
              <td className="px-3 py-2 tabular-nums text-slate-500">#{t.id}</td>
              <td className="px-3 py-2 font-medium">{t.side === 'sell' ? 'Sold' : 'Bought'}</td>
              <td className="px-3 py-2">{nodeLabel(t.counterparty)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{fmtNum((t.settled_wh ?? t.matched_wh) / 1000, 3)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{credits(t.price_milli)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{t.pay_milli == null ? '—' : credits(t.pay_milli)}</td>
              <td className="px-3 py-2"><Pill tone={TRADE_TONE[t.status] ?? 'idle'}>{t.status}</Pill></td>
              <td className="px-3 py-2 text-right tabular-nums" data-testid="trade-block">{t.block_number ?? '—'}</td>
              <td className="px-3 py-2 font-mono text-xs text-slate-500">
                <span className="inline-flex items-center gap-1">{shortHash(t.tx_hash, 4)}{t.tx_hash && <CopyButton text={t.tx_hash} label="Copy tx hash" />}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function ProsumerPage() {
  const { user, logout } = useAuth()
  const market = useMarketSocket({ rest: false })
  const [me, setMe] = useState(null)
  const [book, setBook] = useState(null)
  const [trades, setTrades] = useState([])
  const [error, setError] = useState(null)
  const [autoBusy, setAutoBusy] = useState(false)
  const timer = useRef(null)

  const load = useCallback(async () => {
    try {
      const [m, b, t] = await Promise.all([apiJson('/p2p/me'), apiJson('/p2p/book'), apiJson('/p2p/trades')])
      setMe(m)
      setBook(b)
      setTrades(t.trades)
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  // Re-read when the socket reports a change that concerns the market (debounced; push-driven, not polling).
  const signature = JSON.stringify([
    market.latestInterval?.id,
    market.latestInterval?.status,
    market.trades.map((t) => `${t.id}:${t.status}:${t.step_status}`),
    Object.values(market.orders).map((o) => `${o.id}:${o.status}`),
    market.prosumers[user?.prosumer_node_id]?.net_kw,
  ])
  useEffect(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(load, 300)
    return () => clearTimeout(timer.current)
  }, [signature, load])

  const signOut = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const place = (path, field) => async (kwh, price) => {
    const res = await apiJson(path, { method: 'POST', body: JSON.stringify({ kwh, [field]: price }) })
    await load()
    return res.note
  }

  const toggleAuto = async () => {
    setAutoBusy(true)
    try {
      await apiJson('/p2p/auto', { method: 'POST', body: JSON.stringify({ enabled: !me.auto_trade }) })
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setAutoBusy(false)
    }
  }

  const ends = market.latestInterval ? new Date(market.latestInterval.ends_at).getTime() : null
  const left = ends ? Math.max(0, Math.ceil((ends - market.now) / 1000)) : null
  const role = me?.forecast_role
  const canSell = role === 'surplus'
  const canBuy = role === 'deficit'

  return (
    <div className="min-h-svh bg-slate-50 text-slate-800">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-5 py-4">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600 text-xs font-bold text-white">SEI</span>
          <div>
            <h1 className="text-lg font-semibold leading-tight" data-testid="building-name">{nodeLabel(user?.prosumer_node_id)}</h1>
            <p className="text-xs text-slate-500">{user?.email}</p>
          </div>
          {me && <span data-testid="role-pill"><Pill tone={ROLE_TONE[me.role] ?? 'idle'}>{me.role ?? 'waiting for data'}</Pill></span>}
          <div className="text-sm">
            <span className="text-slate-500">Net </span>
            <span className="font-semibold tabular-nums" data-testid="net-kw">{me?.net_kw == null ? '—' : `${fmtNum(me.net_kw, 2)} kW`}</span>
            {me?.net_kw != null && <span className="text-slate-400"> ({fmtNum(me.generation_kw, 2)} gen − {fmtNum(me.consumption_kw, 2)} load)</span>}
          </div>
          <div className="text-sm">
            <span className="text-slate-500">Balance </span>
            <span className="font-semibold tabular-nums" style={{ color: CHAIN_COLOR }} data-testid="balance">
              {me?.balance_credits == null ? '—' : `${fmtNum(me.balance_credits, 3)} demo credits`}
            </span>
          </div>
          <div className="ml-auto flex items-center gap-3">
            {me && (
              <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
                <input type="checkbox" role="switch" data-testid="auto-toggle" checked={me.auto_trade} disabled={autoBusy} onChange={toggleAuto} className="h-4 w-4 accent-indigo-600" />
                Auto-trade {me.auto_trade ? 'on' : 'off'}
              </label>
            )}
            <Button variant="secondary" onClick={signOut}>Log out</Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-5 px-5 py-6">
        <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800" data-testid="sim-banner">{BANNER}</p>
        {error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</p>}

        <div className="flex flex-wrap items-center gap-3 text-sm text-slate-600">
          <span>
            Interval #{market.latestInterval?.id ?? '—'} · next in <span className="font-semibold tabular-nums text-slate-900">{left == null ? '—' : `${left}s`}</span>
            <span className="text-slate-400"> / {me?.interval_seconds ?? '—'}s</span>
          </span>
          <Pill tone={market.connected ? 'ok' : 'warn'}>{market.connected ? 'Live' : 'Reconnecting…'}</Pill>
          {me && !me.chain_connected && <Pill tone="warn">Chain unreachable · orders are queued</Pill>}
          {me?.address && <span className="font-mono text-xs text-slate-500" title={me.address}>Account {shortHash(me.address, 4)}</span>}
        </div>

        <div className="grid gap-5 md:grid-cols-2">
          <OrderCard
            prefix="sell"
            title="Sell surplus"
            subtitle="Offer your surplus solar to the community."
            priceLabel="Ask"
            enabled={canSell}
            why="Selling is only available while you are in surplus."
            maxKwh={me?.max_kwh}
            bounds={me?.price_bounds}
            defaultPrice={me?.default_ask}
            onSubmit={place('/p2p/offer', 'ask')}
          />
          <OrderCard
            prefix="buy"
            title="Buy energy"
            subtitle="Bid for energy while your load exceeds your solar."
            priceLabel="Max"
            enabled={canBuy}
            why="Buying is only available while you are in deficit."
            maxKwh={me?.max_kwh}
            bounds={me?.price_bounds}
            defaultPrice={me?.default_max}
            onSubmit={place('/p2p/bid', 'max')}
          />
        </div>
        {me && !me.auto_trade && <p className="text-xs text-slate-500">Auto-trade is off: only the orders you place here are traded for your building.</p>}

        <Card title="Live order book" subtitle="Open offers and bids for the current interval">
          <BookTable book={book} />
        </Card>

        <Card title="My trades" subtitle="pending → matched → settled, with the block each step landed in">
          <TradesTable trades={trades} />
        </Card>
      </main>
    </div>
  )
}
