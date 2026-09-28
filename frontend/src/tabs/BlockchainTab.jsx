import { useEffect, useState } from 'react'
import { useBlockchainSocket } from '../hooks/useBlockchainSocket'

// Module 5 — Blockchain tab. Every grid action written to the EnergyLedger
// contract, and each record's journey explained step by step for a
// non-technical viewer. Data arrives by WebSocket push (chain_record /
// chain_status); nothing here polls.

const EVENT_TYPES = {
  ENERGY_REDISTRIBUTION: { label: 'Energy redistribution', icon: '🔀', badge: 'bg-sky-900 text-sky-300' },
  P2P_TRADE: { label: 'P2P trade', icon: '🤝', badge: 'bg-amber-900 text-amber-300' },
  FAULT_ALERT: { label: 'Fault alert', icon: '⚠️', badge: 'bg-red-900 text-red-300' },
  FL_ROUND: { label: 'Federated round', icon: '🧠', badge: 'bg-teal-900 text-teal-300' },
}

const PROVENANCE = {
  simulated: { label: 'Simulated', cls: 'border-amber-500 text-amber-300' },
  replayed_scada: { label: 'Replayed SCADA', cls: 'border-violet-500 text-violet-300' },
  live_api: { label: 'Live API', cls: 'border-sky-500 text-sky-300' },
  offline_federated_run: { label: 'Offline federated run', cls: 'border-teal-500 text-teal-300' },
}

const STATUS = {
  queued: { label: 'Pending', cls: 'bg-slate-700 text-slate-200' },
  submitted: { label: 'Sent', cls: 'bg-indigo-800 text-indigo-200' },
  included: { label: 'In a block', cls: 'bg-blue-800 text-blue-200' },
  confirmed: { label: 'Confirmed', cls: 'bg-emerald-800 text-emerald-200' },
  failed: { label: 'Failed', cls: 'bg-red-800 text-red-200' },
}

const STEPS = {
  what_happened: {
    title: 'What happened',
    explain: 'The grid event that triggered this record, and where its data came from.',
  },
  data_packaged: {
    title: 'Data packaged',
    explain: 'All the facts about the event are bundled into one exact, ordered text package. This full copy is kept in our database (off-chain).',
  },
  fingerprint: {
    title: 'Fingerprint created',
    explain: 'A hash is a short digital fingerprint of the data. Changing even one character of the data gives a completely different fingerprint.',
  },
  tx_sent: {
    title: 'Sent to the blockchain',
    explain: 'The fingerprint is sent to the EnergyLedger smart contract as a signed transaction. The transaction hash is its receipt number.',
  },
  in_block: {
    title: 'Included in a block',
    explain: 'The network wrote the transaction into a block, a batch of records chained to all the blocks before it. Gas is the computing cost of writing it.',
  },
  confirmed_locked: {
    title: 'Confirmed and locked',
    explain: 'Enough blocks now sit on top of it. The contract has no edit or delete function, so this record can never be changed or removed by anyone.',
  },
  verified: {
    title: 'Verified',
    explain: 'We re-create the fingerprint from the stored copy and compare it with the one locked on the blockchain. If they match, the data is untouched.',
  },
}

const STEP_DOT = {
  done: 'bg-emerald-500 text-emerald-950',
  active: 'bg-amber-400 text-amber-950 animate-pulse',
  pending: 'bg-slate-700 text-slate-300',
  failed: 'bg-red-500 text-red-950',
}

function short(hash, n = 6) {
  if (!hash) return '—'
  return hash.length > 2 * n + 2 ? `${hash.slice(0, n + 2)}…${hash.slice(-n)}` : hash
}

function fmtTime(iso) {
  if (!iso) return null
  const d = new Date(iso)
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString()}`
}

function ProvenanceBadge({ value }) {
  const p = PROVENANCE[value] ?? { label: value, cls: 'border-slate-500 text-slate-300' }
  return <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${p.cls}`}>{p.label}</span>
}

