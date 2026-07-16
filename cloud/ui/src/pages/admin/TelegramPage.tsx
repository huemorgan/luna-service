import { useCallback, useEffect, useState } from 'react';
import { Activity, Bot, Database, Loader2, RefreshCw, Send, Webhook } from 'lucide-react';

interface BotIdentity {
  id: number | null;
  username: string | null;
  first_name: string | null;
}

interface WebhookState {
  configured?: boolean | null;
  pending_updates?: number | null;
  last_error?: string | null;
  last_error_at?: string | null;
}

interface AccountStats {
  account_id: string;
  status?: string | null;
  enabled?: boolean | null;
  bot?: BotIdentity;
  bot_id?: number | null;
  bot_username?: string | null;
  webhook?: WebhookState;
  webhook_configured?: boolean | null;
  pending_updates?: number | null;
  privacy_mode?: boolean | null;
  group_visibility?: string | null;
  last_activity_at?: string | null;
  messages_24h_in?: number | null;
  messages_24h_out?: number | null;
  error?: string | null;
}

interface GatewayStats {
  version?: string;
  uptime_s?: number;
  status?: string;
  db?: { ok: boolean; latency_ms?: number; error?: string };
  webhook?: WebhookState;
  totals?: {
    accounts?: number;
    active_chats?: number;
    messages_24h_in?: number;
    messages_24h_out?: number;
    forward_failures_24h?: number;
  };
  hourly?: { hour: string; in: number; out: number }[];
  accounts?: AccountStats[];
}

interface StatsEnvelope {
  configured: boolean;
  reachable?: boolean;
  authorized?: boolean;
  stats?: GatewayStats;
}

interface InstanceRow {
  agent_id: string;
  name: string;
  slug: string;
  status: string;
  plugin_installed: boolean;
  account: Omit<AccountStats, 'account_id'> | null;
}

const cardStyle = { background: 'var(--surface)', borderColor: 'var(--ink-lighter)' } as const;
const dimText = { color: 'var(--text-dim)' } as const;

function fmtUptime(seconds?: number): string {
  if (seconds === undefined) return '—';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function fmtAgo(iso?: string | null): string {
  if (!iso) return '—';
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  return `${Math.floor(minutes / 1440)}d ago`;
}

function statusFor(env: StatsEnvelope | null, failed: boolean) {
  if (failed || !env?.reachable) return { label: 'Offline', color: '#ef4444' };
  if (env.authorized === false || env.stats?.db?.ok === false) {
    return { label: 'Degraded', color: '#eab308' };
  }
  return { label: 'Online', color: '#22c55e' };
}

function MetricCard({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: typeof Activity;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border p-4" style={cardStyle} aria-label={title}>
      <div className="mb-3 flex items-center gap-2">
        <Icon size={15} style={{ color: 'var(--moon)' }} />
        <h3 className="text-xs font-semibold" style={{ color: 'var(--text)' }}>{title}</h3>
      </div>
      {children}
    </section>
  );
}

function StatRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5">
      <span className="text-xs" style={dimText}>{label}</span>
      <span className="text-sm font-medium text-right" style={{ color: 'var(--text)' }}>{value}</span>
    </div>
  );
}

