import { useEffect, useMemo, useRef, useState } from 'react'
import { apiFetch } from '../auth/api'
import { openAuthedSocket } from '../auth/socket'

// Prosumer market hook (same pattern as useDigitalTwinSocket / useBlockchainSocket):
// initial REST fetch of /market/*, then push-only updates over /ws/updates
// (market_prosumer_update, market_registration, market_order, market_match,
// market_settlement, market_interval). Everything here is a real endpoint value,
// nothing comes from src/mocks. Prosumers are SIMULATED buildings: solar is estimated
// from live weather, load is synthetic, amounts are demo credits.
const MAX_TRADES = 60

async function getJson(url) {
  const res = await apiFetch(url)
  if (!res.ok) throw new Error(`${url}: ${res.status}`)
  return res.json()
}

export function useMarketSocket() {
  const [status, setStatus] = useState(null)
  const [prosumers, setProsumers] = useState({})
  const [intervals, setIntervals] = useState({})
  const [orders, setOrders] = useState({})
  const [trades, setTrades] = useState({})
  const [connected, setConnected] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const statusTimer = useRef(null)

  const refreshStatus = () => getJson('/market/status').then(setStatus).catch((err) => console.error('Failed to load market status', err))

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    let cancelled = false
    refreshStatus()
    getJson('/market/prosumers')
      .then((d) => !cancelled && setProsumers(Object.fromEntries(d.prosumers.map((p) => [p.node_id, p]))))
      .catch((err) => console.error('Failed to load prosumers', err))
    getJson('/market/trades?limit=30')
      .then((d) => !cancelled && setTrades(Object.fromEntries(d.trades.map((t) => [t.id, t]))))
      .catch(() => {})
    getJson('/market/intervals?limit=4')
      .then(async (d) => {
        if (cancelled) return
        setIntervals(Object.fromEntries(d.intervals.map((i) => [i.id, i])))
        const details = await Promise.all(d.intervals.map((i) => getJson(`/market/intervals/${i.id}`).catch(() => null)))
        if (cancelled) return
        setOrders((prev) => ({ ...Object.fromEntries(details.filter(Boolean).flatMap((x) => x.orders.map((o) => [o.id, o]))), ...prev }))
        setTrades((prev) => ({ ...Object.fromEntries(details.filter(Boolean).flatMap((x) => x.matches.map((t) => [t.id, t]))), ...prev }))
      })
      .catch(() => {})

    const ws = openAuthedSocket({
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      onMessage: (m) => {
        switch (m.type) {
          case 'market_prosumer_update':
            setProsumers((prev) => ({ ...prev, [m.prosumer.node_id]: { ...prev[m.prosumer.node_id], ...m.prosumer } }))
            break
          case 'market_registration':
            setProsumers((prev) => ({
              ...prev,
              [m.registration.node_id]: { ...prev[m.registration.node_id], registration: m.registration, address: m.registration.address ?? prev[m.registration.node_id]?.address },
            }))
            break
          case 'market_order':
            setOrders((prev) => ({ ...prev, [m.order.id]: m.order }))
            break
          case 'market_match':
          case 'market_settlement':
            setTrades((prev) => ({ ...prev, [m.trade.id]: m.trade }))
            break
          case 'market_interval':
            setIntervals((prev) => ({ ...prev, [m.interval.id]: m.interval }))
            clearTimeout(statusTimer.current)
            statusTimer.current = setTimeout(refreshStatus, 400)
            break
          default:
        }
      },
    })
    return () => {
      cancelled = true
      clearTimeout(statusTimer.current)
      ws.close()
    }
  }, [])

  const tradeList = useMemo(() => Object.values(trades).sort((a, b) => b.id - a.id).slice(0, MAX_TRADES), [trades])
  const latestInterval = useMemo(() => {
    const list = Object.values(intervals).filter((i) => i.status !== 'skipped')
    return list.length ? list.reduce((a, b) => (b.id > a.id ? b : a)) : null
  }, [intervals])
  const currentOrders = useMemo(
    () => Object.values(orders).filter((o) => latestInterval && o.interval_id === latestInterval.id).sort((a, b) => a.id - b.id),
    [orders, latestInterval],
  )
  const prosumerList = useMemo(() => Object.values(prosumers), [prosumers])

  return { status, prosumers, prosumerList, intervals, latestInterval, currentOrders, orders, trades: tradeList, connected, now }
}
