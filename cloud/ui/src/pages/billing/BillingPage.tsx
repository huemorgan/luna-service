// 039/008 — customer billing: balance, packages, grants, usage, statement.
// Credits only — no internal pricing ever reaches this page. Purchase actions
// are disabled until Stripe lands (039/007); the API says payments_enabled.
// Split into three tabs: Status (balance, sources, lots), Usage (stats,
// breakdown, actions), Billing (packages, statement).

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Moon, LogOut, ChevronLeft, Loader2, AlertTriangle, Download,
  ChevronDown, ChevronRight, Pencil, Check, X,
} from 'lucide-react';
import {
  API, BLOCK_MESSAGES, credits, fmtDate, fmtDateTime, getJson, postJson, usd, apiError,
} from './api';
import type {
  ActionRow, BillingSummary, BreakdownRow, Grant, Products, StatementRow, UsageSummary,
} from './api';

const card = {
  background: 'var(--surface)',
  borderColor: 'var(--ink-lighter)',
} as const;

const PLAN_NAMES: Record<string, string> = {
  hobby_19: 'Hobby',
  recurring_99: 'Pro',
  recurring_199: 'Power',
};

const planName = (key: string) => {
  const base = key.replace(/_yearly$/, '');
  const name = PLAN_NAMES[base] ?? base;
  return key.endsWith('_yearly') ? `${name} (yearly)` : name;
};

const GRANT_CATEGORY_LABELS: Record<string, string> = {
  paid: 'Bucket', bonus: 'Bonus', gift: 'Gift', free: 'Free', topup: 'Top-up',
};

type TabKey = 'status' | 'usage' | 'billing';
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'status', label: 'Status' },
  { key: 'usage', label: 'Usage' },
  { key: 'billing', label: 'Billing' },
];

type RangeKey = 'today' | '7d' | '28d' | 'custom';