function StatusChip({ record }) {
  const s = STATUS[record.status] ?? { label: record.status, cls: 'bg-slate-700' }
  const retrying = record.status === 'queued' && record.last_error
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${s.cls}`}>
      {retrying ? 'Pending (retrying)' : s.label}
      {record.status === 'included' && record.required_confirmations
        ? ` ${record.confirmations}/${record.required_confirmations}`
        : ''}
    </span>
  )
}

function Explainer({ text }) {
  return (
    <span className="group relative ml-1 inline-block cursor-help align-middle">
      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-slate-700 text-[10px] font-bold text-slate-300">?</span>
      <span className="pointer-events-none absolute left-5 top-0 z-20 hidden w-64 rounded-md border border-slate-700 bg-slate-900 p-2 text-[11px] font-normal text-slate-300 shadow-lg group-hover:block">
        {text}
      </span>
    </span>
  )
}

function Header({ status, wsConnected, onRecheck, checking }) {
  if (!status) {
    return <div className="border-b border-slate-800 px-4 py-3 text-xs text-slate-400">Loading blockchain status…</div>
  }
  const integrity = status.integrity
  const integrityView =
    !integrity || integrity.state === 'unknown'
      ? { label: 'Integrity unknown', cls: 'bg-slate-800 text-slate-300', icon: '❔' }
      : integrity.state === 'intact'
        ? { label: 'Chain integrity: intact', cls: 'bg-emerald-900 text-emerald-300', icon: '🛡️' }
        : { label: 'Chain integrity: MISMATCH', cls: 'bg-red-900 text-red-200', icon: '🚨' }
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-slate-800 px-4 py-2 text-xs">
      <span className="flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${status.connected ? 'bg-emerald-400' : 'bg-red-400'}`} />
        <span className="font-semibold text-slate-200">
          {status.connected ? 'Blockchain connected' : status.enabled ? 'Blockchain unreachable' : 'Ledger disabled'}
        </span>
      </span>
      <span className="text-slate-400">
        Network: <span className="text-slate-200">{status.network_label ?? status.network}</span>
        {status.chain_id ? <span className="text-slate-500"> (chain {status.chain_id})</span> : null}
      </span>
      <span className="text-slate-400" title={status.contract_address ?? ''}>
        Contract: <span className="font-mono text-slate-200">{short(status.contract_address)}</span>
      </span>
      <span className="text-slate-400">
        Records: <span className="text-slate-200">{status.offchain?.total ?? '—'}</span>
        {status.onchain_record_count != null && (
          <span className="text-slate-500"> ({status.onchain_record_count} on the current chain)</span>
        )}
      </span>
      {status.queue_depth > 0 && <span className="text-amber-300">{status.queue_depth} waiting to be sent</span>}
      <span className="ml-auto flex items-center gap-2">
        <span
          className={`rounded-full px-2 py-1 font-semibold ${integrityView.cls}`}
          title={
            integrity
              ? `Checked ${integrity.checked_records ?? 0} records at ${fmtTime(integrity.checked_at)}` +
                (integrity.mismatched_record_ids?.length ? ` — mismatched: #${integrity.mismatched_record_ids.join(', #')}` : '') +
                (integrity.missing_offchain ? ` — ${integrity.missing_offchain} on-chain records missing off-chain` : '')
              : ''
          }
        >
          {integrityView.icon} {integrityView.label}
        </span>
        <button
          onClick={onRecheck}
          disabled={checking}
          className="rounded-md border border-slate-700 px-2 py-1 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          {checking ? 'Checking…' : 'Re-check all'}
        </button>
        <span
          className={`flex items-center gap-1.5 rounded-full px-2 py-1 ${wsConnected ? 'bg-emerald-950 text-emerald-300' : 'bg-red-950 text-red-300'}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${wsConnected ? 'bg-emerald-400' : 'bg-red-400'}`} />
          {wsConnected ? 'Live updates' : 'Updates disconnected'}
        </span>
      </span>
      {!status.connected && status.last_error && (
        <div className="w-full rounded bg-red-950/60 px-2 py-1 text-red-300">
          {status.last_error}. New records are kept and will be sent automatically when the node is back.
        </div>
      )}
    </div>
  )
}

