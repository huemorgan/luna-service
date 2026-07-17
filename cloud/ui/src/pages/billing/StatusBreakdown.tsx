// 046 — account & payment status breakdown. Read-only: balance, payment
// status banners, credit sources, hosting, credit lots. Rendered as an
// expandable panel on the Dashboard (actions like buying/paying live on the
// Billing page). Credits only — no internal pricing.

import { Link } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { BLOCK_MESSAGES, CREDIT_COLORS, credits, fmtDate } from './api';
import type { BillingSummary, Grant } from './api';

const card = {
  background: 'var(--surface)',
  borderColor: 'var(--ink-lighter)',
} as const;

const GRANT_CATEGORY_LABELS: Record<string, string> = {
  paid: 'Bucket', bonus: 'Bonus', gift: 'Gift', free: 'Free', topup: 'Top-up',
};

function Stat({ label, value, hint, alert }: {
  label: string; value: string; hint?: string; alert?: boolean;
}) {
  return (
    <div className="rounded-2xl p-5 border" style={{
      ...card, borderColor: alert ? 'rgba(255,107,107,0.5)' : 'var(--ink-lighter)',
    }}>
      <div className="text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--text-dim)' }}>{label}</div>
      <div className="text-2xl font-bold" style={{ color: alert ? '#ff6b6b' : 'var(--text)' }}>{value}</div>
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

function SourceBar({ label, hint, granted, remaining, color, maxGranted }: {
  label: string; hint: string; granted: number; remaining: number; color: string;
  maxGranted: number;
}) {
  const used = granted - remaining;
  // Absolute scale: one credit is the same pixel width across every bar, so the
  // full track length is proportional to `granted` vs the largest source. The
  // colored fill is the remaining portion of that same track.
  const trackPct = maxGranted > 0 ? (granted / maxGranted) * 100 : 0;
  const fillPct = granted > 0 ? Math.min(100, (remaining / granted) * 100) : 0;
  return (
    <div className="flex items-center gap-4 text-sm flex-wrap">
      <div className="w-40 flex-shrink-0">
        <div style={{ color: 'var(--text)' }}>{label}</div>
        <div className="text-xs" style={{ color: 'var(--text-dim)' }}>{hint}</div>
      </div>
      <div className="flex-1 min-w-[140px]">
        <div className="h-2 rounded-full overflow-hidden"
          style={{ width: `${trackPct}%`, minWidth: granted > 0 ? 4 : 0, background: 'var(--ink-lighter)' }}>
          <div className="h-full rounded-full" style={{ width: `${fillPct}%`, background: color }} />
        </div>
      </div>
      <span className="tabular-nums text-xs w-56 text-right" style={{ color: 'var(--text-dim)' }}>
        {granted > 0
          ? `${used.toLocaleString()} used · ${remaining.toLocaleString()} left of ${granted.toLocaleString()}`
          : 'none yet'}
      </span>
    </div>
  );
}

export default function StatusBreakdown({ summary, grants }: {
  summary: BillingSummary;
  grants: Grant[] | null;
}) {
  const paymentDue = summary.hosting.filter(h => h.state === 'payment_due');

  const sources = (() => {
    const acc: Record<string, { granted: number; remaining: number }> = {};
    for (const g of grants ?? []) {
      const a = (acc[g.category] ??= { granted: 0, remaining: 0 });
      a.granted += g.original_credits;
      a.remaining += g.remaining_credits;
    }
    const get = (k: string) => acc[k] ?? { granted: 0, remaining: 0 };
    return { bonus: get('bonus'), paid: get('paid'), topup: get('topup'), gift: get('gift'), free: get('free') };
  })();

  // The largest granted source sets the pixel-per-credit scale for every bar.
  const maxGranted = Math.max(
    sources.gift.granted + sources.free.granted,
    sources.bonus.granted,
    sources.paid.granted,
    sources.topup.granted,
    1,
  );

  return (
    <div>
      {/* Payment status */}
      <div className="space-y-3 mb-6">
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
              <Link to="/dashboard/billing" className="block mt-1.5 text-sm font-semibold hover:underline"
                style={{ color: '#ffc864' }}>Manage payment →</Link>
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
        {summary.trial.is_trial && (
          <div className="rounded-xl px-4 py-3 border text-sm" style={{
            background: 'rgba(201,184,255,0.08)', borderColor: 'rgba(201,184,255,0.35)', color: 'var(--text)',
          }}>
            <span className="font-semibold" style={{ color: 'var(--moon)' }}>Free trial.</span>{' '}
            {summary.trial.days_remaining != null && <>{summary.trial.days_remaining} days left</>}
            {summary.trial.expires_at && <> (until {fmtDate(summary.trial.expires_at)})</>}
            {summary.trial.active_luna_cap != null && <> · up to {summary.trial.active_luna_cap} active Luna</>}
          </div>
        )}
      </div>

      {/* Balance stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
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

      {/* Credit sources */}
      {grants && (
        <section className="rounded-2xl p-5 border mb-6" style={card}>
          <SectionTitle>Credit sources</SectionTitle>
          <div className="space-y-4">
            {(sources.gift.granted > 0 || sources.free.granted > 0) && (
              <SourceBar label="Gift & trial credits" hint="granted by Luna — consumed first"
                granted={sources.gift.granted + sources.free.granted}
                remaining={sources.gift.remaining + sources.free.remaining}
                color={CREDIT_COLORS.gift.color} maxGranted={maxGranted} />
            )}
            <SourceBar label="Bonus credits" hint="bundled with packages — consumed before top-ups"
              granted={sources.bonus.granted} remaining={sources.bonus.remaining}
              color={CREDIT_COLORS.bonus.color} maxGranted={maxGranted} />
            <SourceBar label="Bucket credits" hint="your package's monthly credits — consumed last"
              granted={sources.paid.granted} remaining={sources.paid.remaining}
              color={CREDIT_COLORS.paid.color} maxGranted={maxGranted} />
            <SourceBar label="Top-up credits" hint="one-time purchases — consumed before bucket credits"
              granted={sources.topup.granted} remaining={sources.topup.remaining}
              color={CREDIT_COLORS.topup.color} maxGranted={maxGranted} />
          </div>
          <p className="text-xs mt-4" style={{ color: 'var(--text-dim)' }}>
            Credits are consumed cheapest-first: free → gift → bonus → top-up → bucket. Your package's
            bucket credits are always spent last.
          </p>
        </section>
      )}

      {/* Hosting */}
      {summary.hosting.length > 0 && (
        <section className="rounded-2xl p-5 border mb-6" style={card}>
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

      {/* Credit lots */}
      {grants && grants.length > 0 && (
        <section className="rounded-2xl p-5 border" style={card}>
          <SectionTitle>Credit lots</SectionTitle>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>
                <th className="pb-2 font-medium">Type</th>
                <th className="pb-2 font-medium">Remaining</th>
                <th className="pb-2 font-medium">Expires</th>
                <th className="pb-2 font-medium">Status</th>
                <th className="pb-2 font-medium text-right">Consumed order</th>
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
    </div>
  );
}
