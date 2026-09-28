import { useCallback, useEffect, useState } from 'react'
import { apiJson } from '../auth/api'

const STATUS_STYLES = {
  pending: 'bg-sky-900/60 text-sky-200',
  used: 'bg-emerald-900/60 text-emerald-200',
  expired: 'bg-slate-800 text-slate-400',
}

function formatTime(iso) {
  return iso ? new Date(iso).toLocaleString() : '—'
}

export default function InviteAdminPage() {
  const [created, setCreated] = useState(null)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState(null)
  const [copied, setCopied] = useState(false)
  const [invites, setInvites] = useState(null)
  const [listError, setListError] = useState(null)

  const loadInvites = useCallback(() => {
    setListError(null)
    return apiJson('/auth/invites')
      .then((data) => setInvites(data.invites))
      .catch((err) => setListError(err.message))
  }, [])

  useEffect(() => {
    loadInvites()
  }, [loadInvites])

  const generate = async () => {
    setCreating(true)
    setCreateError(null)
    setCopied(false)
    try {
      setCreated(await apiJson('/auth/invites', { method: 'POST', body: '{}' }))
      loadInvites()
    } catch (err) {
      setCreateError(err.message)
    } finally {
      setCreating(false)
    }
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(created.invite_url)
      setCopied(true)
    } catch {
      setCreateError('Could not copy automatically. Select the link and copy it manually.')
    }
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="text-base font-semibold">Invite an admin</h2>
          <p className="mt-1 text-sm text-slate-400">
            Generates a single-use registration link that expires in 48 hours. The link is shown only once; only
            a hash of it is stored.
          </p>
          <button
            onClick={generate}
            disabled={creating}
            className="mt-4 rounded-md bg-sky-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {creating ? 'Generating…' : 'Generate invite link'}
          </button>
          {createError && (
            <p role="alert" className="mt-3 rounded-md border border-red-800 bg-red-950/60 px-3 py-2 text-sm text-red-200">
              {createError}
            </p>
          )}
          {created && (
            <div className="mt-4 rounded-md border border-amber-700 bg-amber-950/40 p-3">
              <p className="text-xs font-medium text-amber-200">
                Copy this link now. It will not be shown again. Expires {formatTime(created.expires_at)}.
              </p>
              <div className="mt-2 flex gap-2">
                <input
                  readOnly
                  value={created.invite_url}
                  onFocus={(e) => e.target.select()}
                  className="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-xs text-slate-200"
                />
                <button
                  onClick={copy}
                  className="rounded-md bg-slate-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-600"
                >
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold">Invites</h2>
            <button onClick={loadInvites} className="text-xs text-sky-400 hover:text-sky-300">
              Refresh
            </button>
          </div>
          {listError ? (
            <p role="alert" className="mt-3 text-sm text-red-300">
              Could not load invites: {listError}
            </p>
          ) : invites === null ? (
            <p className="mt-3 text-sm text-slate-400">Loading invites…</p>
          ) : invites.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">No invites yet.</p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-slate-400">
                  <tr>
                    <th className="py-1.5 pr-3 font-medium">Status</th>
                    <th className="py-1.5 pr-3 font-medium">Created by</th>
                    <th className="py-1.5 pr-3 font-medium">Created</th>
                    <th className="py-1.5 pr-3 font-medium">Expires</th>
                    <th className="py-1.5 font-medium">Used by</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {invites.map((inv) => (
                    <tr key={inv.id}>
                      <td className="py-1.5 pr-3">
                        <span className={`rounded px-1.5 py-0.5 text-xs ${STATUS_STYLES[inv.status]}`}>{inv.status}</span>
                      </td>
                      <td className="py-1.5 pr-3 text-slate-300">{inv.created_by_email}</td>
                      <td className="py-1.5 pr-3 text-slate-400">{formatTime(inv.created_at)}</td>
                      <td className="py-1.5 pr-3 text-slate-400">{formatTime(inv.expires_at)}</td>
                      <td className="py-1.5 text-slate-300">{inv.used_by_email ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