function RecordRow({ record, selected, onSelect }) {
  const et = EVENT_TYPES[record.event_type] ?? { label: record.event_type, icon: '•', badge: 'bg-slate-800' }
  return (
    <li>
      <button
        onClick={() => onSelect(record.id)}
        className={`w-full px-4 py-2.5 text-left text-xs transition-colors ${selected ? 'bg-slate-800' : 'hover:bg-slate-900'}`}
      >
        <div className="flex items-center gap-2">
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${et.badge}`}>
            {et.icon} {et.label}
          </span>
          <ProvenanceBadge value={record.provenance} />
          {record.tampered_at && (
            <span className="rounded bg-red-900 px-1.5 py-0.5 text-[10px] font-semibold text-red-200">TAMPERED (dev demo)</span>
          )}
          <span className="ml-auto text-slate-500">{new Date(record.created_at).toLocaleTimeString()}</span>
        </div>
        <div className="mt-1 text-slate-200">{record.summary}</div>
        <div className="mt-1 flex items-center gap-2 text-slate-500">
          <StatusChip record={record} />
          {record.locked && <span title="Confirmed: can no longer be edited or deleted">🔒</span>}
          <span className="font-mono">tx {short(record.tx_hash)}</span>
          <span className="ml-auto">#{record.id}</span>
        </div>
      </button>
    </li>
  )
}

function StepData({ step, record, onVerify, verifying }) {
  const d = step.data
  switch (step.key) {
    case 'what_happened':
      return (
        <div className="space-y-1">
          <div className="text-slate-200">{d.summary}</div>
          <div>
            Node / actor: <span className="text-slate-200">{d.actor}</span>
            {d.source_ref && (
              <>
                {' · '}Reference: <span className="font-mono text-slate-300">{d.source_ref}</span>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            Data source: <ProvenanceBadge value={d.provenance} />
          </div>
          {record.payload?.provenance_note && <div className="text-slate-500">{record.payload.provenance_note}</div>}
        </div>
      )
    case 'data_packaged':
      return (
        <pre className="max-h-64 overflow-auto rounded bg-slate-950 p-2 font-mono text-[11px] text-slate-300">
          {JSON.stringify(d.payload, null, 2)}
        </pre>
      )
    case 'fingerprint':
      return (
        <div>
          <div className="break-all font-mono text-slate-200">{d.payload_hash}</div>
          <div className="mt-1 text-slate-500">Method: {d.algorithm}. Only this fingerprint goes on the blockchain, not the data itself.</div>
        </div>
      )
    case 'tx_sent':
      return d.tx_hash ? (
        <div>
          Transaction hash: <span className="break-all font-mono text-slate-200">{d.tx_hash}</span>
          {d.explorer_url && (
            <a href={d.explorer_url} target="_blank" rel="noreferrer" className="ml-2 text-sky-400 underline">
              view on Etherscan
            </a>
          )}
          {d.attempts > 1 && <div className="text-slate-500">Sent after {d.attempts} attempts.</div>}
        </div>
      ) : (
        <div>
          Waiting to be sent.
          {d.last_error && <div className="text-amber-300">Last attempt: {d.last_error} (retrying automatically)</div>}
        </div>
      )
    case 'in_block':
      return d.block_number != null ? (
        <div className="space-y-0.5">
          <div>
            Block <span className="text-slate-200">#{d.block_number}</span> · Gas used{' '}
            <span className="text-slate-200">{d.gas_used?.toLocaleString()}</span> · Ledger entry{' '}
            <span className="text-slate-200">#{d.chain_record_id}</span>
          </div>
          <div>
            Block hash: <span className="break-all font-mono text-slate-300">{d.block_hash}</span>
          </div>
          {d.block_timestamp && <div className="text-slate-500">Block time (as reported by the chain): {fmtTime(d.block_timestamp)}</div>}
          {!record.deployment_current && (
            <div className="text-amber-300">
              This record was written to an earlier ledger contract; the local dev chain has since been restarted.
            </div>
          )}
        </div>
      ) : (
        <div>{step.status === 'failed' ? 'The transaction was rejected by the contract.' : 'Waiting for a block.'}</div>
      )
    case 'confirmed_locked':
      return step.status === 'done' ? (
        <div className="text-emerald-300">
          🔒 Locked with {d.confirmations} confirmation{d.confirmations === 1 ? '' : 's'}. It cannot be edited or deleted.
        </div>
      ) : (
        <div>
          {d.confirmations ?? 0} of {d.required_confirmations ?? '?'} confirmations.
        </div>
      )
    case 'verified':
      return (
        <div className="space-y-2">
          <button
            onClick={onVerify}
            disabled={verifying || !['included', 'confirmed'].includes(record.status)}
            className="rounded-md bg-emerald-700 px-3 py-1.5 font-semibold text-white hover:bg-emerald-600 disabled:opacity-40"
          >
            {verifying ? 'Verifying…' : 'Verify integrity'}
          </button>
          {d.result === 'match' && (
            <div className="rounded border border-emerald-600 bg-emerald-950 p-2 text-emerald-200">
              ✅ <span className="font-semibold">Match.</span> {d.explanation}
            </div>
          )}
          {d.result === 'mismatch' && (
            <div className="rounded border border-red-600 bg-red-950 p-2 text-red-200">
              ❌ <span className="font-semibold">Mismatch.</span> {d.explanation}
            </div>
          )}
          {d.result && !['match', 'mismatch'].includes(d.result) && <div className="text-amber-300">{d.explanation}</div>}
          {d.recomputed_hash && (
            <div className="space-y-0.5 font-mono text-[11px]">
              <div>
                <span className="font-sans text-slate-500">Fingerprint of stored copy: </span>
                <span className="break-all">{d.recomputed_hash}</span>
              </div>
              <div>
                <span className="font-sans text-slate-500">Fingerprint on blockchain: </span>
                <span className="break-all">{d.onchain_hash ?? '—'}</span>
              </div>
            </div>
          )}
        </div>
      )
    default:
      return null
  }
}

function RecordDetail({ recordId, lastMessage, devTools, onClose }) {
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState(null)
  const [verifying, setVerifying] = useState(false)
  const [tampering, setTampering] = useState(false)

  const load = () =>
    fetch(`/chain/records/${recordId}`)
      .then(async (res) => {
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || res.statusText)
        setDetail(data)
        setError(null)
      })
      .catch((err) => setError(err.message))

  // Initial load, then reload only when the backend pushes a change for this record.
  useEffect(() => {
    setDetail(null)
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordId])
  useEffect(() => {
    if (lastMessage && lastMessage.id === recordId) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastMessage])

  const verify = async () => {
    setVerifying(true)
    try {
      await fetch(`/chain/verify/${recordId}`, { method: 'POST' })
      await load()
    } finally {
      setVerifying(false)
    }
  }

  const tamper = async () => {
    if (!window.confirm('DEV-ONLY DEMO: edit the off-chain database copy of this record so that Verify fails?')) return
    setTampering(true)
    try {
      await fetch(`/chain/dev/tamper/${recordId}`, { method: 'POST' })
      await load()
    } finally {
      setTampering(false)
    }
  }

  if (error) return <div className="p-4 text-sm text-red-300">Could not load record #{recordId}: {error}</div>
  if (!detail) return <div className="p-4 text-sm text-slate-400">Loading record #{recordId}…</div>

  const { record, steps } = detail
  const et = EVENT_TYPES[record.event_type] ?? { label: record.event_type, icon: '•', badge: 'bg-slate-800' }
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${et.badge}`}>
          {et.icon} {et.label}
        </span>
        <ProvenanceBadge value={record.provenance} />
        <StatusChip record={record} />
        {record.locked && <span title="Immutable">🔒</span>}
        <span className="text-xs text-slate-500">Record #{record.id}</span>
        <button onClick={onClose} className="ml-auto text-xs text-slate-400 hover:text-slate-200">
          Close ✕
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <h3 className="mb-3 text-sm font-semibold text-slate-100">{record.summary}</h3>
        {record.tampered_at && (
          <div className="mb-3 rounded border border-red-700 bg-red-950/60 p-2 text-xs text-red-200">
            DEV-ONLY tamper demo applied {fmtTime(record.tampered_at)}: field <span className="font-mono">{record.tamper_detail?.field}</span>{' '}
            changed from <span className="font-mono">{JSON.stringify(record.tamper_detail?.old_value)}</span> to{' '}
            <span className="font-mono">{JSON.stringify(record.tamper_detail?.new_value)}</span> in the database copy only. The
            blockchain copy was not (and cannot be) changed.
          </div>
        )}
        <ol className="relative space-y-4 border-l border-slate-700 pl-6">
          {steps.map((step) => {
            const meta = STEPS[step.key]
            return (
              <li key={step.key} className="relative">
                <span
                  className={`absolute -left-[34px] flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${STEP_DOT[step.status]}`}
                >
                  {step.status === 'done' ? '✓' : step.status === 'failed' ? '✕' : step.n}
                </span>
                <div className="flex items-center text-xs">
                  <span className="font-semibold text-slate-100">
                    {step.n}. {meta.title}
                  </span>
                  <Explainer text={meta.explain} />
                  <span className="ml-auto text-[11px] text-slate-500">{fmtTime(step.at) ?? '—'}</span>
                </div>
                <div className="mt-1 text-xs text-slate-400">
                  <StepData step={step} record={record} onVerify={verify} verifying={verifying} />
                </div>
              </li>
            )
          })}
        </ol>
        {devTools && (
          <div className="mt-6 rounded border border-dashed border-red-800 p-3 text-xs">
            <div className="font-semibold text-red-300">Developer demo only</div>
            <p className="mt-1 text-slate-400">
              Simulates someone secretly editing the database copy of this record. The blockchain copy stays as it was, so
              Verify will then show a mismatch.
            </p>
            <button
              onClick={tamper}
              disabled={tampering}
              className="mt-2 rounded-md border border-red-700 px-3 py-1.5 font-semibold text-red-300 hover:bg-red-950 disabled:opacity-50"
            >
              {tampering ? 'Tampering…' : 'Tamper with off-chain copy (dev only)'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function BlockchainTab() {
  const [filter, setFilter] = useState(null)
  const [selected, setSelected] = useState(null)
  const [busy, setBusy] = useState(null)
  const [notice, setNotice] = useState(null)
  const [checking, setChecking] = useState(false)
  const { status, records, total, connected, lastMessage, loadError, refreshStatus, loadMore, hasMore } =
    useBlockchainSocket(filter)

  const post = async (label, url, onOk) => {
    setBusy(label)
    setNotice(null)
    try {
      const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || res.statusText)
      onOk(data)
    } catch (err) {
      setNotice({ kind: 'error', text: `${label} failed: ${err.message}` })
    } finally {
      setBusy(null)
    }
  }

  const simulateTrade = () =>
    post('Simulated trade', '/chain/simulate-trade', (data) => {
      setSelected(data.record.id)
      setNotice({ kind: 'ok', text: `Created simulated trade #${data.record.id}. Watch its steps on the right.` })
    })

  const replayFl = () =>
    post('Federated replay', '/chain/replay-fl-rounds', (data) =>
      setNotice({
        kind: 'ok',
        text: `Federated run ${data.run}: ${data.recorded} round(s) recorded, ${data.skipped_already_recorded} already on the ledger.`,
      }),
    )

  const recheck = async () => {
    setChecking(true)
    try {
      await refreshStatus()
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Header status={status} wsConnected={connected} onRecheck={recheck} checking={checking} />

      <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 px-4 py-2 text-xs">
        <span className="text-slate-400">Show:</span>
        {[null, ...Object.keys(EVENT_TYPES)].map((key) => (
          <button
            key={key ?? 'all'}
            onClick={() => setFilter(key)}
            className={`rounded-md px-2.5 py-1 font-medium ${
              filter === key ? 'bg-sky-600 text-white' : 'bg-slate-900 text-slate-400 hover:text-slate-200'
            }`}
          >
            {key ? `${EVENT_TYPES[key].icon} ${EVENT_TYPES[key].label}` : 'All'}
          </button>
        ))}
        <span className="ml-auto flex gap-2">
          <button
            onClick={replayFl}
            disabled={busy !== null}
            className="rounded-md border border-teal-700 px-3 py-1 font-semibold text-teal-300 hover:bg-teal-950 disabled:opacity-50"
            title="Record each round of the offline Module 4 federated run (round_log.json) on the ledger"
          >
            {busy === 'Federated replay' ? 'Recording…' : '🧠 Record federated rounds'}
          </button>
          <button
            onClick={simulateTrade}
            disabled={busy !== null}
            className="rounded-md bg-amber-600 px-3 py-1 font-semibold text-white hover:bg-amber-500 disabled:opacity-50"
            title="Creates a SIMULATED peer-to-peer trade between two twin nodes. No real energy or money moves."
          >
            {busy === 'Simulated trade' ? 'Creating…' : '🤝 Simulate P2P trade'}
          </button>
        </span>
      </div>

      {notice && (
        <div
          className={`border-b px-4 py-1.5 text-xs ${
            notice.kind === 'error' ? 'border-red-900 bg-red-950/50 text-red-300' : 'border-emerald-900 bg-emerald-950/50 text-emerald-300'
          }`}
        >
          {notice.text}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="flex w-[46%] min-w-[360px] flex-col border-r border-slate-800">
          <div className="border-b border-slate-800 px-4 py-2 text-[11px] text-slate-500">
            Newest first · {total} record{total === 1 ? '' : 's'}
            {filter ? ` of type ${EVENT_TYPES[filter].label}` : ''}. Energy trades are simulated: no solar/EV hardware exists
            yet.
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {loadError && <p className="p-4 text-sm text-red-300">Could not load the ledger: {loadError}</p>}
            {!loadError && records.length === 0 && (
              <p className="p-4 text-sm text-slate-400">
                No records yet. They appear automatically when the digital twin reacts to a fault, or use the buttons above.
              </p>
            )}
            <ul className="divide-y divide-slate-800">
              {records.map((r) => (
                <RecordRow key={r.id} record={r} selected={r.id === selected} onSelect={setSelected} />
              ))}
            </ul>
            {hasMore && (
              <button onClick={loadMore} className="w-full py-2 text-xs text-sky-400 hover:bg-slate-900">
                Load older records
              </button>
            )}
          </div>
        </div>
        <div className="min-w-0 flex-1">
          {selected != null ? (
            <RecordDetail
              key={selected}
              recordId={selected}
              lastMessage={lastMessage}
              devTools={status?.dev_tools}
              onClose={() => setSelected(null)}
            />
          ) : (
            <div className="flex h-full items-center justify-center p-8 text-center text-sm text-slate-400">
              <div className="max-w-md space-y-2">
                <div className="text-3xl">⛓️</div>
                <p>Select a record to see its journey onto the blockchain, step by step.</p>
                <p className="text-xs text-slate-500">
                  Each grid action is summarised as a fingerprint (hash) and locked into a tamper-proof ledger. The full details stay in
                  our database; the blockchain proves they were never changed.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default BlockchainTab