function rangeQuery(range: RangeKey, start: string, end: string): string {
  if (range !== 'custom') return `range=${range}`;
  return `range=custom&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
}

// ── Small building blocks ────────────────────────────────────────────────────

function Stat({ label, value, hint, alert }: {
  label: string; value: string; hint?: string; alert?: boolean;
}) {
  return (
    <div className="rounded-2xl p-5 border" style={{
      ...card,
      borderColor: alert ? 'rgba(255,107,107,0.5)' : 'var(--ink-lighter)',
    }}>
      <div className="text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--text-dim)' }}>
        {label}
      </div>
      <div className="text-2xl font-bold" style={{ color: alert ? '#ff6b6b' : 'var(--text)' }}>
        {value}
      </div>
      {hint && <div className="text-xs mt-1" style={{ color: 'var(--text-dim)' }}>{hint}</div>}
    </div>
  );
}

function Banner({ code, extra }: { code: keyof typeof BLOCK_MESSAGES; extra?: string }) {
  const msg = BLOCK_MESSAGES[code];
  return (
    <div className="rounded-xl px-4 py-3 border flex items-start gap-3 text-sm" style={{
      background: 'rgba(255,107,107,0.08)', borderColor: 'rgba(255,107,107,0.4)',
    }}>
      <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" style={{ color: '#ff6b6b' }} />
      <div>
        <span className="font-semibold" style={{ color: '#ff6b6b' }}>{msg.title}.</span>{' '}
        <span style={{ color: 'var(--text)' }}>{msg.body}</span>
        {extra && <span className="block mt-0.5" style={{ color: 'var(--text-dim)' }}>{extra}</span>}
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-sm font-semibold uppercase tracking-wider mb-4" style={{ color: 'var(--text-dim)' }}>
      {children}
    </h3>
  );
}

function Progress({ used, limit, warnPct }: { used: number; limit: number | null; warnPct: number | null }) {
  if (limit == null || limit <= 0) {
    return <span className="text-xs" style={{ color: 'var(--text-dim)' }}>no limit</span>;
  }
  const pct = Math.min(100, Math.round((used / limit) * 100));
  const warn = warnPct != null && pct >= warnPct;
  const full = used >= limit;
  const color = full ? '#ff6b6b' : warn ? '#ffc864' : 'var(--moon)';
  return (
    <div className="flex items-center gap-2 min-w-[130px]">
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--ink-lighter)' }}>
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="text-xs tabular-nums" style={{ color: 'var(--text-dim)' }}>{pct}%</span>
    </div>
  );
}

// ── Credit source bar (Status tab): filled = remaining, drains as it burns ──

function SourceBar({ label, hint, granted, remaining }: {
  label: string; hint: string; granted: number; remaining: number;
}) {
  const used = granted - remaining;
  const pct = granted > 0 ? Math.min(100, Math.round((remaining / granted) * 100)) : 0;
  return (
    <div className="flex items-center gap-4 text-sm flex-wrap">
      <div className="w-40 flex-shrink-0">
        <div style={{ color: 'var(--text)' }}>{label}</div>
        <div className="text-xs" style={{ color: 'var(--text-dim)' }}>{hint}</div>
      </div>
      <div className="flex-1 h-2 rounded-full overflow-hidden min-w-[140px]" style={{ background: 'var(--ink-lighter)' }}>
        <div className="h-full rounded-full" style={{
          width: `${pct}%`, background: 'var(--moon)', opacity: 0.8,
        }} />
      </div>
      <span className="tabular-nums text-xs w-56 text-right" style={{ color: 'var(--text-dim)' }}>
        {granted > 0
          ? `${used.toLocaleString()} used · ${remaining.toLocaleString()} left of ${granted.toLocaleString()}`
          : 'none yet'}
      </span>
    </div>
  );
}

// ── Per-Luna limit editor ────────────────────────────────────────────────────

function LimitEditor({ luna, onSaved }: {
  luna: UsageSummary['per_luna'][number];
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [daily, setDaily] = useState('');
  const [monthly, setMonthly] = useState('');
  const [warnPct, setWarnPct] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const begin = () => {
    setDaily(luna.daily.limit_credits?.toString() ?? '');
    setMonthly(luna.monthly.limit_credits?.toString() ?? '');
    setWarnPct(luna.warning_threshold_pct?.toString() ?? '');
    setError(null);
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    const num = (s: string) => (s.trim() === '' ? null : Number(s));
    const res = await fetch(`${API}/limits/${luna.agent_id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        daily_limit_credits: num(daily),
        monthly_limit_credits: num(monthly),
        warning_threshold_pct: num(warnPct),
      }),
    });
    setSaving(false);
    if (!res.ok) {
      setError(await apiError(res));
      return;
    }
    setEditing(false);
    onSaved();
  };

  if (!editing) {
    return (
      <button onClick={begin} className="p-1.5 rounded-lg hover:opacity-80 transition-opacity"
        title="Edit limits" style={{ color: 'var(--text-dim)' }}>
        <Pencil size={14} />
      </button>
    );
  }
  const inputCls = 'w-24 px-2 py-1 rounded-lg text-sm border bg-transparent';
  const inputStyle = { borderColor: 'var(--ink-lighter)', color: 'var(--text)' } as const;
  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-dim)' }}>
        <label>daily</label>
        <input className={inputCls} style={inputStyle} value={daily}
          onChange={e => setDaily(e.target.value)} placeholder="none" inputMode="numeric" />
        <label>monthly</label>
        <input className={inputCls} style={inputStyle} value={monthly}
          onChange={e => setMonthly(e.target.value)} placeholder="none" inputMode="numeric" />
        <label>warn %</label>
        <input className={inputCls} style={inputStyle} value={warnPct}
          onChange={e => setWarnPct(e.target.value)} placeholder="80" inputMode="numeric" />
        <button onClick={save} disabled={saving} className="p-1.5 rounded-lg" style={{ color: '#78dca0' }}>
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
        </button>
        <button onClick={() => setEditing(false)} className="p-1.5 rounded-lg" style={{ color: 'var(--text-dim)' }}>
          <X size={14} />
        </button>
      </div>
      {error && <div className="text-xs" style={{ color: '#ff6b6b' }}>{error}</div>}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function BillingPage() {
  const [params, setParams] = useSearchParams();
  const tabParam = params.get('tab');
  const tab: TabKey = tabParam === 'usage' || tabParam === 'billing' ? tabParam : 'status';
  const setTab = (t: TabKey) => setParams(t === 'status' ? {} : { tab: t });

  const [summary, setSummary] = useState<BillingSummary | null>(null);
  const [grants, setGrants] = useState<Grant[] | null>(null);
  const [products, setProducts] = useState<Products | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [range, setRange] = useState<RangeKey>('28d');
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [usageError, setUsageError] = useState<string | null>(null);

  const [breakBy, setBreakBy] = useState('agent');
  const [breakdown, setBreakdown] = useState<BreakdownRow[] | null>(null);

  const [actions, setActions] = useState<ActionRow[] | null>(null);
  const [openAction, setOpenAction] = useState<string | null>(null);

  const [statement, setStatement] = useState<StatementRow[]>([]);
  const [statementDone, setStatementDone] = useState(false);

  // Purchase actions (039/007) — every action just fetches a Stripe URL or
  // applies a code-owned plan change; credits only ever arrive via webhooks.
  const [busy, setBusy] = useState<string | null>(null);
  const [payMsg, setPayMsg] = useState<string | null>(null);
  const [payErr, setPayErr] = useState<string | null>(null);

  const query = useMemo(() => {
    if (range === 'custom' && (!customStart || !customEnd)) return null;
    return rangeQuery(
      range,
      customStart && `${customStart}T00:00:00+00:00`,
      customEnd && `${customEnd}T23:59:59+00:00`,
    );
  }, [range, customStart, customEnd]);

  const loadTop = useCallback(() => {
    getJson<BillingSummary>(`${API}/summary`).then(setSummary).catch(e => setLoadError(e.message));
    getJson<Grant[]>(`${API}/grants`).then(setGrants).catch(() => {});
    getJson<Products>(`${API}/products`).then(setProducts).catch(() => {});
  }, []);

  const loadUsage = useCallback(() => {
    if (!query) return;
    setUsageError(null);
    getJson<UsageSummary>(`${API}/usage/summary?${query}`)
      .then(setUsage).catch(e => setUsageError(e.message));
    getJson<ActionRow[]>(`${API}/usage/actions?${query}&limit=50`).then(setActions).catch(() => {});
  }, [query]);

  useEffect(loadTop, [loadTop]);
  useEffect(loadUsage, [loadUsage]);
  useEffect(() => {
    if (!query) return;
    getJson<BreakdownRow[]>(`${API}/usage/breakdown?by=${breakBy}&${query}`)
      .then(setBreakdown).catch(() => {});
  }, [breakBy, query]);

  const loadStatement = useCallback((offset: number) => {
    getJson<StatementRow[]>(`${API}/statement?limit=50&offset=${offset}`)
      .then(rows => {
        setStatement(prev => (offset === 0 ? rows : [...prev, ...rows]));
        if (rows.length < 50) setStatementDone(true);
      })
      .catch(() => {});
  }, []);
  useEffect(() => loadStatement(0), [loadStatement]);

  const redirectTo = async (path: string, body: unknown, key: string) => {
    setBusy(key);
    setPayErr(null);
    try {
      const { url } = await postJson<{ url: string }>(`${API}${path}`, body);
      window.location.href = url;
    } catch (e) {
      setPayErr((e as Error).message);
      setBusy(null);
    }
  };

  const changePlan = async (productKey: string) => {
    setBusy(productKey);
    setPayErr(null);
    setPayMsg(null);
    try {
      const r = await postJson<{ applied: string }>(`${API}/subscription/change`, { product_key: productKey });
      setPayMsg(r.applied === 'upgrade_invoiced_now'
        ? 'Upgrade confirmed — your new credits arrive as soon as the payment is verified (usually under a minute).'
        : `Plan change scheduled — you switch to ${planName(productKey)} at your next renewal. Nothing extra is charged until then.`);
      loadTop();
    } catch (e) {
      setPayErr((e as Error).message);
    }
    setBusy(null);
  };

  const openPortal = () => redirectTo('/portal', undefined, 'portal');

  const paymentDue = summary?.hosting.filter(h => h.state === 'payment_due') ?? [];
  const trendMax = Math.max(1, ...(usage?.trend.map(t => t.credits) ?? [0]));
  const [interval, setInterval_] = useState<'month' | 'year'>('month');
  const plans = products?.products.filter(p => p.kind === 'subscription' && p.interval === interval) ?? [];
  const topups = products?.products.filter(p => p.kind === 'topup') ?? [];
  const paymentsOn = products?.payments_enabled ?? false;
  const sub = summary?.subscription ?? null;
  const currentPlanPrice = sub
    ? products?.products.find(p => p.key === sub.product_key)?.price_usd_cents ?? null
    : null;
  const checkoutParam = params.get('checkout') ?? params.get('topup');

  // Granted vs consumed per grant category, for the Status source bars.
  const sources = useMemo(() => {
    const acc: Record<string, { granted: number; remaining: number }> = {};
    for (const g of grants ?? []) {
      const a = (acc[g.category] ??= { granted: 0, remaining: 0 });
      a.granted += g.original_credits;
      a.remaining += g.remaining_credits;
    }
    const get = (k: string) => acc[k] ?? { granted: 0, remaining: 0 };
    return { bonus: get('bonus'), paid: get('paid'), topup: get('topup'), gift: get('gift'), free: get('free') };
  }, [grants]);

  return (
    <div className="min-h-screen" style={{ background: 'var(--ink)' }}>
      <header
        className="flex items-center justify-between px-6 py-4 border-b"
        style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}
      >
        <div className="flex items-center gap-3">
          <Moon size={24} style={{ color: 'var(--moon)' }} />
          <span className="text-lg font-semibold" style={{ color: 'var(--text)' }}>Luna Service</span>
        </div>
        <a href="/auth/logout" className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors hover:opacity-80" style={{ color: 'var(--text-dim)' }}>
          <LogOut size={14} />
          Sign out
        </a>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        <nav className="mb-6 flex items-center gap-2 text-sm" style={{ color: 'var(--text-dim)' }}>
          <Link to="/dashboard" className="inline-flex items-center gap-1 hover:underline">
            <ChevronLeft size={14} /> Dashboard
          </Link>
          <span>/</span>
          <span style={{ color: 'var(--text)' }}>Billing</span>
        </nav>

        <h2 className="text-2xl font-bold mb-4" style={{ color: 'var(--text)' }}>Credits &amp; usage</h2>

        <div className="flex items-center gap-1 mb-6 border-b" style={{ borderColor: 'var(--ink-lighter)' }}>
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className="px-4 py-2 text-sm -mb-px border-b-2 transition-colors"
              style={tab === t.key
                ? { borderColor: 'var(--moon)', color: 'var(--text)', fontWeight: 600 }
                : { borderColor: 'transparent', color: 'var(--text-dim)' }}>
              {t.label}
            </button>
          ))}
        </div>

        {loadError && (
          <div className="rounded-xl px-4 py-3 border text-sm mb-6" style={{
            background: 'rgba(255,107,107,0.08)', borderColor: 'rgba(255,107,107,0.4)', color: '#ff6b6b',
          }}>
            {loadError}
          </div>
        )}

        {!summary && !loadError && (
          <div className="flex items-center gap-2 py-16 justify-center" style={{ color: 'var(--text-dim)' }}>
            <Loader2 size={18} className="animate-spin" /> Loading billing…
          </div>
        )}

        {summary && (
          <>
            {/* Block banners derived from the account state — visible on every tab. */}
            <div className="space-y-3 mb-6">
              {checkoutParam === 'success' && (
                <div className="rounded-xl px-4 py-3 border text-sm" style={{
                  background: 'rgba(120,220,160,0.08)', borderColor: 'rgba(120,220,160,0.4)', color: 'var(--text)',
                }}>
                  <span className="font-semibold" style={{ color: '#78dca0' }}>Payment received.</span>{' '}
                  Your credits appear here as soon as the payment is verified — usually under a minute.
                </div>
              )}
              {summary.billing_status === 'past_due' && (
                <div className="rounded-xl px-4 py-3 border flex items-start gap-3 text-sm" style={{
                  background: 'rgba(255,200,100,0.08)', borderColor: 'rgba(255,200,100,0.4)',
                }}>
                  <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" style={{ color: '#ffc864' }} />
                  <div>
                    <span className="font-semibold" style={{ color: '#ffc864' }}>Subscription payment failed.</span>{' '}
                    <span style={{ color: 'var(--text)' }}>
                      {summary.recovery.payment_action_required
                        ? 'Your card needs attention — update it or confirm the charge with your bank.'
                        : 'The renewal charge did not go through.'}
                      {summary.recovery.next_payment_retry_at && (
                        <> We retry automatically on {fmtDate(summary.recovery.next_payment_retry_at)}.</>
                      )}
                    </span>
                    {paymentsOn && (
                      <button onClick={openPortal} disabled={busy === 'portal'}
                        className="block mt-1.5 text-sm font-semibold hover:underline"
                        style={{ color: '#ffc864' }}>
                        {busy === 'portal' ? 'Opening…' : 'Fix payment method →'}
                      </button>
                    )}
                  </div>
                </div>
              )}
              {summary.debt_credits > 0 && (
                <Banner code="credits_exhausted"
                  extra={`Balance is ${credits(summary.posted_balance_credits)}. Add at least ${credits(summary.recovery.credits_required_for_positive_balance)} to get back to positive.`} />
              )}
              {paymentDue.length > 0 && (
                <Banner code="hosting_payment_due"
                  extra={`${paymentDue.map(h => h.agent_name).join(', ')} — restarting needs ${summary.recovery.hosting_restart_credits != null ? credits(summary.recovery.hosting_restart_credits) : 'more credits'}.`} />
              )}
            </div>

            {summary.trial.is_trial && (
              <div className="rounded-xl px-4 py-3 border text-sm mb-6" style={{
                background: 'rgba(201,184,255,0.08)', borderColor: 'rgba(201,184,255,0.35)', color: 'var(--text)',
              }}>
                <span className="font-semibold" style={{ color: 'var(--moon)' }}>Free trial.</span>{' '}
                {summary.trial.days_remaining != null && <>{summary.trial.days_remaining} days left</>}
                {summary.trial.expires_at && <> (until {fmtDate(summary.trial.expires_at)})</>}
                {summary.trial.active_luna_cap != null && <> · up to {summary.trial.active_luna_cap} active Luna</>}
                <span style={{ color: 'var(--text-dim)' }}> — subscribe to lift the caps once payments open.</span>
              </div>
            )}

            {tab === 'status' && (
              <>
                {/* Balance stats */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                  <Stat label="Balance" value={credits(summary.posted_balance_credits)}
                    alert={summary.posted_balance_credits <= 0}
                    hint={`paid ${summary.balances.paid.toLocaleString()} · bonus ${summary.balances.bonus.toLocaleString()} · gift ${summary.balances.gift.toLocaleString()} · top-up ${summary.balances.topup.toLocaleString()}`} />
                  <Stat label="In-flight holds" value={credits(summary.open_exposure_credits)}
                    hint="reserved for running actions" />
                  <Stat label="Debt" value={credits(summary.debt_credits)} alert={summary.debt_credits > 0}
                    hint={summary.debt_credits > 0 ? 'repaid automatically from new credits' : 'none'} />
                  <Stat label="Next expiry" value={summary.next_expiry_at ? fmtDate(summary.next_expiry_at) : '—'}
                    hint="earliest credit lot expiring" />
                </div>

                {/* Credit sources: granted vs consumed per category. */}
                {grants && (
                  <section className="rounded-2xl p-5 border mb-8" style={card}>
                    <SectionTitle>Credit sources</SectionTitle>
                    <div className="space-y-4">
                      {(sources.gift.granted > 0 || sources.free.granted > 0) && (
                        <SourceBar label="Gift & trial credits" hint="granted by Luna — burned first"
                          granted={sources.gift.granted + sources.free.granted}
                          remaining={sources.gift.remaining + sources.free.remaining} />
                      )}
                      <SourceBar label="Bonus credits" hint="bundled with packages — burned before top-ups"
                        granted={sources.bonus.granted} remaining={sources.bonus.remaining} />
                      <SourceBar label="Bucket credits" hint="your package's monthly credits — burned last"
                        granted={sources.paid.granted} remaining={sources.paid.remaining} />
                      <SourceBar label="Top-up credits" hint="one-time purchases — burned before bucket credits"
                        granted={sources.topup.granted} remaining={sources.topup.remaining} />
                    </div>
                    <p className="text-xs mt-4" style={{ color: 'var(--text-dim)' }}>
                      Credits burn cheapest-first: free → gift → bonus → top-up → bucket. Your package's
                      bucket credits are always spent last.
                    </p>
                  </section>
                )}

                {/* Hosting */}
                {summary.hosting.length > 0 && (
                  <section className="rounded-2xl p-5 border mb-8" style={card}>
                    <SectionTitle>Always-on hosting</SectionTitle>
                    <div className="space-y-2">
                      {summary.hosting.map(h => (
                        <div key={h.agent_id} className="flex items-center justify-between text-sm">
                          <Link to={`/dashboard/agents/${h.agent_id}`} className="hover:underline" style={{ color: 'var(--text)' }}>
                            {h.agent_name}
                          </Link>
                          <span style={{ color: h.state === 'payment_due' ? '#ff6b6b' : 'var(--text-dim)' }}>
                            {h.state == null
                              ? 'not hosted'
                              : h.state === 'payment_due'
                                ? 'payment due'
                                : `${h.state} · ${h.price_credits?.toLocaleString()} cr until ${fmtDate(h.period_ends_at)}`}
                          </span>
                        </div>
                      ))}
                    </div>
                    {summary.hosting_price_credits != null && (
                      <p className="text-xs mt-3" style={{ color: 'var(--text-dim)' }}>
                        Hosting is {credits(summary.hosting_price_credits)} per Luna per month, paid from your balance.
                        Suspended Lunas cost nothing.
                      </p>
                    )}
                  </section>
                )}

                {/* Grants */}
                {grants && grants.length > 0 && (
                  <section className="rounded-2xl p-5 border mb-8" style={card}>
                    <SectionTitle>Credit lots</SectionTitle>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-xs uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>
                          <th className="pb-2 font-medium">Type</th>
                          <th className="pb-2 font-medium">Remaining</th>
                          <th className="pb-2 font-medium">Expires</th>
                          <th className="pb-2 font-medium">Status</th>
                          <th className="pb-2 font-medium text-right">Burn order</th>
                        </tr>
                      </thead>
                      <tbody>
                        {grants.map(g => (
                          <tr key={g.id} className="border-t" style={{ borderColor: 'var(--ink-lighter)' }}>
                            <td className="py-2" style={{ color: 'var(--text)' }}>
                              {GRANT_CATEGORY_LABELS[g.category] ?? g.category}
                            </td>
                            <td className="py-2 tabular-nums" style={{ color: 'var(--text)' }}>
                              {g.remaining_credits.toLocaleString()} / {g.original_credits.toLocaleString()}
                            </td>
                            <td className="py-2" style={{ color: 'var(--text-dim)' }}>{fmtDate(g.expires_at)}</td>
                            <td className="py-2" style={{ color: 'var(--text-dim)' }}>{g.status}</td>
                            <td className="py-2 text-right" style={{ color: 'var(--text-dim)' }}>
                              {g.use_next_order != null ? `#${g.use_next_order}` : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </section>
                )}
              </>
            )}

            {tab === 'usage' && (
              <>
                {/* Usage */}
                <section className="rounded-2xl p-5 border mb-8" style={card}>
                  <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
                    <SectionTitle>Usage</SectionTitle>
                    <div className="flex items-center gap-2 text-sm">
                      {(['today', '7d', '28d', 'custom'] as RangeKey[]).map(k => (
                        <button key={k} onClick={() => setRange(k)}
                          className="px-3 py-1.5 rounded-lg transition-colors"
                          style={range === k
                            ? { background: 'var(--moon)', color: 'var(--ink)', fontWeight: 600 }
                            : { color: 'var(--text-dim)' }}>
                          {k === 'today' ? 'Today' : k === 'custom' ? 'Custom' : `Last ${k.replace('d', ' days')}`}
                        </button>
                      ))}
                      {range === 'custom' && (
                        <>
                          <input type="date" value={customStart} onChange={e => setCustomStart(e.target.value)}
                            className="px-2 py-1 rounded-lg border bg-transparent text-sm"
                            style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)', colorScheme: 'dark' }} />
                          <span style={{ color: 'var(--text-dim)' }}>→</span>
                          <input type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)}
                            className="px-2 py-1 rounded-lg border bg-transparent text-sm"
                            style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)', colorScheme: 'dark' }} />
                        </>
                      )}
                    </div>
                  </div>

                  {usageError && <div className="text-sm mb-3" style={{ color: '#ff6b6b' }}>{usageError}</div>}

                  {usage && (
                    <>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
                        <Stat label="Used in range" value={credits(usage.used_credits)} />
                        <Stat label="Today" value={credits(usage.today_credits)} />
                        <Stat label="This month" value={credits(usage.month_credits)} />
                        <Stat label="Est. days left"
                          value={usage.projected_depletion_days != null ? `~${usage.projected_depletion_days}` : '—'}
                          hint="estimate from this range's average" />
                      </div>

                      {usage.trend.length > 0 && (
                        <div className="mb-6">
                          <div className="flex items-end gap-1 h-24">
                            {usage.trend.map(t => (
                              <div key={t.day} className="flex-1 rounded-t"
                                title={`${t.day}: ${t.credits.toLocaleString()} cr`}
                                style={{
                                  height: `${Math.max(3, (t.credits / trendMax) * 100)}%`,
                                  background: 'var(--moon)', opacity: 0.75, minWidth: 3,
                                }} />
                            ))}
                          </div>
                          <div className="flex justify-between text-xs mt-1" style={{ color: 'var(--text-dim)' }}>
                            <span>{usage.trend[0].day}</span>
                            <span>{usage.trend[usage.trend.length - 1].day}</span>
                          </div>
                        </div>
                      )}

                      {/* Per-Luna limits */}
                      <div className="mb-2">
                        <div className="text-xs uppercase tracking-wider mb-3" style={{ color: 'var(--text-dim)' }}>
                          Per-Luna limits
                        </div>
                        <div className="space-y-3">
                          {usage.per_luna.map(l => (
                            <div key={l.agent_id} className="flex items-center justify-between gap-4 text-sm flex-wrap">
                              <Link to={`/dashboard/agents/${l.agent_id}`} className="hover:underline min-w-[120px]"
                                style={{ color: 'var(--text)' }}>
                                {l.agent_name}
                              </Link>
                              <div className="flex items-center gap-2">
                                <span className="text-xs w-12" style={{ color: 'var(--text-dim)' }}>daily</span>
                                <span className="text-xs tabular-nums w-28" style={{ color: 'var(--text)' }}>
                                  {l.daily.used_credits.toLocaleString()}{l.daily.limit_credits != null && ` / ${l.daily.limit_credits.toLocaleString()}`} cr
                                </span>
                                <Progress used={l.daily.used_credits} limit={l.daily.limit_credits} warnPct={l.warning_threshold_pct} />
                              </div>
                              <div className="flex items-center gap-2">
                                <span className="text-xs w-14" style={{ color: 'var(--text-dim)' }}>monthly</span>
                                <span className="text-xs tabular-nums w-28" style={{ color: 'var(--text)' }}>
                                  {l.monthly.used_credits.toLocaleString()}{l.monthly.limit_credits != null && ` / ${l.monthly.limit_credits.toLocaleString()}`} cr
                                </span>
                                <Progress used={l.monthly.used_credits} limit={l.monthly.limit_credits} warnPct={l.warning_threshold_pct} />
                              </div>
                              <LimitEditor luna={l} onSaved={loadUsage} />
                            </div>
                          ))}
                          {usage.per_luna.length === 0 && (
                            <div className="text-sm" style={{ color: 'var(--text-dim)' }}>No Lunas yet.</div>
                          )}
                        </div>
                        <p className="text-xs mt-3" style={{ color: 'var(--text-dim)' }}>
                          Limits cap what each Luna can spend (hosting excluded). Only the account owner can change them.
                        </p>
                      </div>
                    </>
                  )}
                </section>

                {/* Breakdown */}
                <section className="rounded-2xl p-5 border mb-8" style={card}>
                  <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
                    <SectionTitle>Where credits went</SectionTitle>
                    <div className="flex items-center gap-1 text-sm flex-wrap">
                      {[['agent', 'Luna'], ['service', 'Service'], ['plugin', 'Plugin'],
                        ['action_type', 'Action type'], ['model', 'Model'], ['root_action', 'Action']].map(([k, label]) => (
                        <button key={k} onClick={() => setBreakBy(k)}
                          className="px-3 py-1.5 rounded-lg transition-colors"
                          style={breakBy === k
                            ? { background: 'var(--moon)', color: 'var(--ink)', fontWeight: 600 }
                            : { color: 'var(--text-dim)' }}>
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                  {breakdown && breakdown.length > 0 ? (
                    <div className="space-y-2">
                      {breakdown.map(r => {
                        const max = breakdown[0].credits || 1;
                        return (
                          <div key={`${r.key}-${r.id}`} className="flex items-center gap-3 text-sm">
                            <span className="w-48 truncate" style={{ color: 'var(--text)' }}>{r.key}</span>
                            <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--ink-lighter)' }}>
                              <div className="h-full rounded-full" style={{
                                width: `${Math.max(2, (r.credits / max) * 100)}%`, background: 'var(--moon)', opacity: 0.75,
                              }} />
                            </div>
                            <span className="tabular-nums w-24 text-right" style={{ color: 'var(--text)' }}>
                              {credits(r.credits)}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="text-sm" style={{ color: 'var(--text-dim)' }}>No usage in this range.</div>
                  )}
                </section>

                {/* Actions */}
                <section className="rounded-2xl p-5 border mb-8" style={card}>
                  <div className="flex items-center justify-between mb-4">
                    <SectionTitle>Recent actions</SectionTitle>
                    {query && (
                      <a href={`${API}/usage/actions.csv?${query}`}
                        className="flex items-center gap-1.5 text-sm hover:opacity-80" style={{ color: 'var(--moon)' }}>
                        <Download size={14} /> CSV
                      </a>
                    )}
                  </div>
                  {actions && actions.length > 0 ? (
                    <div className="space-y-1">
                      {actions.map(a => (
                        <div key={a.root_action_id}>
                          <button
                            onClick={() => setOpenAction(openAction === a.root_action_id ? null : a.root_action_id)}
                            className="w-full flex items-center gap-3 text-sm py-2 text-left hover:opacity-80">
                            {openAction === a.root_action_id
                              ? <ChevronDown size={14} style={{ color: 'var(--text-dim)' }} />
                              : <ChevronRight size={14} style={{ color: 'var(--text-dim)' }} />}
                            <span className="w-32 flex-shrink-0 text-xs" style={{ color: 'var(--text-dim)' }}>
                              {fmtDateTime(a.at)}
                            </span>
                            <span className="w-36 truncate" style={{ color: 'var(--text)' }}>{a.agent_name ?? '—'}</span>
                            <span className="flex-1" style={{ color: 'var(--text)' }}>{a.label}</span>
                            <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{a.status}</span>
                            <span className="tabular-nums w-20 text-right" style={{ color: 'var(--text)' }}>
                              {credits(a.credits)}
                            </span>
                          </button>
                          {openAction === a.root_action_id && (
                            <div className="ml-9 mb-2 space-y-1">
                              {a.children.map(c => (
                                <div key={c.call_id} className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-dim)' }}>
                                  <span className="w-28 flex-shrink-0">{fmtDateTime(c.at)}</span>
                                  <span className="w-24">{c.service}</span>
                                  <span className="flex-1 truncate">{c.plugin ?? c.model ?? '—'}</span>
                                  <span>{c.status}</span>
                                  <span className="tabular-nums w-20 text-right">{credits(c.credits)}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm" style={{ color: 'var(--text-dim)' }}>No actions in this range.</div>
                  )}
                </section>
              </>
            )}

            {tab === 'billing' && (
              <>
                {/* Packages */}
                {products && (
                  <section className="mb-8">
                    <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
                      <SectionTitle>Packages</SectionTitle>
                      <div className="flex items-center gap-1 text-sm">
                        {(['month', 'year'] as const).map(k => (
                          <button key={k} onClick={() => setInterval_(k)}
                            className="px-3 py-1.5 rounded-lg transition-colors"
                            style={interval === k
                              ? { background: 'var(--moon)', color: 'var(--ink)', fontWeight: 600 }
                              : { color: 'var(--text-dim)' }}>
                            {k === 'month' ? 'Monthly' : 'Yearly'}
                          </button>
                        ))}
                      </div>
                    </div>

                    {payMsg && (
                      <div className="rounded-xl px-4 py-3 border text-sm mb-4" style={{
                        background: 'rgba(120,220,160,0.08)', borderColor: 'rgba(120,220,160,0.4)', color: 'var(--text)',
                      }}>
                        {payMsg}
                      </div>
                    )}
                    {payErr && (
                      <div className="rounded-xl px-4 py-3 border text-sm mb-4" style={{
                        background: 'rgba(255,107,107,0.08)', borderColor: 'rgba(255,107,107,0.4)', color: '#ff6b6b',
                      }}>
                        {payErr}
                      </div>
                    )}
                    {sub?.pending_product_key && (
                      <p className="text-sm mb-4" style={{ color: 'var(--text-dim)' }}>
                        Your plan switches to <span style={{ color: 'var(--text)' }}>{planName(sub.pending_product_key)}</span>
                        {sub.current_period_end && <> on {fmtDate(sub.current_period_end)}</>} — nothing extra is
                        charged until then.
                      </p>
                    )}

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      {plans.map(p => {
                        const yearlyPlan = p.interval === 'year';
                        // 1 credit = 1¢, so a credit total IS a cent amount.
                        const monthlyValue = yearlyPlan
                          ? (p.monthly_paid_lot_credits ?? 0) + (p.monthly_bonus_lot_credits ?? 0)
                          : p.paid_credits + p.bonus_credits;
                        const monthlyPrice = yearlyPlan ? p.price_usd_cents / 12 : p.price_usd_cents;
                        const action = (() => {
                          if (!paymentsOn) return { label: 'Coming soon', disabled: true };
                          if (busy === p.key) return { label: 'One moment…', disabled: true };
                          if (!sub) {
                            return {
                              label: 'Subscribe',
                              onClick: () => redirectTo('/checkout/subscription', { product_key: p.key }, p.key),
                            };
                          }
                          if (sub.product_key === p.key) return { label: 'Current plan', disabled: true };
                          if (sub.pending_product_key === p.key) return { label: 'Starts at renewal', disabled: true };
                          const upgrade = currentPlanPrice == null || p.price_usd_cents > currentPlanPrice;
                          return {
                            label: upgrade ? 'Upgrade now' : 'Switch at renewal',
                            onClick: () => changePlan(p.key),
                          };
                        })();
                        return (
                          <div key={p.key} className="rounded-2xl p-5 border" style={{
                            ...card,
                            borderColor: sub?.product_key === p.key ? 'var(--moon)' : 'var(--ink-lighter)',
                          }}>
                            <div className="text-sm font-semibold mb-1" style={{ color: 'var(--moon)' }}>
                              {PLAN_NAMES[p.key.replace(/_yearly$/, '')] ?? p.key}
                            </div>
                            <div className="text-2xl font-bold mb-2" style={{ color: 'var(--text)' }}>
                              {monthlyValue > monthlyPrice && (
                                <s className="text-base font-medium mr-2" style={{ color: 'var(--text-dim)' }}>
                                  {usd(monthlyValue)}
                                </s>
                              )}
                              {usd(monthlyPrice)}
                              <span className="text-sm font-normal" style={{ color: 'var(--text-dim)' }}>
                                {yearlyPlan ? '/mo billed yearly' : '/mo'}
                              </span>
                            </div>
                            <div className="text-sm" style={{ color: 'var(--text)' }}>
                              {(yearlyPlan ? (p.monthly_paid_lot_credits ?? 0) : p.paid_credits).toLocaleString()} credits monthly
                              {(yearlyPlan ? (p.monthly_bonus_lot_credits ?? 0) : p.bonus_credits) > 0 && (
                                <> + {(yearlyPlan ? (p.monthly_bonus_lot_credits ?? 0) : p.bonus_credits).toLocaleString()} bonus</>
                              )}
                              {yearlyPlan && p.yearly_gift_credits > 0 && (
                                <span className="block text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>
                                  + {p.yearly_gift_credits.toLocaleString()} gift credits for the year
                                </span>
                              )}
                            </div>
                            <button disabled={action.disabled} onClick={action.onClick}
                              className={`mt-4 w-full px-4 py-2 rounded-xl text-sm font-semibold transition-opacity ${
                                action.disabled ? 'cursor-not-allowed opacity-50' : 'hover:opacity-90'}`}
                              style={{ background: 'var(--moon)', color: 'var(--ink)' }}
                              title={paymentsOn ? undefined : 'Online payments are rolling out'}>
                              {action.label}
                            </button>
                          </div>
                        );
                      })}
                    </div>

                    {/* Top-ups: fixed catalog steps only — the server re-checks. */}
                    {topups.length > 0 && (
                      paymentsOn ? (
                        <div className="mt-5">
                          <div className="text-xs uppercase tracking-wider mb-2" style={{ color: 'var(--text-dim)' }}>
                            One-time top-up
                          </div>
                          <div className="flex items-center gap-2 flex-wrap">
                            {topups.map(t => (
                              <button key={t.key} disabled={busy === t.key}
                                onClick={() => redirectTo('/checkout/topup', { amount_usd_cents: t.price_usd_cents }, t.key)}
                                className="px-4 py-2 rounded-xl text-sm border transition-colors hover:opacity-80"
                                style={{ ...card, color: 'var(--text)' }}>
                                {busy === t.key
                                  ? 'One moment…'
                                  : <>{usd(t.price_usd_cents)} → {t.paid_credits.toLocaleString()} cr</>}
                              </button>
                            ))}
                          </div>
                          <p className="text-xs mt-2" style={{ color: 'var(--text-dim)' }}>
                            Top-up credits never expire and are spent before your package credits.
                          </p>
                        </div>
                      ) : (
                        <p className="text-xs mt-3" style={{ color: 'var(--text-dim)' }}>
                          Top-ups: {topups.map(t => `${usd(t.price_usd_cents)} → ${t.paid_credits.toLocaleString()} cr`).join(' · ')}.
                          Online payments are rolling out — packages are shown for transparency.
                        </p>
                      )
                    )}

                    {paymentsOn && (
                      <button onClick={openPortal} disabled={busy === 'portal'}
                        className="mt-5 text-sm hover:underline" style={{ color: 'var(--moon)' }}>
                        {busy === 'portal' ? 'Opening…' : 'Manage payment methods & invoices →'}
                      </button>
                    )}
                  </section>
                )}

                {/* Statement */}
                <section className="rounded-2xl p-5 border mb-8" style={card}>
                  <SectionTitle>Statement</SectionTitle>
                  {statement.length > 0 ? (
                    <>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>
                            <th className="pb-2 font-medium">When</th>
                            <th className="pb-2 font-medium">What</th>
                            <th className="pb-2 font-medium">Luna</th>
                            <th className="pb-2 font-medium text-right">Credits</th>
                            <th className="pb-2 font-medium text-right">Balance</th>
                          </tr>
                        </thead>
                        <tbody>
                          {statement.map((r, i) => (
                            <tr key={i} className="border-t" style={{ borderColor: 'var(--ink-lighter)' }}>
                              <td className="py-2 text-xs" style={{ color: 'var(--text-dim)' }}>{fmtDateTime(r.at)}</td>
                              <td className="py-2" style={{ color: 'var(--text)' }}>
                                {r.reason ?? r.type}
                                {r.service && <span className="text-xs ml-2" style={{ color: 'var(--text-dim)' }}>{r.service}</span>}
                              </td>
                              <td className="py-2" style={{ color: 'var(--text-dim)' }}>{r.agent_name ?? '—'}</td>
                              <td className="py-2 text-right tabular-nums"
                                style={{ color: r.credits >= 0 ? '#78dca0' : 'var(--text)' }}>
                                {r.credits >= 0 ? '+' : ''}{r.credits.toLocaleString()}
                              </td>
                              <td className="py-2 text-right tabular-nums" style={{ color: 'var(--text-dim)' }}>
                                {r.balance_after.toLocaleString()}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {!statementDone && (
                        <button onClick={() => loadStatement(statement.length)}
                          className="mt-3 text-sm hover:underline" style={{ color: 'var(--moon)' }}>
                          Load more
                        </button>
                      )}
                    </>
                  ) : (
                    <div className="text-sm" style={{ color: 'var(--text-dim)' }}>No wallet movements yet.</div>
                  )}
                </section>
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}
