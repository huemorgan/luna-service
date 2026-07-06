import { useCallback, useEffect, useState } from 'react';
import { Clock, RefreshCw, Loader2, Database, Zap, ListChecks, CalendarClock } from 'lucide-react';

interface ServiceStats {
  version: string;
  uptime_s: number;
  last_tick_at: string | null;
  db: { ok: boolean; latency_ms?: number; error?: string };
  totals: {
    accounts: number;
    triggers_enabled: number;
    triggers_paused: number;
    fires_1h: number;
    fires_24h: number;
    failed_24h: number;
    dead_24h: number;
  };
  upcoming: { due_at: string; account_id: string; trigger_name: string }[];
  accounts: AccountStats[];
}

interface AccountStats {
  account_id: string;
  enabled: boolean;
  triggers: number;
  next_run_at: string | null;
  last_fire_at: string | null;
  last_fire_status: string | null;
  fires_24h: number;
  sent_today: number;
  daily_cap: number;
}

interface StatsEnvelope {
  configured: boolean;
  reachable?: boolean;
  authorized?: boolean;
  stats?: ServiceStats;
}

interface TriggerRow {
  id: string;
  account_id: string;
  name: string;
  expr_raw: string;
  expr_cron: string;
  timezone: string;
  action_type: string;
  target: string;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
}

interface InstanceRow {
  agent_id: string;
  name: string;
  slug: string;
  status: string;
  plugin_installed: boolean;
  account: {
    enabled: boolean | null;
    triggers: number | null;
    next_run_at: string | null;
    last_fire_at: string | null;
    last_fire_status: string | null;
    fires_24h: number | null;
    sent_today: number | null;
    daily_cap: number | null;
  } | null;
}

type Pill = { label: string; color: string };

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

