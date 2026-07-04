import { useCallback, useEffect, useState } from 'react';
import { MessageCircle, RefreshCw, Loader2, Database, Users, MessagesSquare, HardDrive, Send } from 'lucide-react';

interface WindowStats {
  messages_in: number;
  messages_out: number;
  active_chats: number;
  active_users: number;
}

interface GatewayStats {
  status: string;
  connected: boolean;
  self_jid: string | null;
  has_qr: boolean;
  last_activity_at: string | null;
  uptime_s: number;
  version: string;
  rss_mb: number;
  sent_today: number;
  send_daily_cap: number;
  db: { ok: boolean; latency_ms?: number; error?: string };
  totals: { messages: number; chats: number; users: number };
  last_hour: WindowStats;
  last_24h: WindowStats;
  media_24h: Record<string, number>;
  hourly: { hour: string; in: number; out: number }[];
  last_message_at: string | null;
}

interface StatsEnvelope {
  configured: boolean;
  reachable?: boolean;
  authorized?: boolean;
  stats?: GatewayStats;
}

interface InstanceAccount {
  status: string | null;
  connected: boolean | null;
  self_jid: string | null;
  has_qr: boolean | null;
  messages_24h_in: number | null;
  messages_24h_out: number | null;
  sent_today: number | null;
  daily_cap: number | null;
}

interface InstanceRow {
  agent_id: string;
  name: string;
  slug: string;
  status: string;
  plugin_installed: boolean;
  account: InstanceAccount | null;
}

type Pill = { label: string; color: string };

// Gateway-process health only — per-number link state lives on each Luna's row.
function pillFor(env: StatsEnvelope | null): Pill {
  if (!env || !env.reachable || env.authorized === false) return { label: 'Offline', color: '#ef4444' };
  return { label: 'Online', color: '#22c55e' };
}

function fmtUptime(s: number): string {
  if (!s && s !== 0) return '—';
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function fmtAgo(iso: string | null): string {
  if (!iso) return '—';
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} m ago`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.floor(h / 24)} d ago`;
}

const cardStyle = { background: 'var(--surface)', borderColor: 'var(--ink-lighter)' } as const;
const dimText = { color: 'var(--text-dim)' } as const;

function MetricCard({ title, icon: Icon, children }: { title: string; icon: any; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border p-4" style={cardStyle}>
      <div className="flex items-center gap-2 mb-3">
        <Icon size={14} style={{ color: 'var(--moon)' }} />
        <span className="text-xs font-semibold" style={{ color: 'var(--text)' }}>{title}</span>
      </div>
      {children}
    </div>
  );
}

function StatRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-baseline py-0.5">
      <span className="text-xs" style={dimText}>{label}</span>
      <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{value}</span>
    </div>
  );
}

