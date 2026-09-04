// 039/008 + 046 — customer Billing page: payment status banners, packages,
// and statement. Balance/credit sources/hosting/credit-lots breakdown moved to
// the Dashboard "Account & payment status" panel; Usage to /dashboard/usage.
// No tabs — this page is just Billing. Credits only — no internal pricing.

import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  ChevronLeft, Loader2, AlertTriangle,
} from 'lucide-react';
import AppHeader from '../../components/AppHeader';
import {
  API, BLOCK_MESSAGES, credits, fmtDate, fmtDateTime, getJson, postJson, usd,
} from './api';
import type {
  BillingSummary, Products, StatementRow,
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

// ── Small building blocks ────────────────────────────────────────────────────

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

// ── Page ─────────────────────────────────────────────────────────────────────

export default function BillingPage() {
  const [params] = useSearchParams();

  const [summary, setSummary] = useState<BillingSummary | null>(null);
  const [products, setProducts] = useState<Products | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [statement, setStatement] = useState<StatementRow[]>([]);
  const [statementDone, setStatementDone] = useState(false);

  const [busy, setBusy] = useState<string | null>(null);
  const [couponCode, setCouponCode] = useState('');
  const [couponBusy, setCouponBusy] = useState(false);
  const [couponMsg, setCouponMsg] = useState<string | null>(null);
  const [couponErr, setCouponErr] = useState<string | null>(null);
  const [payMsg, setPayMsg] = useState<string | null>(null);
  const [payErr, setPayErr] = useState<string | null>(null);
  const [interval, setInterval_] = useState<'month' | 'year'>('month');

  const loadTop = useCallback(() => {
    getJson<BillingSummary>(`${API}/summary`).then(setSummary).catch(e => setLoadError(e.message));
    getJson<Products>(`${API}/products`).then(setProducts).catch(() => {});
  }, []);
  useEffect(loadTop, [loadTop]);

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

  const redeemCoupon = async () => {
    const code = couponCode.trim();
    if (!code) return;
    setCouponBusy(true);
    setCouponErr(null);
    setCouponMsg(null);
    try {
      const r = await postJson<{ credits: number; expires_at: string | null }>(
        `${API}/coupons/redeem`, { code },
      );
      setCouponMsg(`Coupon accepted — ${r.credits.toLocaleString()} credits added to your account${
        r.expires_at ? ` (valid until ${fmtDate(r.expires_at)})` : ''}.`);
      setCouponCode('');
      loadTop();
      loadStatement(0);
    } catch (e) {
      setCouponErr((e as Error).message);
    }
    setCouponBusy(false);
  };

  const paymentDue = summary?.hosting.filter(h => h.state === 'payment_due') ?? [];
  const plans = products?.products.filter(p => p.kind === 'subscription' && p.interval === interval) ?? [];
  const topups = products?.products.filter(p => p.kind === 'topup') ?? [];
  const paymentsOn = products?.payments_enabled ?? false;
  const sub = summary?.subscription ?? null;
  const currentPlanPrice = sub
    ? products?.products.find(p => p.key === sub.product_key)?.price_usd_cents ?? null
    : null;
  const checkoutParam = params.get('checkout') ?? params.get('topup');

  return (
    <div className="min-h-screen" style={{ background: 'var(--ink)' }}>
      <AppHeader />

      <main className="max-w-5xl mx-auto px-6 py-8">
        <nav className="mb-6 flex items-center gap-2 text-sm" style={{ color: 'var(--text-dim)' }}>
          <Link to="/dashboard" className="inline-flex items-center gap-1 hover:underline">
            <ChevronLeft size={14} /> Dashboard
          </Link>
          <span>/</span>
          <span style={{ color: 'var(--text)' }}>Billing</span>
        </nav>

        <h2 className="text-2xl font-bold mb-6" style={{ color: 'var(--text)' }}>Billing</h2>

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
            {/* Block banners derived from account state. */}
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

            <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>
              Your account balance and full credit breakdown live under{' '}
              <Link to="/dashboard" className="hover:underline" style={{ color: 'var(--moon)' }}>
                Account &amp; payment status
              </Link>{' '}on the dashboard.
            </p>

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

            {/* Coupon */}
            <section className="rounded-2xl p-5 border mb-8" style={card}>
              <SectionTitle>Coupon</SectionTitle>
              <div className="flex items-center gap-2 flex-wrap">
                <input
                  value={couponCode}
                  onChange={e => setCouponCode(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') redeemCoupon(); }}
                  placeholder="Enter coupon code"
                  className="px-3 py-2 rounded-xl text-sm border bg-transparent outline-none"
                  style={{ ...card, color: 'var(--text)', minWidth: '16rem' }}
                />
                <button onClick={redeemCoupon} disabled={couponBusy || !couponCode.trim()}
                  className={`px-4 py-2 rounded-xl text-sm font-semibold transition-opacity ${
                    couponBusy || !couponCode.trim() ? 'cursor-not-allowed opacity-50' : 'hover:opacity-90'}`}
                  style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
                  {couponBusy ? 'Redeeming…' : 'Redeem'}
                </button>
              </div>
              {couponMsg && (
                <div className="rounded-xl px-4 py-3 border text-sm mt-3" style={{
                  background: 'rgba(120,220,160,0.08)', borderColor: 'rgba(120,220,160,0.4)', color: 'var(--text)',
                }}>
                  {couponMsg}
                </div>
              )}
              {couponErr && (
                <div className="rounded-xl px-4 py-3 border text-sm mt-3" style={{
                  background: 'rgba(255,107,107,0.08)', borderColor: 'rgba(255,107,107,0.4)', color: '#ff6b6b',
                }}>
                  {couponErr}
                </div>
              )}
            </section>

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
      </main>
    </div>
  );
}