function fmtWhen(iso: string | null): string {
  if (!iso) return '—';
  const t = new Date(iso);
  const mins = Math.round((t.getTime() - Date.now()) / 60000);
  const clock = t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  if (mins <= 0) return `due (${clock})`;
  if (mins < 60) return `in ${mins} m (${clock})`;
  if (mins < 1440) return `in ${Math.round(mins / 60)} h (${clock})`;
  return t.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// Ticker silence beyond a few intervals means the clock is stuck even if HTTP answers.
function tickerLag(s: ServiceStats | undefined): { label: string; color: string } {
  if (!s?.last_tick_at) return { label: '—', color: 'var(--text-dim)' };
  const secs = Math.floor((Date.now() - new Date(s.last_tick_at).getTime()) / 1000);
  if (secs < 60) return { label: `${secs}s ago`, color: '#22c55e' };
  return { label: `${Math.floor(secs / 60)}m ago`, color: '#eab308' };
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

export default function SchedulerPage() {
  const [env, setEnv] = useState<StatsEnvelope | null>(null);
  const [triggers, setTriggers] = useState<TriggerRow[]>([]);
  const [instances, setInstances] = useState<InstanceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchFailed, setFetchFailed] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [sRes, tRes, iRes] = await Promise.all([
        fetch('/api/admin/scheduler/stats'),
        fetch('/api/admin/scheduler/triggers'),
        fetch('/api/admin/scheduler/instances'),
      ]);
      if (sRes.ok) { setEnv(await sRes.json()); setFetchFailed(false); }
      else setFetchFailed(true);
      if (tRes.ok) {
        const body = await tRes.json();
        setTriggers(Array.isArray(body.triggers) ? body.triggers : []);
      }
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
          <p className="text-sm mb-2" style={{ color: 'var(--text)' }}>Scheduler service is not configured.</p>
          <p className="text-xs" style={dimText}>
            Set <span className="font-mono">CLOUD_SCHEDULER_SERVICE_URL</span> and{' '}
            <span className="font-mono">CLOUD_SCHEDULER_SERVICE_ADMIN_KEY</span> on the control plane
            (copy the key from the luna-scheduler Render service).
          </p>
        </div>
      </div>
    );
  }

  const pill = fetchFailed ? { label: 'Offline', color: '#ef4444' } : pillFor(env);
  const s = env?.stats;
  const unauthorized = env?.reachable && env?.authorized === false;
  const lag = tickerLag(s);
  const visible = instances.filter(a => a.account || a.plugin_installed);

  return (
    <div className="max-w-5xl">
      <Header onRefresh={fetchAll} />

      {/* ── Service health strip ── */}
      <div className="rounded-2xl border p-4 mb-4 flex flex-wrap items-center gap-x-6 gap-y-2" style={cardStyle}>
        <span className="text-xs px-2.5 py-1 rounded-full font-semibold" style={{ color: pill.color, background: `${pill.color}22` }}>
          ● Service {pill.label}
        </span>
        <span className="text-xs" style={dimText}>uptime {s ? fmtUptime(s.uptime_s) : '—'}</span>
        <span className="text-xs" style={dimText}>
          last tick <span style={{ color: lag.color }}>{lag.label}</span>
        </span>
        <span className="text-xs" style={dimText}>v{s?.version || '—'}</span>
      </div>

      {unauthorized && (
        <div className="rounded-xl border px-4 py-3 mb-4 text-sm" style={{ borderColor: '#ef4444', color: '#ef4444', background: '#ef444411' }}>
          Service rejected the admin key — check <span className="font-mono">CLOUD_SCHEDULER_SERVICE_ADMIN_KEY</span>.
        </div>
      )}

      {/* ── Metric cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-4">
        <MetricCard title="Triggers" icon={ListChecks}>
          <StatRow label="Enabled" value={s?.totals.triggers_enabled ?? '—'} />
          <StatRow label="Paused" value={s?.totals.triggers_paused ?? '—'} />
          <StatRow label="Accounts" value={s?.totals.accounts ?? '—'} />
        </MetricCard>

        <MetricCard title="Fires" icon={Zap}>
          <StatRow label="Last hour" value={s?.totals.fires_1h ?? '—'} />
          <StatRow label="Last 24 h" value={s?.totals.fires_24h ?? '—'} />
          <StatRow label="Failed 24 h" value={
            s ? <span style={{ color: s.totals.failed_24h > 0 ? '#eab308' : 'var(--text)' }}>{s.totals.failed_24h}</span> : '—'
          } />
          <StatRow label="Dead-letter 24 h" value={
            s ? <span style={{ color: s.totals.dead_24h > 0 ? '#ef4444' : 'var(--text)' }}>{s.totals.dead_24h}</span> : '—'
          } />
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

      {/* ── Upcoming fires ── */}
      {s && (s.upcoming || []).length > 0 && (
        <div className="rounded-2xl border p-4 mb-6" style={cardStyle}>
          <div className="flex items-center gap-2 mb-3">
            <CalendarClock size={14} style={{ color: 'var(--moon)' }} />
            <span className="text-xs font-semibold" style={{ color: 'var(--text)' }}>Upcoming fires</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
            {s.upcoming.slice(0, 10).map((u, i) => (
              <div key={i} className="flex justify-between items-baseline py-1 border-b last:border-b-0" style={{ borderColor: 'var(--ink-lighter)' }}>
                <span className="text-xs truncate mr-3" style={{ color: 'var(--text)' }}>
                  <span className="font-mono" style={dimText}>{u.account_id}</span> · {u.trigger_name}
                </span>
                <span className="text-xs whitespace-nowrap" style={dimText}>{fmtWhen(u.due_at)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Triggers (fleet-wide) ── */}
      <h3 className="text-sm font-semibold mb-2" style={{ color: 'var(--text)' }}>
        Triggers <span className="font-normal" style={dimText}>({triggers.length})</span>
      </h3>
      <p className="text-xs mb-3 max-w-3xl" style={dimText}>
        Every trigger on the service, read-only. Triggers are created inside each
        Luna — by the agent, a playbook, or the Scheduler plugin tab.
      </p>
      <div className="rounded-xl border overflow-hidden mb-6" style={{ borderColor: 'var(--ink-lighter)' }}>
        <table className="w-full">
          <thead>
            <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
              {['Agent', 'Trigger', 'Schedule', 'Action', 'Next run', 'Last run', 'State'].map((h, i) => (
                <th key={i} className="text-left text-xs font-medium px-4 py-3" style={dimText}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {triggers.length === 0 ? (
              <tr style={{ background: 'var(--surface)' }}>
                <td colSpan={7} className="px-4 py-6 text-center text-sm" style={dimText}>
                  No triggers yet — install the Scheduler plugin inside a Luna and ask it to schedule something.
                </td>
              </tr>
            ) : triggers.map(t => (
              <tr key={t.id} className="border-t" style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}>
                <td className="px-4 py-3 text-xs font-mono" style={dimText}>{t.account_id}</td>
                <td className="px-4 py-3 text-sm" style={{ color: 'var(--text)' }}>{t.name}</td>
                <td className="px-4 py-3 text-xs" style={dimText} title={t.timezone}>
                  {t.expr_raw} <span className="font-mono">({t.expr_cron})</span>
                </td>
                <td className="px-4 py-3 text-xs" style={dimText} title={t.target}>
                  {t.action_type === 'playbook' ? `playbook: ${t.target}` : `prompt: ${(t.target || '').slice(0, 40)}${(t.target || '').length > 40 ? '…' : ''}`}
                </td>
                <td className="px-4 py-3 text-xs" style={dimText}>{t.enabled ? fmtWhen(t.next_run_at) : '—'}</td>
                <td className="px-4 py-3 text-xs" style={dimText}>{fmtAgo(t.last_run_at)}</td>
                <td className="px-4 py-3">
                  <span className="text-xs px-2 py-0.5 rounded-full font-medium"
                    style={t.enabled
                      ? { color: '#22c55e', background: '#22c55e22' }
                      : { color: '#eab308', background: '#eab30822' }}>
                    {t.enabled ? 'enabled' : 'paused'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Instances (per-Luna scheduler) ── */}
      <h3 className="text-sm font-semibold mb-2" style={{ color: 'var(--text)' }}>
        Instances <span className="font-normal" style={dimText}>({visible.length})</span>
      </h3>
      <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--ink-lighter)' }}>
        <table className="w-full">
          <thead>
            <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
              {['Agent', 'Machine', 'Triggers', 'Next fire', 'Last fire', 'Fires 24h'].map((h, i) => (
                <th key={i} className="text-left text-xs font-medium px-4 py-3" style={dimText}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr style={{ background: 'var(--surface)' }}>
                <td colSpan={6} className="px-4 py-6 text-center text-sm" style={dimText}>
                  No Luna uses the scheduler yet — install the Scheduler plugin inside a Luna.
                </td>
              </tr>
            ) : visible.map(a => (
              <tr key={a.agent_id} className="border-t" style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}>
                <td className="px-4 py-3 text-sm" style={{ color: 'var(--text)' }}>
                  {a.name} <span className="text-xs font-mono" style={dimText}>{a.slug}</span>
                </td>
                <td className="px-4 py-3 text-xs" style={dimText}>{a.status}</td>
                <td className="px-4 py-3 text-xs" style={dimText}>{a.account?.triggers ?? (a.plugin_installed ? 'plugin installed' : '—')}</td>
                <td className="px-4 py-3 text-xs" style={dimText}>{fmtWhen(a.account?.next_run_at ?? null)}</td>
                <td className="px-4 py-3 text-xs" style={dimText}>
                  {a.account?.last_fire_at ? (
                    <>
                      {fmtAgo(a.account.last_fire_at)}{' '}
                      {a.account.last_fire_status && (
                        <span style={{ color: a.account.last_fire_status === 'delivered' ? '#22c55e' : '#ef4444' }}>
                          ({a.account.last_fire_status})
                        </span>
                      )}
                    </>
                  ) : '—'}
                </td>
                <td className="px-4 py-3 text-xs" style={dimText}>{a.account?.fires_24h ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Header({ onRefresh }: { onRefresh: () => void }) {
  return (
    <div className="flex items-center justify-between mb-6">
      <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
        <Clock size={20} style={{ color: 'var(--moon)' }} />
        Scheduler
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
