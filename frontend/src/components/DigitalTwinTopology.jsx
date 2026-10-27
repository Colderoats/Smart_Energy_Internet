import { useEffect, useMemo, useRef, useState } from 'react'
import { ReactFlow, Background, Controls } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import TwinNode from './TwinNode'
import FlowEdge, { TradeEdge, flowWidth } from './FlowEdge'
import { SOURCE_COLORS } from '../ui/theme'

const nodeTypes = { twinNode: TwinNode }
const edgeTypes = { flow: FlowEdge, trade: TradeEdge }

// How long a settled trade edge stays on the map after it settles.
const SETTLED_EDGE_MS = 40000

// How long a just-changed edge stays visibly highlighted after a
// reroute/isolate, so the reconfiguration reads as an event, not a silent
// state update.
const HIGHLIGHT_MS = 2500

// Fixed demo layout, same spirit as Module 1's TopologyView — sources on
// the left, the two collector buses in the middle (this is where reroutes
// visibly swing an edge from one column to the other), grid on the right.
const POSITIONS = {
  // Compact icon cards (UI redesign) — tighter spacing than the Module 3
  // detector-row cards, which now live in the side panel instead.
  wind_01: { x: 0, y: 0 },
  hydro_01: { x: 0, y: 100 },
  wind_scada_kelmarsh_1: { x: 0, y: 200 },
  wind_scada_kelmarsh_2: { x: 0, y: 300 },
  wind_scada_kelmarsh_3: { x: 0, y: 400 },
  wind_scada_kelmarsh_4: { x: 0, y: 500 },
  bus_a: { x: 330, y: 70 },
  bus_c: { x: 330, y: 210 },
  bus_b: { x: 330, y: 350 },
  bus_d: { x: 330, y: 490 },
  grid: { x: 630, y: 260 },
  // Prosumer market: community bus column (4 prosumer cards -> community_bus -> grid).
  // Solar / battery sources sit below the wind and hydro cards (they used to fall back to 0,0 and stack on wind_01).
  solar_01: { x: 0, y: 620 },
  solar_hardware: { x: 0, y: 720 },
  solar_02: { x: 0, y: 820 },
  battery_01: { x: 0, y: 920 },
  prosumer_home_01: { x: 0, y: 1100 },
  prosumer_apartment_01: { x: 0, y: 1260 },
  prosumer_shop_01: { x: 0, y: 1420 },
  prosumer_school_01: { x: 0, y: 1580 },
  community_bus: { x: 640, y: 1350 },
}

// Temporary trade edges for the prosumer market. Seller -> buyer, violet (blockchain): dashed
// with a moving dot while the interval runs, solid once settled on chain ("Settled · block #N").
// Unmatched deficit: a thin grey edge from the grid ("served by grid", not on-chain).
function buildTradeEdges(trades, orders, latestIntervalId, now) {
  const edges = []
  let lane = 0
  for (const t of trades ?? []) {
    const settled = t.status === 'settled'
    const recentlySettled = settled && t.settled_at && now - new Date(t.settled_at).getTime() < SETTLED_EDGE_MS
    if (t.status === 'failed' || !(t.interval_id === latestIntervalId || recentlySettled)) continue
    const kwh = ((settled ? t.settled_wh : t.matched_wh) / 1000).toFixed(3)
    edges.push({
      id: `trade-${t.id}`,
      source: t.seller,
      target: t.buyer,
      sourceHandle: 'trade-out',
      targetHandle: 'trade-in',
      type: 'trade',
      data: { settled, lane: lane++ % 3, label: settled ? `${kwh} kWh · Settled · block #${t.settle_block}` : `${kwh} kWh · pending` },
    })
  }
  for (const o of orders ?? []) {
    if (o.side !== 'bid' || !(o.remaining_wh > 0)) continue
    edges.push({
      id: `grid-${o.id}`,
      source: 'grid',
      sourceHandle: 'grid-out',
      target: o.node_id,
      type: 'flow',
      data: { width: 1.2, color: '#94a3b8', flowing: false, label: `served by grid · ${(o.remaining_wh / 1000).toFixed(3)} kWh` },
    })
  }
  return edges
}

