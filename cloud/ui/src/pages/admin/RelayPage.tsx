import { useCallback, useEffect, useState } from 'react';
import { Webhook, RefreshCw, Loader2, Plus, Trash2, Link2 } from 'lucide-react';

interface Delivery {
  id: string;
  webhook_id: string;
  connected_account_id: string | null;
  agent_slug: string | null;
  status: string;
  attempts: number;
  last_status_code: number | null;
  last_error: string | null;
  created_at: string | null;
  delivered_at: string | null;
  next_attempt_at: string | null;
}

interface AccountLink {
  connected_account_id: string;
  agent_slug: string | null;
  app_name: string | null;
  source: string;
  created_at: string | null;
  last_seen_at: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  delivered: '#22c55e',
  pending: '#eab308',
  unroutable: '#f97316',
  dead: '#ef4444',
};

const thCls = 'text-left text-xs font-medium px-4 py-3';
const thStyle = { color: 'var(--text-dim)' } as const;

function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

export default function RelayPage({ embedded = false }: { embedded?: boolean } = {}) {
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [links, setLinks] = useState<AccountLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddLink, setShowAddLink] = useState(false);
  const [newAccount, setNewAccount] = useState('');
  const [newAgent, setNewAgent] = useState('');
  const [newApp, setNewApp] = useState('');
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    const [dRes, lRes] = await Promise.all([
      fetch('/api/admin/relay/deliveries?limit=100'),
      fetch('/api/admin/relay/links'),
    ]);
    if (dRes.ok) setDeliveries(await dRes.json());
    if (lRes.ok) setLinks(await lRes.json());
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 10000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const handleAddLink = async () => {
    setError(null);
    const res = await fetch('/api/admin/relay/links', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        connected_account_id: newAccount.trim(),
        agent_slug: newAgent.trim(),
        app_name: newApp.trim() || null,
      }),
    });
    if (res.ok) {
      setNewAccount(''); setNewAgent(''); setNewApp(''); setShowAddLink(false);
      await fetchAll();
    } else {
      const body = await res.json().catch(() => null);
      setError(body?.detail || `Failed (${res.status})`);
    }
  };

  const handleDeleteLink = async (accountId: string) => {
    const res = await fetch(`/api/admin/relay/links/${encodeURIComponent(accountId)}`, { method: 'DELETE' });
    if (res.ok) await fetchAll();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  return (
    <div className={embedded ? '' : 'max-w-5xl'}>
      {embedded ? (
        <div className="flex justify-end mb-4">
          <button
            onClick={fetchAll}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-all hover:scale-105"
            style={{ border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}
          >
            <RefreshCw size={14} />
          </button>
        </div>
      ) : (
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
            <Webhook size={20} style={{ color: 'var(--moon)' }} />
            Webhook Relay
          </h2>
          <button
            onClick={fetchAll}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-all hover:scale-105"
            style={{ border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}
          >
            <RefreshCw size={14} />
          </button>
        </div>
      )}

      {/* ── Deliveries ── */}
      <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text)' }}>
        Deliveries <span className="font-normal" style={{ color: 'var(--text-dim)' }}>({deliveries.length})</span>
      </h3>
      {deliveries.length === 0 ? (
        <div className="rounded-2xl p-8 border text-center mb-8" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          <p className="text-sm" style={{ color: 'var(--text-dim)' }}>
            No webhook deliveries yet. Composio trigger events will appear here.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border overflow-hidden mb-8" style={{ borderColor: 'var(--ink-lighter)' }}>
          <table className="w-full">
            <thead>
              <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
                <th className={thCls} style={thStyle}>Status</th>
                <th className={thCls} style={thStyle}>Agent</th>
                <th className={thCls} style={thStyle}>Connected Account</th>
                <th className={thCls} style={thStyle}>Attempts</th>
                <th className={thCls} style={thStyle}>Last Code</th>
                <th className={thCls} style={thStyle}>Received</th>
                <th className={thCls} style={thStyle}>Delivered / Next Try</th>
              </tr>
            </thead>
            <tbody>
              {deliveries.map(d => (
                <tr key={d.id} className="border-t" style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}>
                  <td className="px-4 py-3">
                    <span
                      className="text-xs px-2 py-0.5 rounded-full font-medium"
                      style={{
                        color: STATUS_COLORS[d.status] || 'var(--text-dim)',
                        background: `${STATUS_COLORS[d.status] || '#888'}22`,
                      }}
                      title={d.last_error || undefined}
                    >
                      {d.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm" style={{ color: 'var(--text)' }}>{d.agent_slug || '—'}</td>
                  <td className="px-4 py-3 text-xs font-mono" style={{ color: 'var(--text-dim)' }}>{d.connected_account_id || '—'}</td>
                  <td className="px-4 py-3 text-sm" style={{ color: 'var(--text-dim)' }}>{d.attempts}</td>
                  <td className="px-4 py-3 text-sm" style={{ color: 'var(--text-dim)' }}>{d.last_status_code ?? '—'}</td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-dim)' }}>{fmtTime(d.created_at)}</td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-dim)' }}>
                    {d.status === 'delivered' ? fmtTime(d.delivered_at) : d.status === 'pending' ? fmtTime(d.next_attempt_at) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Account links ── */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold flex items-center gap-1.5" style={{ color: 'var(--text)' }}>
          <Link2 size={14} style={{ color: 'var(--moon)' }} />
          Account Links <span className="font-normal" style={{ color: 'var(--text-dim)' }}>({links.length})</span>
        </h3>
        <button
          onClick={() => setShowAddLink(!showAddLink)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all hover:scale-105"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}
        >
          <Plus size={12} />
          Add Link
        </button>
      </div>

      <p className="text-xs mb-3 max-w-3xl leading-relaxed" style={{ color: 'var(--text-dim)' }}>
        Maps a Composio connected account (<span className="font-mono">ca_…</span>) to the Luna
        agent that owns it, so inbound webhooks from that account get relayed to the right
        machine. Links are created automatically when a user connects an account, or added
        manually here for backfill. <span className="font-mono">App</span> is the Composio
        toolkit (e.g. gmail) and is optional.
      </p>

      {showAddLink && (
        <div className="rounded-xl border p-4 mb-4 flex flex-wrap items-end gap-3" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          {[
            { label: 'Connected account ID', value: newAccount, set: setNewAccount, placeholder: 'ca_…' },
            { label: 'Agent slug', value: newAgent, set: setNewAgent, placeholder: 'alice-my-luna' },
            { label: 'App (optional)', value: newApp, set: setNewApp, placeholder: 'gmail' },
          ].map(f => (
            <label key={f.label} className="flex flex-col gap-1 text-xs" style={{ color: 'var(--text-dim)' }}>
              {f.label}
              <input
                value={f.value}
                onChange={e => f.set(e.target.value)}
                placeholder={f.placeholder}
                className="px-3 py-2 rounded-lg text-sm outline-none"
                style={{ background: 'var(--ink)', border: '1px solid var(--ink-lighter)', color: 'var(--text)' }}
              />
            </label>
          ))}
          <button
            onClick={handleAddLink}
            disabled={!newAccount.trim() || !newAgent.trim()}
            className="px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:scale-105 disabled:opacity-50"
            style={{ background: 'var(--moon)', color: 'var(--ink)' }}
          >
            Save
          </button>
          {error && <span className="text-xs" style={{ color: '#ef4444' }}>{error}</span>}
        </div>
      )}

      {links.length === 0 ? (
        <div className="rounded-2xl p-8 border text-center" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          <p className="text-sm" style={{ color: 'var(--text-dim)' }}>
            No account links. They're captured automatically from gateway traffic, or add one manually.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--ink-lighter)' }}>
          <table className="w-full">
            <thead>
              <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
                <th className={thCls} style={thStyle}>Connected Account</th>
                <th className={thCls} style={thStyle}>Agent</th>
                <th className={thCls} style={thStyle}>App</th>
                <th className={thCls} style={thStyle}>Source</th>
                <th className={thCls} style={thStyle}>Last Seen</th>
                <th className="text-right text-xs font-medium px-4 py-3" style={thStyle}></th>
              </tr>
            </thead>
            <tbody>
              {links.map(l => (
                <tr key={l.connected_account_id} className="border-t" style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}>
                  <td className="px-4 py-3 text-xs font-mono" style={{ color: 'var(--text)' }}>{l.connected_account_id}</td>
                  <td className="px-4 py-3 text-sm" style={{ color: 'var(--text)' }}>{l.agent_slug || '—'}</td>
                  <td className="px-4 py-3 text-sm" style={{ color: 'var(--text-dim)' }}>{l.app_name || '—'}</td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-dim)' }}>{l.source}</td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-dim)' }}>{fmtTime(l.last_seen_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleDeleteLink(l.connected_account_id)}
                      className="p-1.5 rounded-lg transition-all hover:scale-110"
                      style={{ color: '#ef4444' }}
                      title="Delete link"
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
