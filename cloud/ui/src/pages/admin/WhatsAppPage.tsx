import { useCallback, useEffect, useState } from 'react';
import { MessageCircle, RefreshCw, Loader2, Database, Users, MessagesSquare, HardDrive } from 'lucide-react';

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
  const maxHourly = Math.max(1, ...(s?.hourly || []).map(h => Math.max(h.in, h.out)));
  // Read-only: Lunas with a live account or the plugin. Connecting happens
  // inside each Luna (plugin-whatsapp >= 0.7.0), not here.
  const hasLiveAccount = (a: InstanceRow) => !!a.account && a.account.status !== 'disabled';
  const visible = instances.filter(a => hasLiveAccount(a) || a.plugin_installed);

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
        Lunas on WhatsApp — each with its own number and daily send cap. Connecting
        happens inside each Luna: install the WhatsApp plugin and scan the QR in its
        settings tab.
      </p>
      <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--ink-lighter)' }}>
        <table className="w-full">
          <thead>
            <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
              {['Agent', 'Machine', 'Status', '24h msgs', 'Sent today'].map((h, i) => (
                <th key={i} className="text-left text-xs font-medium px-4 py-3" style={dimText}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr style={{ background: 'var(--surface)' }}>
                <td colSpan={5} className="px-4 py-6 text-center text-sm" style={dimText}>
                  No Luna is on WhatsApp yet — install the WhatsApp plugin inside a Luna to connect it.
                </td>
              </tr>
            ) : visible.map(a => (
              <InstanceTr key={a.agent_id} row={a} />
            ))}
          </tbody>
        </table>
      </div>

    </div>
  );
}

// Lifecycle: plugin installed → setup phone (scan QR) → linked (own number).
function lifecyclePill(a: InstanceRow, acct: InstanceAccount | null): { label: string; color: string } {
  if (acct?.connected) return { label: acct.self_jid ? acct.self_jid.split('@')[0] : 'linked', color: '#22c55e' };
  if (acct?.has_qr) return { label: 'setup phone', color: '#eab308' };
  if (acct?.status) return { label: acct.status, color: '#eab308' };
  if (a.plugin_installed) return { label: 'plugin installed', color: 'var(--moon)' };
  return { label: '—', color: 'var(--text-dim)' };
}

function InstanceTr({ row: a }: { row: InstanceRow }) {
  // A disabled account is a disconnected one — offer Connect again.
  const acct = a.account && a.account.status !== 'disabled' ? a.account : null;
  const pill = lifecyclePill(a, acct);
  const sent = acct?.sent_today ?? 0;
  const cap = acct?.daily_cap ?? 0;
  const capPct = cap > 0 ? Math.min(100, Math.round((sent / cap) * 100)) : 0;
  const capColor = capPct >= 100 ? '#ef4444' : capPct >= 80 ? '#eab308' : '#22c55e';
  return (
    <tr className="border-t" style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}>
      <td className="px-4 py-3 text-sm" style={{ color: 'var(--text)' }}>
        {a.name} <span className="text-xs font-mono" style={dimText}>{a.slug}</span>
      </td>
      <td className="px-4 py-3 text-xs" style={dimText}>{a.status}</td>
      <td className="px-4 py-3 text-sm">
        <span className="text-xs px-2 py-0.5 rounded-full font-medium"
          style={{ color: pill.color, background: `${pill.color}22` }}>
          {pill.label}
        </span>
      </td>
      <td className="px-4 py-3 text-xs" style={dimText}>
        {acct ? `${acct.messages_24h_in ?? 0} in / ${acct.messages_24h_out ?? 0} out` : '—'}
      </td>
      <td className="px-4 py-3 text-xs" style={dimText}>
        {acct ? (
          <div className="min-w-[90px]" title="daily cap guards against ban risk">
            {sent} / {cap || '∞'}
            <div className="mt-1 h-1 rounded-full overflow-hidden" style={{ background: 'var(--ink)' }}>
              <div className="h-full rounded-full" style={{ width: `${capPct}%`, background: capColor }} />
            </div>
          </div>
        ) : '—'}
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