export default function TelegramPage() {
  const [env, setEnv] = useState<StatsEnvelope | null>(null);
  const [instances, setInstances] = useState<InstanceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchFailed, setFetchFailed] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [statsResponse, instancesResponse] = await Promise.all([
        fetch('/api/admin/telegram/stats'),
        fetch('/api/admin/telegram/instances'),
      ]);
      if (statsResponse.ok) {
        setEnv(await statsResponse.json());
        setFetchFailed(false);
      } else {
        setFetchFailed(true);
      }
      if (instancesResponse.ok) setInstances(await instancesResponse.json());
    } catch {
      setFetchFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(fetchAll, 0);
    const interval = window.setInterval(fetchAll, 15000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(interval);
    };
  }, [fetchAll]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20" aria-label="Loading Telegram monitoring">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  if (env && !env.configured) {
    return (
      <div className="max-w-5xl">
        <Header onRefresh={fetchAll} />
        <div className="rounded-2xl border p-8 text-center" style={cardStyle}>
          <p className="mb-2 text-sm" style={{ color: 'var(--text)' }}>Telegram gateway is not configured.</p>
          <p className="text-xs" style={dimText}>
            Configure the external multi-account gateway on the control plane to enable monitoring.
          </p>
        </div>
      </div>
    );
  }

  const stats = env?.stats;
  const gatewayStatus = statusFor(env, fetchFailed);
  const unauthorized = env?.reachable && env.authorized === false;
  const webhook = stats?.webhook;
  const hourly = stats?.hourly || [];
  const maxHourly = Math.max(1, ...hourly.map(bucket => Math.max(bucket.in, bucket.out)));
  const visible = instances.filter(instance => instance.plugin_installed || instance.account);

  return (
    <div className="max-w-5xl">
      <Header onRefresh={fetchAll} />

      {unauthorized && (
        <div
          className="mb-4 rounded-xl border px-4 py-3 text-sm"
          style={{ borderColor: '#eab308', color: '#eab308', background: '#eab30811' }}
          role="status"
        >
          Gateway authorization failed. Check the server-side gateway configuration.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 mb-4 sm:grid-cols-2 lg:grid-cols-3">
        <MetricCard title="Gateway health" icon={Activity}>
          <StatRow
            label="Status"
            value={<span style={{ color: gatewayStatus.color }}>{gatewayStatus.label}</span>}
          />
          <StatRow label="Uptime" value={fmtUptime(stats?.uptime_s)} />
          <StatRow label="Version" value={stats?.version || '—'} />
        </MetricCard>

        <MetricCard title="Webhook" icon={Webhook}>
          <StatRow
            label="Configured"
            value={webhook?.configured === undefined ? '—' : webhook.configured ? 'yes' : 'no'}
          />
          <StatRow label="Pending updates" value={webhook?.pending_updates ?? '—'} />
          <StatRow label="Last error" value={webhook?.last_error || 'none'} />
        </MetricCard>

        <MetricCard title="Database" icon={Database}>
          <StatRow
            label="Status"
            value={
              stats?.db
                ? <span style={{ color: stats.db.ok ? '#22c55e' : '#ef4444' }}>{stats.db.ok ? 'ok' : 'down'}</span>
                : '—'
            }
          />
          <StatRow label="Latency" value={stats?.db?.latency_ms === undefined ? '—' : `${stats.db.latency_ms} ms`} />
        </MetricCard>

        <MetricCard title="Fleet" icon={Bot}>
          <StatRow label="Bots" value={stats?.totals?.accounts ?? stats?.accounts?.length ?? '—'} />
          <StatRow label="Active chats" value={stats?.totals?.active_chats ?? '—'} />
          <StatRow label="Forward failures 24h" value={stats?.totals?.forward_failures_24h ?? '—'} />
        </MetricCard>

        <MetricCard title="Messages (24h)" icon={Send}>
          <StatRow label="Inbound" value={stats?.totals?.messages_24h_in ?? '—'} />
          <StatRow label="Outbound" value={stats?.totals?.messages_24h_out ?? '—'} />
        </MetricCard>
      </div>

      <section className="mb-6 rounded-2xl border p-4" style={cardStyle} aria-label="Messages last 24 hours">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="text-xs font-semibold" style={{ color: 'var(--text)' }}>Messages — last 24h</h3>
          <span className="text-xs" style={dimText}>
            <span style={{ color: 'var(--moon)' }}>■</span> inbound&nbsp;&nbsp;
            <span style={{ color: '#22c55e' }}>■</span> outbound
          </span>
        </div>
        {hourly.length === 0 ? (
          <p className="py-8 text-center text-xs" style={dimText}>No hourly message data.</p>
        ) : (
          <div className="flex h-28 items-end gap-1">
            {hourly.map((bucket, index) => (
              <div
                key={`${bucket.hour}-${index}`}
                className="flex flex-1 items-end gap-px"
                title={`${new Date(bucket.hour).toLocaleTimeString([], { hour: '2-digit' })}: ${bucket.in} in / ${bucket.out} out`}
              >
                <div className="flex-1 rounded-t" style={{ height: `${(bucket.in / maxHourly) * 100}%`, minHeight: bucket.in ? 2 : 0, background: 'var(--moon)' }} />
                <div className="flex-1 rounded-t" style={{ height: `${(bucket.out / maxHourly) * 100}%`, minHeight: bucket.out ? 2 : 0, background: '#22c55e' }} />
              </div>
            ))}
          </div>
        )}
      </section>

      <h3 className="mb-2 text-sm font-semibold" style={{ color: 'var(--text)' }}>
        Lunas <span className="font-normal" style={dimText}>({visible.length})</span>
      </h3>
      <p className="mb-3 max-w-3xl text-xs" style={dimText}>
        Read-only fleet state. Each Luna connects its own BotFather bot from the Telegram plugin settings.
      </p>
      <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--ink-lighter)' }}>
        <table className="w-full min-w-[820px]">
          <thead>
            <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
              {['Luna', 'Plugin', 'Bot', 'Webhook', 'Group visibility', '24h messages', 'Last activity', 'Error'].map(label => (
                <th key={label} className="px-4 py-3 text-left text-xs font-medium" style={dimText}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr style={{ background: 'var(--surface)' }}>
                <td colSpan={8} className="px-4 py-7 text-center text-sm" style={dimText}>
                  No Luna uses Telegram yet. Install the Telegram plugin inside a Luna to connect a bot.
                </td>
              </tr>
            ) : visible.map(instance => <InstanceRowView key={instance.agent_id} row={instance} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function InstanceRowView({ row }: { row: InstanceRow }) {
  const account = row.account;
  const bot = account?.bot;
  const webhook = account?.webhook;
  const username = bot?.username || account?.bot_username;
  const webhookConfigured = webhook?.configured ?? account?.webhook_configured;
  const visibility = account?.group_visibility
    || (account?.privacy_mode === true ? 'mentions only' : account?.privacy_mode === false ? 'all group messages' : '—');

  return (
    <tr className="border-t" style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}>
      <td className="px-4 py-3 text-sm" style={{ color: 'var(--text)' }}>
        {row.name} <span className="block font-mono text-xs" style={dimText}>{row.slug}</span>
      </td>
      <td className="px-4 py-3 text-xs" style={dimText}>{row.plugin_installed ? 'installed' : '—'}</td>
      <td className="px-4 py-3 text-xs" style={dimText}>{username ? `@${username}` : '—'}</td>
      <td className="px-4 py-3 text-xs" style={{ color: webhookConfigured ? '#22c55e' : 'var(--text-dim)' }}>
        {webhookConfigured === undefined || webhookConfigured === null ? '—' : webhookConfigured ? 'configured' : 'not configured'}
      </td>
      <td className="px-4 py-3 text-xs" style={dimText}>{visibility}</td>
      <td className="px-4 py-3 text-xs whitespace-nowrap" style={dimText}>
        {account ? `${account.messages_24h_in ?? 0} in / ${account.messages_24h_out ?? 0} out` : '—'}
      </td>
      <td className="px-4 py-3 text-xs whitespace-nowrap" style={dimText}>{fmtAgo(account?.last_activity_at)}</td>
      <td className="px-4 py-3 text-xs max-w-[180px] truncate" style={{ color: account?.error ? '#eab308' : 'var(--text-dim)' }}>
        {account?.error || webhook?.last_error || '—'}
      </td>
    </tr>
  );
}

function Header({ onRefresh }: { onRefresh: () => void }) {
  return (
    <div className="mb-6 flex items-center justify-between">
      <h2 className="flex items-center gap-2 text-xl font-bold" style={{ color: 'var(--text)' }}>
        <Send size={20} style={{ color: 'var(--moon)' }} />
        Telegram
      </h2>
      <button
        type="button"
        onClick={onRefresh}
        aria-label="Refresh Telegram monitoring"
        className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition-all hover:scale-105"
        style={{ border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}
      >
        <RefreshCw size={14} />
      </button>
    </div>
  );
}
