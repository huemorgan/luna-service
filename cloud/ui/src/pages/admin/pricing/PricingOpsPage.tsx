// 039/009 — billing operations: counters, invariants, alerts.
import { useCallback, useEffect, useState } from 'react';
import { Activity, Loader2, AlertTriangle, RefreshCw, ShieldCheck } from 'lucide-react';
import { API, apiError } from './api';

interface Counted { count: number; credits: number }
interface OpsSnapshot {
  generated_at: string;
  holds: { open: Counted; needs_reconciliation: Counted };
  rated_charges: Record<string, number>;
  would_block: { window_days: number; by_code: Record<string, number>; total: number };
  unrated_dimensions: string[];
  worker: {
    by_type: Record<string, Record<string, number>>;
    dead: Array<{ job_type: string; count: number }>;
    dead_money_jobs: number;
    oldest_pending_age_seconds: number | null;
  };
  webhooks: { error: number; stale_queued: number };
  hosting: { stuck_pending: number; payment_due: number; active_without_charge: number };
  scheduled_lots: { activation_backlog: number };
  clawback: { drifted: Array<{ payment_ref: string; clawed_credits: number; target_credits: number }>; drifted_count: number };
  stripe_bindings: { test: string[]; live: string[]; no_published_version?: boolean };
  negative_margin_calls_7d: number;
  heartbeats: Array<{ name: string; last_run_at: string; detail: Record<string, unknown> | null }>;
}

interface Alert {
  alert_key: string; severity: string; message: string; status: string;
  value: unknown; threshold: unknown;
  first_seen_at: string | null; last_seen_at: string | null; resolved_at: string | null;
}

interface Invariants {
  trial_balance: { total: number; unbalanced_transactions: Array<{ transaction_id: string; sum: number }>; ok: boolean };
  projection_drift: { drifted: Array<Record<string, unknown>>; drifted_count: number; missing_projection?: number; ok: boolean };
  grant_remainders: { drifted: Array<Record<string, unknown>>; drifted_count: number; ok: boolean };
}

const SEVERITY_COLORS: Record<string, { bg: string; fg: string }> = {
  critical: { bg: 'rgba(255,107,107,0.15)', fg: '#ff6b6b' },
  warning: { bg: 'rgba(255,200,100,0.15)', fg: '#ffc864' },
  info: { bg: 'rgba(122,162,255,0.15)', fg: '#7aa2ff' },
};

function SeverityPill({ severity }: { severity: string }) {
  const c = SEVERITY_COLORS[severity] ?? SEVERITY_COLORS.info;
  return (
    <span className="px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ background: c.bg, color: c.fg }}>{severity}</span>
  );
}

