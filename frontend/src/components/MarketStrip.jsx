import { navigate } from '../auth/router'
import { Pill } from '../ui/components'
import { fmtNum } from '../ui/format'
import Icon from '../ui/icons'
import { CHAIN_COLOR, nodeLabel } from '../ui/theme'

// "Prosumer market" strip on the Digital Twin tab: interval countdown, total kWh traded and the
// last 5 trades. Prosumers are simulated buildings; amounts are demo credits.
export default function MarketStrip({ market }) {
  const { status, latestInterval, trades, now } = market
  const ends = latestInterval ? new Date(latestInterval.ends_at).getTime() : null
  const left = ends ? Math.max(0, Math.ceil((ends - now) / 1000)) : null
  const tradedKwh = (status?.counts?.settled_wh ?? 0) / 1000
  const last5 = trades.slice(0, 5)
  return (
    <div className="rounded-2xl border border-violet-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <span className="flex items-center gap-2 text-sm font-semibold" style={{ color: CHAIN_COLOR }}>
          <Icon name="market" size={18} /> Prosumer market
        </span>
        {!status?.enabled && status && <Pill tone="idle">Market disabled</Pill>}
        <span className="text-sm text-slate-600">
          Interval #{latestInterval?.id ?? '—'} · next in <span className="font-semibold tabular-nums text-slate-900" data-testid="market-countdown">{left == null ? '—' : `${left}s`}</span>
          <span className="text-slate-400"> / {status?.interval_seconds ?? '—'}s</span>
        </span>
        <span className="text-sm text-slate-600">
          Traded: <span className="font-semibold text-slate-900">{fmtNum(tradedKwh, 3)} kWh</span> in {status?.counts?.settled_trades ?? 0} settled trades
        </span>
        {status && !status.connected && <Pill tone="warn">Chain unreachable · trades queued</Pill>}
        {status?.demo_irradiance && <Pill tone="warn" dot={false}>Demo irradiance {status.irradiance_override} W/m²</Pill>}
        <button onClick={() => navigate('/dashboard/chain')} className="ml-auto text-xs font-medium text-violet-700 hover:underline">
          Blockchain view →
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {last5.length === 0 ? (
          <span className="text-xs text-slate-500">No trades yet. Trades appear when one prosumer has surplus and another a deficit.</span>
        ) : (
          last5.map((t) => (
            <span key={t.id} className="inline-flex items-center gap-1.5 rounded-lg bg-violet-50 px-2 py-1 text-xs text-violet-800">
              {nodeLabel(t.seller)} → {nodeLabel(t.buyer)} · {fmtNum((t.settled_wh ?? t.matched_wh) / 1000, 3)} kWh ·{' '}
              {t.status === 'settled' ? `settled #${t.settle_block}` : t.status.replace('_', ' ')}
            </span>
          ))
        )}
      </div>
      <p className="mt-2 text-[11px] text-slate-500">
        Prosumers are simulated buildings: solar estimated from live weather, load synthetic. Amounts are demo credits.
      </p>
    </div>
  )
}