function DigitalTwinTopology({ nodes, onSelectNode, selectedNodeId, trades, orders, latestIntervalId, now }) {
  const flowNodes = useMemo(
    () =>
      Object.values(nodes).map((node) => ({
        id: node.node_id,
        type: 'twinNode',
        position: POSITIONS[node.node_id] ?? { x: 0, y: 0 },
        data: { ...node, onSelect: onSelectNode },
        selected: node.node_id === selectedNodeId,
      })),
    [nodes, onSelectNode, selectedNodeId],
  )

  // The routing edges are derived live from each source node's
  // active_connection/isolated state (not a one-time snapshot) — this is
  // the actual current topology, and it's what makes a self-healing
  // reroute/isolate visibly move the line on the graph instead of leaving
  // it pointing at the node's original bus forever.
  const sourceEdges = useMemo(
    () =>
      Object.values(nodes)
        .filter((node) => node.type !== 'bus' && node.type !== 'grid' && node.type !== 'prosumer' && !node.isolated && node.active_connection)
        .map((node) => ({
          id: `${node.node_id}-${node.active_connection}`,
          source: node.node_id,
          target: node.active_connection,
          // Twin estimate of power on this line: latest output x load share.
          kw: (node.latest_reading?.power_output ?? 0) * (node.load_share ?? 1),
          color: SOURCE_COLORS[node.type] ?? SOURCE_COLORS.grid,
        })),
    [nodes],
  )

  // bus_a -> grid / bus_b -> grid are structural and never reconfigured by
  // self-healing, so they're safe to keep constant.
  const busEdges = useMemo(
    () =>
      Object.values(nodes)
        .filter((node) => node.type === 'bus')
        .map((node) => ({
          id: `${node.node_id}-grid`,
          source: node.node_id,
          target: 'grid',
          kw: node.current_load_kw ?? 0,
          color: SOURCE_COLORS.grid,
        })),
    [nodes],
  )

  // Prosumer <-> community bus links: surplus feeds the bus, deficit draws from it (kW arithmetic).
  const prosumerEdges = useMemo(
    () =>
      Object.values(nodes)
        .filter((node) => node.type === 'prosumer' && node.net_kw != null)
        .map((node) => ({
          id: `${node.node_id}-community_bus`,
          source: node.node_id,
          target: 'community_bus',
          kw: Math.abs(node.net_kw),
          color: node.role === 'surplus' ? SOURCE_COLORS.solar : SOURCE_COLORS.grid,
          reverse: node.role === 'deficit',
          idle: node.role === 'balanced',
        })),
    [nodes],
  )

  const tradeEdges = useMemo(() => buildTradeEdges(trades, orders, latestIntervalId, now), [trades, orders, latestIntervalId, now])

  const highlightedEdgeIds = useRecentlyChangedEdges(sourceEdges)

  const flowEdges = useMemo(() => {
    const all = [...sourceEdges, ...busEdges, ...prosumerEdges]
    const maxKw = Math.max(1, ...all.map((e) => e.kw))
    const flows = all.map(({ kw, color, reverse, idle, ...edge }) => {
      const highlighted = highlightedEdgeIds.has(edge.id)
      return {
        ...edge,
        type: 'flow',
        data: {
          width: highlighted ? Math.max(4, flowWidth(kw, maxKw)) : flowWidth(kw, maxKw),
          color: highlighted ? '#f97316' : color,
          dotColor: highlighted ? '#f97316' : color,
          flowing: kw > 0 && !idle,
          reverse,
        },
      }
    })
    return [...flows, ...tradeEdges]
  }, [sourceEdges, busEdges, prosumerEdges, tradeEdges, highlightedEdgeIds])

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#e2e8f0" gap={22} />
        <Controls />
      </ReactFlow>
    </div>
  )
}

// Tracks each source node's active_connection across renders and returns
// the set of edge ids that just swung to a different target (a reroute) so
// the graph can flash that edge briefly instead of silently updating it.
function useRecentlyChangedEdges(sourceEdges) {
  const prevTargetsRef = useRef({})
  const timersRef = useRef({})
  const [highlighted, setHighlighted] = useState(() => new Set())

  useEffect(() => {
    const prevTargets = prevTargetsRef.current
    const changedIds = sourceEdges
      .filter((edge) => {
        const prevTarget = prevTargets[edge.source]
        return prevTarget !== undefined && prevTarget !== edge.target
      })
      .map((edge) => edge.id)

    if (changedIds.length > 0) {
      setHighlighted((current) => new Set([...current, ...changedIds]))
      for (const id of changedIds) {
        clearTimeout(timersRef.current[id])
        timersRef.current[id] = setTimeout(() => {
          setHighlighted((current) => {
            const next = new Set(current)
            next.delete(id)
            return next
          })
        }, HIGHLIGHT_MS)
      }
    }

    prevTargetsRef.current = Object.fromEntries(sourceEdges.map((edge) => [edge.source, edge.target]))
  }, [sourceEdges])

  useEffect(
    () => () => {
      for (const timer of Object.values(timersRef.current)) clearTimeout(timer)
    },
    [],
  )

  return highlighted
}

export default DigitalTwinTopology