function ago(iso: string | null): string {
  if (!iso) return '—';
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function PricingOpsPage() {
  const [snapshot, setSnapshot] = useState<OpsSnapshot | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [invariants, setInvariants] = useState<Invariants | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [snapRes, alertRes] = await Promise.all([
      fetch(`${API}/ops`), fetch(`${API}/ops/alerts`),
    ]);
    if (snapRes.ok) setSnapshot(await snapRes.json());
    if (alertRes.ok) setAlerts((await alertRes.json()).alerts);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const evaluate = async () => {
    setBusy('evaluate'); setError(null);
    const res = await fetch(`${API}/ops/alerts/evaluate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    if (!res.ok) setError(await apiError(res));
    await load();
    setBusy(null);
  };

  const runInvariants = async () => {
    setBusy('invariants'); setError(null);
    const res = await fetch(`${API}/ops/invariants`);
    if (res.ok) setInvariants(await res.json());
    else setError(await apiError(res));
    setBusy(null);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }
  if (!snapshot) return <p className="text-sm" style={{ color: 'var(--text-dim)' }}>Failed to load ops snapshot.</p>;

  const activeAlerts = alerts.filter(a => a.status === 'active');
  const w = snapshot.worker;
  const deadTotal = w.dead.reduce((n, d) => n + d.count, 0);

  return (
    <div className="max-w-5xl">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <Activity size={20} style={{ color: 'var(--moon)' }} />
          Billing Operations
        </h2>
        <button onClick={() => { setLoading(true); load(); }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors hover:opacity-80"
          style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text-dim)' }}>
          <RefreshCw size={12} /> Refresh
        </button>
      </div>
      <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>
        Live counters from the billing plane. Alerts evaluate automatically every
        5 minutes in the background worker; invariants replay the full ledger on demand.
      </p>

      {error && (
        <div className="rounded-xl px-4 py-3 text-sm mb-4"
          style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>{error}</div>
      )}

      {/* Alerts */}
      <Section title="Alerts" action={
        <button onClick={evaluate} disabled={busy === 'evaluate'}
          className="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:opacity-80"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
          {busy === 'evaluate' ? 'Evaluating…' : 'Evaluate now'}
        </button>
      }>
        {alerts.length === 0 ? (
          <Empty>No alerts have ever fired.</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ color: 'var(--text-dim)' }} className="text-left text-xs">
                <th className="pb-2 font-medium">Alert</th>
                <th className="pb-2 font-medium">Severity</th>
                <th className="pb-2 font-medium">Status</th>
                <th className="pb-2 font-medium">Value</th>
                <th className="pb-2 font-medium">First seen</th>
                <th className="pb-2 font-medium">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map(a => (
                <tr key={a.alert_key} className="border-t" style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)' }}>
                  <td className="py-2 pr-3">
                    <div className="font-medium">{a.alert_key}</div>
                    <div className="text-xs" style={{ color: 'var(--text-dim)' }}>{a.message}</div>
                  </td>
                  <td className="py-2 pr-3"><SeverityPill severity={a.severity} /></td>
                  <td className="py-2 pr-3">
                    <span className="text-xs font-medium" style={{ color: a.status === 'active' ? '#ff6b6b' : '#78dca0' }}>
                      {a.status}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-xs font-mono">{JSON.stringify(a.value)}</td>
                  <td className="py-2 pr-3 text-xs" style={{ color: 'var(--text-dim)' }}>{ago(a.first_seen_at)}</td>
                  <td className="py-2 text-xs" style={{ color: 'var(--text-dim)' }}>{ago(a.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {activeAlerts.length > 0 && (
          <div className="rounded-xl px-4 py-3 text-sm flex items-center gap-2 mt-3"
            style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
            <AlertTriangle size={16} />
            {activeAlerts.length} active alert{activeAlerts.length > 1 ? 's' : ''} need attention.
          </div>
        )}
      </Section>

      {/* Invariants */}
      <Section title="Ledger invariants" action={
        <button onClick={runInvariants} disabled={busy === 'invariants'}
          className="px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors hover:opacity-80"
          style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)' }}>
          {busy === 'invariants' ? 'Replaying ledger…' : 'Run invariants'}
        </button>
      }>
        {!invariants ? (
          <Empty>Full ledger replay — trial balance, projection drift, grant remainders. Run on demand.</Empty>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <InvariantCard name="Trial balance" ok={invariants.trial_balance.ok}
              detail={invariants.trial_balance.ok
                ? 'Every transaction sums to zero.'
                : `sum=${invariants.trial_balance.total}, ${invariants.trial_balance.unbalanced_transactions.length} unbalanced txns`} />
            <InvariantCard name="Projection drift" ok={invariants.projection_drift.ok}
              detail={invariants.projection_drift.ok
                ? 'Read model matches ledger replay.'
                : `${invariants.projection_drift.drifted_count} drifted accounts`} />
            <InvariantCard name="Grant remainders" ok={invariants.grant_remainders.ok}
              detail={invariants.grant_remainders.ok
                ? 'Lot remainders match consumption history.'
                : `${invariants.grant_remainders.drifted_count} drifted grants`} />
          </div>
        )}
      </Section>

      {/* Counters */}
      <Section title="Counters">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <Stat label="Open holds"
            value={`${snapshot.holds.open.count} (${snapshot.holds.open.credits.toLocaleString()} cr)`} />
          <Stat label="Reconciliation holds"
            value={`${snapshot.holds.needs_reconciliation.count} (${snapshot.holds.needs_reconciliation.credits.toLocaleString()} cr)`}
            alert={snapshot.holds.needs_reconciliation.count > 0} />
          <Stat label="Dead money jobs" value={String(w.dead_money_jobs)} alert={w.dead_money_jobs > 0} />
          <Stat label="Dead jobs (all)" value={String(deadTotal)} alert={deadTotal > 0} />
          <Stat label="Oldest pending job"
            value={w.oldest_pending_age_seconds == null ? 'none' : `${Math.floor(w.oldest_pending_age_seconds / 60)}m`} />
          <Stat label="Webhook errors" value={String(snapshot.webhooks.error)} alert={snapshot.webhooks.error > 0} />
          <Stat label="Stale queued webhooks" value={String(snapshot.webhooks.stale_queued)}
            alert={snapshot.webhooks.stale_queued > 0} />
          <Stat label="Hosting stuck pending" value={String(snapshot.hosting.stuck_pending)}
            alert={snapshot.hosting.stuck_pending > 0} />
          <Stat label="Hosting payment due" value={String(snapshot.hosting.payment_due)}
            alert={snapshot.hosting.payment_due > 0} />
          <Stat label="Active w/o charge" value={String(snapshot.hosting.active_without_charge)}
            alert={snapshot.hosting.active_without_charge > 0} />
          <Stat label="Scheduled-lot backlog" value={String(snapshot.scheduled_lots.activation_backlog)}
            alert={snapshot.scheduled_lots.activation_backlog > 0} />
          <Stat label="Clawback drift" value={String(snapshot.clawback.drifted_count)}
            alert={snapshot.clawback.drifted_count > 0} />
          <Stat label="Negative-margin calls (7d)" value={String(snapshot.negative_margin_calls_7d)}
            alert={snapshot.negative_margin_calls_7d > 0} />
          <Stat label="Rated charges" value={Object.entries(snapshot.rated_charges)
            .map(([s, n]) => `${n} ${s}`).join(' · ') || 'none'} />
          <Stat label={`Would-block (${snapshot.would_block.window_days}d)`}
            value={snapshot.would_block.total === 0 ? '0'
              : Object.entries(snapshot.would_block.by_code).map(([c, n]) => `${n} ${c}`).join(' · ')}
            alert={snapshot.would_block.total > 0} />
        </div>
      </Section>

      {/* Drill-downs that only render when non-empty */}
      {w.dead.length > 0 && (
        <Section title="Dead jobs by type">
          <ul className="text-sm space-y-1" style={{ color: '#ff6b6b' }}>
            {w.dead.map(d => <li key={d.job_type} className="font-mono text-xs">{d.job_type}: {d.count}</li>)}
          </ul>
        </Section>
      )}
      {snapshot.clawback.drifted.length > 0 && (
        <Section title="Clawback drift detail">
          <ul className="text-sm space-y-1" style={{ color: '#ff6b6b' }}>
            {snapshot.clawback.drifted.map(d => (
              <li key={d.payment_ref} className="font-mono text-xs">
                {d.payment_ref}: clawed {d.clawed_credits} / target {d.target_credits}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {snapshot.unrated_dimensions.length > 0 && (
        <Section title="Unrated dimensions (provider cost gaps)">
          <ul className="text-xs font-mono space-y-1" style={{ color: '#ffc864' }}>
            {snapshot.unrated_dimensions.map(g => <li key={g}>{g}</li>)}
          </ul>
        </Section>
      )}

      {/* Stripe bindings */}
      <Section title="Unbound Stripe product keys">
        {snapshot.stripe_bindings.no_published_version ? (
          <Empty>No published pricing version.</Empty>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {(['test', 'live'] as const).map(mode => (
              <div key={mode} className="rounded-xl border p-4"
                style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
                <div className="text-xs mb-1 uppercase" style={{ color: 'var(--text-dim)' }}>{mode} mode</div>
                {snapshot.stripe_bindings[mode].length === 0 ? (
                  <span className="text-sm" style={{ color: '#78dca0' }}>all bound</span>
                ) : (
                  <ul className="text-xs font-mono space-y-0.5" style={{ color: '#ffc864' }}>
                    {snapshot.stripe_bindings[mode].map(k => <li key={k}>{k}</li>)}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Heartbeats */}
      <Section title="Loop heartbeats">
        {snapshot.heartbeats.length === 0 ? (
          <Empty>No heartbeats yet — background loops have not run.</Empty>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {snapshot.heartbeats.map(h => (
              <div key={h.name} className="rounded-xl border p-4"
                style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
                <div className="text-xs mb-1 font-mono" style={{ color: 'var(--text-dim)' }}>{h.name}</div>
                <div className="text-sm font-semibold flex items-center gap-1.5" style={{ color: 'var(--text)' }}>
                  <ShieldCheck size={13} style={{ color: '#78dca0' }} />
                  {ago(h.last_run_at)}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

function Section({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="mb-8">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide" style={{ color: 'var(--text-dim)' }}>{title}</h3>
        {action}
      </div>
      {children}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-sm" style={{ color: 'var(--text-dim)' }}>{children}</p>;
}

function Stat({ label, value, alert }: { label: string; value: string; alert?: boolean }) {
  return (
    <div className="rounded-xl border p-4" style={{ background: 'var(--surface)', borderColor: alert ? '#ff6b6b' : 'var(--ink-lighter)' }}>
      <div className="text-xs mb-1" style={{ color: 'var(--text-dim)' }}>{label}</div>
      <div className="text-sm font-semibold" style={{ color: alert ? '#ff6b6b' : 'var(--text)' }}>{value}</div>
    </div>
  );
}

function InvariantCard({ name, ok, detail }: { name: string; ok: boolean; detail: string }) {
  return (
    <div className="rounded-xl border p-4" style={{ background: 'var(--surface)', borderColor: ok ? 'var(--ink-lighter)' : '#ff6b6b' }}>
      <div className="text-xs mb-1" style={{ color: 'var(--text-dim)' }}>{name}</div>
      <div className="text-sm font-semibold" style={{ color: ok ? '#78dca0' : '#ff6b6b' }}>
        {ok ? 'OK' : 'BROKEN'}
      </div>
      <div className="text-xs mt-1" style={{ color: 'var(--text-dim)' }}>{detail}</div>
    </div>
  );
}
