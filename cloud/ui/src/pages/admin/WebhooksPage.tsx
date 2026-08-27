import { useCallback, useEffect, useState } from 'react';
import { Webhook, RefreshCw, Loader2, Copy, Check, Trash2 } from 'lucide-react';

interface HookEndpoint {
  id: string;
  agent_slug: string | null;
  agent_name: string | null;
  name: string;
  plugin: string;
  hook_slug: string;
  public_url: string;
  target_path: string;
  mode: string;
  enabled: boolean;
  created_at: string | null;
  last_delivery_at: string | null;
  delivery_count: number;
  last_status_code: number | null;
}

interface HookDelivery {
  id: string;
  webhook_id: string;
  agent_slug: string | null;
  target_path: string | null;
  status: string;
  attempts: number;
  last_status_code: number | null;
  last_error: string | null;
  created_at: string | null;
  delivered_at: string | null;
  next_attempt_at: string | null;
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

function CopyUrl({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(url).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-mono transition-all hover:opacity-80"
      style={{ border: '1px solid var(--ink-lighter)', color: copied ? '#22c55e' : 'var(--text-dim)' }}
      title={url}
    >
      {copied ? <Check size={11} /> : <Copy size={11} />}
      {copied ? 'Copied' : `…/${url.split('/').pop()}`}
    </button>
  );
}

export default function WebhooksPage() {
  const [endpoints, setEndpoints] = useState<HookEndpoint[]>([]);
  const [deliveries, setDeliveries] = useState<HookDelivery[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    const [eRes, dRes] = await Promise.all([
      fetch('/api/admin/webhooks/endpoints'),
      fetch('/api/admin/webhooks/deliveries?limit=100'),
    ]);
    if (eRes.ok) setEndpoints(await eRes.json());
    if (dRes.ok) setDeliveries(await dRes.json());
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 10000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const handleToggle = async (ep: HookEndpoint) => {
    const res = await fetch(`/api/admin/webhooks/endpoints/${ep.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !ep.enabled }),
    });
    if (res.ok) await fetchAll();
  };

  const handleDelete = async (ep: HookEndpoint) => {
    if (!window.confirm(`Delete hook "${ep.plugin}/${ep.name}" for ${ep.agent_slug}? External senders will get 404.`)) return;
    const res = await fetch(`/api/admin/webhooks/endpoints/${ep.id}`, { method: 'DELETE' });
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
    <div className="max-w-6xl">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <Webhook size={20} style={{ color: 'var(--moon)' }} />
          Webhooks
        </h2>
        <button
          onClick={fetchAll}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-all hover:scale-105"
          style={{ border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}
        >
          <RefreshCw size={14} />
        </button>
      </div>
      <p className="text-xs mb-6 max-w-3xl leading-relaxed" style={{ color: 'var(--text-dim)' }}>
        Inbound webhook URLs minted by plugins running inside hosted Lunas. A call to a
        hook URL wakes the agent's machine and delivers to the owning plugin — directly
        (sync) or through the store-and-forward queue (queue).
      </p>

      {/* ── Endpoints ── */}
      <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text)' }}>
        Registered hooks <span className="font-normal" style={{ color: 'var(--text-dim)' }}>({endpoints.length})</span>
      </h3>
      {endpoints.length === 0 ? (
        <div className="rounded-2xl p-8 border text-center mb-8" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          <p className="text-sm" style={{ color: 'var(--text-dim)' }}>
            No hooks minted yet. Plugins create them through the agent webhook API.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border overflow-x-auto mb-8" style={{ borderColor: 'var(--ink-lighter)' }}>
          <table className="w-full">
            <thead>
              <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
                <th className={thCls} style={thStyle}>Agent</th>
                <th className={thCls} style={thStyle}>Hook</th>
                <th className={thCls} style={thStyle}>Mode</th>
                <th className={thCls} style={thStyle}>URL</th>
                <th className={thCls} style={thStyle}>Deliveries</th>
                <th className={thCls} style={thStyle}>Last Code</th>
                <th className={thCls} style={thStyle}>Last Delivery</th>
                <th className={thCls} style={thStyle}>Enabled</th>
                <th className="text-right text-xs font-medium px-4 py-3" style={thStyle}></th>
              </tr>
            </thead>
            <tbody>
              {endpoints.map(ep => (
                <tr key={ep.id} className="border-t" style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)', opacity: ep.enabled ? 1 : 0.5 }}>
                  <td className="px-4 py-3 text-sm" style={{ color: 'var(--text)' }} title={ep.agent_name || undefined}>
                    {ep.agent_slug || '—'}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text)' }}>
                    <span className="font-mono">{ep.plugin}</span>
                    <span style={{ color: 'var(--text-dim)' }}> / {ep.name}</span>
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-dim)' }}>{ep.mode}</td>
                  <td className="px-4 py-3"><CopyUrl url={ep.public_url} /></td>
                  <td className="px-4 py-3 text-sm" style={{ color: 'var(--text-dim)' }}>{ep.delivery_count}</td>
                  <td className="px-4 py-3 text-sm" style={{ color: 'var(--text-dim)' }}>{ep.last_status_code ?? '—'}</td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-dim)' }}>{fmtTime(ep.last_delivery_at)}</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => handleToggle(ep)}
                      className="w-9 h-5 rounded-full relative transition-colors"
                      style={{ background: ep.enabled ? 'var(--moon)' : 'var(--ink-lighter)' }}
                      title={ep.enabled ? 'Disable' : 'Enable'}
                    >
                      <span
                        className="absolute top-0.5 w-4 h-4 rounded-full transition-all"
                        style={{ background: 'var(--ink)', left: ep.enabled ? 18 : 2 }}
                      />
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleDelete(ep)}
                      className="p-1.5 rounded-lg transition-all hover:scale-110"
                      style={{ color: '#ef4444' }}
                      title="Delete hook"
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

      {/* ── Queue deliveries ── */}
      <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text)' }}>
        Queued deliveries <span className="font-normal" style={{ color: 'var(--text-dim)' }}>({deliveries.length})</span>
      </h3>
      <p className="text-xs mb-3 max-w-3xl leading-relaxed" style={{ color: 'var(--text-dim)' }}>
        Only queue-mode hooks appear here; sync hooks deliver inline and update the
        per-hook stats above. Composio trigger deliveries have their own view on the
        machine pages.
      </p>
      {deliveries.length === 0 ? (
        <div className="rounded-2xl p-8 border text-center" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          <p className="text-sm" style={{ color: 'var(--text-dim)' }}>No queued deliveries yet.</p>
        </div>
      ) : (
        <div className="rounded-xl border overflow-x-auto" style={{ borderColor: 'var(--ink-lighter)' }}>
          <table className="w-full">
            <thead>
              <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
                <th className={thCls} style={thStyle}>Status</th>
                <th className={thCls} style={thStyle}>Agent</th>
                <th className={thCls} style={thStyle}>Target</th>
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
                  <td className="px-4 py-3 text-xs font-mono" style={{ color: 'var(--text-dim)' }}>{d.target_path || '—'}</td>
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
    </div>
  );
}
