import { SourceIcon } from '../ui/icons'
import { Pill } from '../ui/components'
import { fmtNum } from '../ui/format'
import { HEALTH_LABEL, HEALTH_TONE, SOURCE_COLORS, nodeLabel } from '../ui/theme'
import { SourceBadge } from './EnergyNode'
import { DetectorRows } from './TwinNode'

// Grid Map side panel: key values of the selected node. Used by both the
// Live View and the Digital Twin view (each passes its own node object).

function Row({ label, children }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-800">{children}</span>
    </div>
  )
}

export default function NodeSidePanel({ node, twin = false }) {
  if (!node) return <p className="text-sm text-slate-500">Click a node on the map to see its values.</p>
  const r = node.latest_reading
  const color = SOURCE_COLORS[node.type] ?? SOURCE_COLORS.grid
  const isBus = node.type === 'bus'
  const isGrid = node.type === 'grid'

  return (
    <div>
      <div className="flex items-center gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl" style={{ background: `${color}1f`, color }}>
          <SourceIcon type={node.type} size={22} />
        </span>
        <div className="min-w-0">
          <div className="truncate text-base font-semibold text-slate-900">{nodeLabel(node.node_id)}</div>
          <div className="truncate font-mono text-xs text-slate-400">{node.node_id}</div>
        </div>
      </div>

      <div className="mt-4 divide-y divide-slate-100">
        {!isBus && !isGrid && (
          <>
            <Row label="Status">
              <Pill tone={node.isolated ? 'bad' : HEALTH_TONE[node.health_status] ?? 'ok'}>
                {node.isolated ? 'Isolated' : HEALTH_LABEL[node.health_status] ?? 'Normal'}
              </Pill>
            </Row>
            <Row label="Data source">
              <SourceBadge sourceType={node.source_type} />
            </Row>
            <Row label="Power output">{r ? `${fmtNum(r.power_output, 1)} kW` : '—'}</Row>
            {r?.wind_speed != null && <Row label="Wind speed">{fmtNum(r.wind_speed, 1)} m/s</Row>}
            {r?.temperature != null && <Row label="Temperature">{fmtNum(r.temperature, 1)} °C</Row>}
            {r?.vibration != null && <Row label="Vibration">{fmtNum(r.vibration, 2)}</Row>}
            {node.rated_capacity_kw != null && <Row label="Rated capacity">{fmtNum(node.rated_capacity_kw)} kW</Row>}
            {twin && !node.isolated && <Row label="Routed via">{nodeLabel(node.active_connection)}</Row>}
            {twin && node.load_share < 1 && !node.isolated && <Row label="Curtailed to">{Math.round(node.load_share * 100)}%</Row>}
            <Row label="Last updated">{node.last_updated ? new Date(node.last_updated).toLocaleTimeString() : '—'}</Row>
          </>
        )}
        {isBus && (
          <>
            <Row label="Load">{fmtNum(node.current_load_kw)} kW</Row>
            <Row label="Capacity">{fmtNum(node.capacity_kw)} kW</Row>
            <Row label="Status">
              <Pill tone={node.current_load_kw > node.capacity_kw ? 'bad' : 'ok'}>
                {node.current_load_kw > node.capacity_kw ? 'Overloaded' : 'Within capacity'}
              </Pill>
            </Row>
          </>
        )}
      </div>

      {twin && node.detectors && (
        <div className="mt-4 rounded-xl bg-slate-50 p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Fault detectors</div>
          <DetectorRows data={node} />
        </div>
      )}
    </div>
  )
}