export default function WhatsAppPage() {
  const [env, setEnv] = useState<StatsEnvelope | null>(null);
  const [instances, setInstances] = useState<InstanceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchFailed, setFetchFailed] = useState(false);
  const [busySlug, setBusySlug] = useState<string | null>(null);
  const [qrAgent, setQrAgent] = useState<InstanceRow | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const [sRes, iRes] = await Promise.all([
        fetch('/api/admin/whatsapp/stats'),
        fetch('/api/admin/whatsapp/instances'),
      ]);
      if (sRes.ok) { setEnv(await sRes.json()); setFetchFailed(false); }
      else setFetchFailed(true);
      if (iRes.ok) setInstances(await iRes.json());
    } catch {
      setFetchFailed(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 15000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const handleConnect = async (a: InstanceRow) => {
    setActionError(null);
    setBusySlug(a.slug);
    try {
      const res = await fetch(`/api/admin/whatsapp/instances/${a.agent_id}/connect`, { method: 'POST' });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setActionError(body?.detail || `Connect failed (${res.status})`);
      } else {
        await fetchAll();
        setQrAgent(a);
      }
    } catch {
      setActionError('Connect failed (network)');
    }
    setBusySlug(null);
  };

  const handleDisconnect = async (a: InstanceRow) => {
    if (!window.confirm(`Disconnect WhatsApp for ${a.slug}? Its number unlinks and inbound stops.`)) return;
    setActionError(null);
    setBusySlug(a.slug);
    try {
      const res = await fetch(`/api/admin/whatsapp/instances/${a.agent_id}/connect`, { method: 'DELETE' });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setActionError(body?.detail || `Disconnect failed (${res.status})`);
      } else {
        await fetchAll();
      }
    } catch {
      setActionError('Disconnect failed (network)');
    }
    setBusySlug(null);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  if (env && !env.configured) {
    return (
      <div className="max-w-5xl">
        <Header onRefresh={fetchAll} />
        <div className="rounded-2xl p-8 border text-center" style={cardStyle}>
          <p className="text-sm mb-2" style={{ color: 'var(--text)' }}>WhatsApp gateway is not configured.</p>
          <p className="text-xs" style={dimText}>
            Set <span className="font-mono">CLOUD_WHATSAPP_GATEWAY_URL</span> and{' '}
            <span className="font-mono">CLOUD_WHATSAPP_GATEWAY_ADMIN_KEY</span> on the control plane
            (copy the key from the luna-wa-gateway Render service).
          </p>
        </div>
      </div>
    );
  }

  const pill = fetchFailed ? { label: 'Offline', color: '#ef4444' } : pillFor(env);
  const s = env?.stats;
  const unauthorized = env?.reachable && env?.authorized === false;
  const budgetPct = s && s.send_daily_cap > 0 ? Math.min(100, Math.round((s.sent_today / s.send_daily_cap) * 100)) : 0;
  const budgetColor = budgetPct >= 100 ? '#ef4444' : budgetPct >= 80 ? '#eab308' : '#22c55e';
  const maxHourly = Math.max(1, ...(s?.hourly || []).map(h => Math.max(h.in, h.out)));

  return (
    <div className="max-w-5xl">
      <Header onRefresh={fetchAll} />

      {/* ── Gateway health strip (numbers live per-Luna below) ── */}
      <div className="rounded-2xl border p-4 mb-4 flex flex-wrap items-center gap-x-6 gap-y-2" style={cardStyle}>
        <span className="text-xs px-2.5 py-1 rounded-full font-semibold" style={{ color: pill.color, background: `${pill.color}22` }}>
          ● Gateway {pill.label}
        </span>
        <span className="text-xs" style={dimText}>uptime {s ? fmtUptime(s.uptime_s) : '—'}</span>
        <span className="text-xs" style={dimText}>last activity {fmtAgo(s?.last_activity_at ?? null)}</span>
        <span className="text-xs" style={dimText}>{s ? `${s.rss_mb} MB` : '—'}</span>
        <span className="text-xs" style={dimText}>v{s?.version || '—'}</span>
      </div>

      {unauthorized && (
        <div className="rounded-xl border px-4 py-3 mb-4 text-sm" style={{ borderColor: '#ef4444', color: '#ef4444', background: '#ef444411' }}>
          Gateway rejected the admin key — check <span className="font-mono">CLOUD_WHATSAPP_GATEWAY_ADMIN_KEY</span>.
        </div>
      )}

      {/* ── Metric cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-4">
        <MetricCard title="Messages" icon={MessagesSquare}>
          <StatRow label="Last hour" value={s ? `${s.last_hour.messages_in} in / ${s.last_hour.messages_out} out` : '—'} />
          <StatRow label="Last 24 h" value={s ? `${s.last_24h.messages_in} in / ${s.last_24h.messages_out} out` : '—'} />
          <StatRow label="All time" value={s?.totals.messages ?? '—'} />
          <p className="text-xs mt-2" style={dimText}>last message {fmtAgo(s?.last_message_at ?? null)}</p>
        </MetricCard>

        <MetricCard title="Users & Chats" icon={Users}>
          <StatRow label="Users 1 h / 24 h" value={s ? `${s.last_hour.active_users} / ${s.last_24h.active_users}` : '—'} />
          <StatRow label="Chats 1 h / 24 h" value={s ? `${s.last_hour.active_chats} / ${s.last_24h.active_chats}` : '—'} />
          <StatRow label="Total users" value={s?.totals.users ?? '—'} />
          <StatRow label="Total chats" value={s?.totals.chats ?? '—'} />
        </MetricCard>

        <MetricCard title="Send budget" icon={Send}>
          <StatRow label="Sent today" value={s ? `${s.sent_today} / ${s.send_daily_cap}` : '—'} />
          <div className="mt-2 h-2 rounded-full overflow-hidden" style={{ background: 'var(--ink)' }}>
            <div className="h-full rounded-full transition-all" style={{ width: `${budgetPct}%`, background: budgetColor }} />
          </div>
          <p className="text-xs mt-2" style={dimText}>daily cap guards against ban risk</p>
        </MetricCard>

        <MetricCard title="Media (24 h)" icon={HardDrive}>
          {s && Object.keys(s.media_24h || {}).length > 0 ? (
            Object.entries(s.media_24h).map(([kind, n]) => <StatRow key={kind} label={kind} value={n} />)
          ) : (
            <p className="text-xs" style={dimText}>no media in the last 24 h</p>
          )}
        </MetricCard>

        <MetricCard title="Database" icon={Database}>
          {s?.db?.ok ? (
            <>
              <StatRow label="Status" value={<span style={{ color: '#22c55e' }}>ok</span>} />
              <StatRow label="Latency" value={`${s.db.latency_ms ?? '—'} ms`} />
            </>
          ) : s ? (
            <p className="text-sm font-medium" style={{ color: '#ef4444' }}>server up, DB down</p>
          ) : (
            <p className="text-xs" style={dimText}>—</p>
          )}
        </MetricCard>
      </div>

      {/* ── 24h chart ── */}
      {s && (s.hourly || []).length > 0 && (
        <div className="rounded-2xl border p-4 mb-6" style={cardStyle}>
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold" style={{ color: 'var(--text)' }}>Messages — last 24 h</span>
            <span className="text-xs" style={dimText}>
              <span style={{ color: 'var(--moon)' }}>■</span> in&nbsp;&nbsp;
              <span style={{ color: '#22c55e' }}>■</span> out
            </span>
          </div>
          <div className="flex items-end gap-1 h-24">
            {s.hourly.map((b, i) => (
              <div key={i} className="flex-1 flex items-end gap-px" title={`${new Date(b.hour).getHours()}:00 — ${b.in} in / ${b.out} out`}>
                <div className="flex-1 rounded-t" style={{ height: `${(b.in / maxHourly) * 100}%`, background: 'var(--moon)', minHeight: b.in > 0 ? 2 : 0 }} />
                <div className="flex-1 rounded-t" style={{ height: `${(b.out / maxHourly) * 100}%`, background: '#22c55e', minHeight: b.out > 0 ? 2 : 0 }} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Instances (per-Luna WhatsApp) ── */}
      <h3 className="text-sm font-semibold mb-2" style={{ color: 'var(--text)' }}>
        Instances <span className="font-normal" style={dimText}>({instances.length})</span>
      </h3>
      <p className="text-xs mb-3 max-w-3xl" style={dimText}>
        Each Luna gets its own WhatsApp number: Connect creates the gateway account and
        wires the plugin (no restart); scan that Luna's QR to link its number.
      </p>
      <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--ink-lighter)' }}>
        <table className="w-full">
          <thead>
            <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
              {['Agent', 'Machine', 'Plugin', 'WhatsApp', '24h msgs', ''].map((h, i) => (
                <th key={i} className="text-left text-xs font-medium px-4 py-3" style={dimText}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {instances.length === 0 ? (
              <tr style={{ background: 'var(--surface)' }}>
                <td colSpan={6} className="px-4 py-6 text-center text-sm" style={dimText}>No agents provisioned.</td>
              </tr>
            ) : instances.map(a => (
              <InstanceTr key={a.agent_id} row={a} busy={busySlug === a.slug}
                onConnect={() => handleConnect(a)} onDisconnect={() => handleDisconnect(a)}
                onShowQr={() => setQrAgent(a)} />
            ))}
          </tbody>
        </table>
      </div>

      {actionError && (
        <p className="text-xs mt-2" style={{ color: '#ef4444' }}>{actionError}</p>
      )}

      {qrAgent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }} onClick={() => setQrAgent(null)}>
          <div className="rounded-2xl border p-4 w-[420px]" style={cardStyle} onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
                Link WhatsApp — <span className="font-mono">{qrAgent.slug}</span>
              </span>
              <button onClick={() => setQrAgent(null)} className="text-sm px-2" style={dimText}>✕</button>
            </div>
            <iframe
              title="whatsapp-qr"
              src={`/api/admin/whatsapp/instances/${qrAgent.agent_id}/qr`}
              className="w-full rounded-lg"
              style={{ height: 420, border: '1px solid var(--ink-lighter)', background: '#fff' }}
            />
            <p className="text-xs mt-2" style={dimText}>
              Scan with the WhatsApp phone for this Luna. The page refreshes itself until linked.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function waPill(acct: InstanceAccount): { label: string; color: string } {
  if (acct.connected) return { label: acct.self_jid ? acct.self_jid.split('@')[0] : 'Online', color: '#22c55e' };
  if (acct.has_qr) return { label: 'needs QR', color: '#eab308' };
  if (acct.status) return { label: acct.status, color: '#eab308' };
  return { label: 'unknown', color: 'var(--text-dim)' };
}

function InstanceTr({ row: a, busy, onConnect, onDisconnect, onShowQr }: {
  row: InstanceRow; busy: boolean;
  onConnect: () => void; onDisconnect: () => void; onShowQr: () => void;
}) {
  // A disabled account is a disconnected one — offer Connect again.
  const acct = a.account && a.account.status !== 'disabled' ? a.account : null;
  return (
    <tr className="border-t" style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}>
      <td className="px-4 py-3 text-sm" style={{ color: 'var(--text)' }}>
        {a.name} <span className="text-xs font-mono" style={dimText}>{a.slug}</span>
      </td>
      <td className="px-4 py-3 text-xs" style={dimText}>{a.status}</td>
      <td className="px-4 py-3 text-sm">
        {a.plugin_installed ? <span style={{ color: '#22c55e' }}>✓</span> : <span style={dimText}>—</span>}
      </td>
      <td className="px-4 py-3 text-sm">
        {acct ? (
          <span className="text-xs px-2 py-0.5 rounded-full font-medium"
            style={{ color: waPill(acct).color, background: `${waPill(acct).color}22` }}>
            {waPill(acct).label}
          </span>
        ) : <span style={dimText}>—</span>}
      </td>
      <td className="px-4 py-3 text-xs" style={dimText}>
        {acct ? `${acct.messages_24h_in ?? 0} in / ${acct.messages_24h_out ?? 0} out` : '—'}
      </td>
      <td className="px-4 py-3 text-right whitespace-nowrap">
        {!acct ? (
          <button onClick={onConnect} disabled={busy}
            className="px-3 py-1.5 rounded-xl text-xs font-semibold transition-all hover:scale-105 disabled:opacity-50"
            style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
            {busy ? 'Connecting…' : 'Connect'}
          </button>
        ) : (
          <>
            {acct.has_qr && (
              <button onClick={onShowQr}
                className="px-3 py-1.5 rounded-xl text-xs font-semibold mr-2 transition-all hover:scale-105"
                style={{ background: '#eab308', color: 'var(--ink)' }}>
                Show QR
              </button>
            )}
            <button onClick={onDisconnect} disabled={busy}
              className="px-2 py-1.5 rounded-xl text-xs transition-all hover:scale-105 disabled:opacity-50"
              style={{ border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}
              title="Disconnect this Luna's WhatsApp account">
              {busy ? '…' : 'Disconnect'}
            </button>
          </>
        )}
      </td>
    </tr>
  );
}

function Header({ onRefresh }: { onRefresh: () => void }) {
  return (
    <div className="flex items-center justify-between mb-6">
      <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
        <MessageCircle size={20} style={{ color: 'var(--moon)' }} />
        WhatsApp
      </h2>
      <button
        onClick={onRefresh}
        className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-all hover:scale-105"
        style={{ border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}
      >
        <RefreshCw size={14} />
      </button>
    </div>
  );
}
