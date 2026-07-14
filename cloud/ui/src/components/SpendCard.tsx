// 039/008 — per-Luna spend summary on the agent detail page. Credits only.

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { API, credits, fmtDate, getJson } from '../pages/billing/api';
import type { BillingSummary, UsageSummary } from '../pages/billing/api';

export function SpendCard({ agentId }: { agentId: string }) {
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [summary, setSummary] = useState<BillingSummary | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getJson<UsageSummary>(`${API}/usage/summary?range=28d`).then(setUsage).catch(() => setFailed(true));
    getJson<BillingSummary>(`${API}/summary`).then(setSummary).catch(() => setFailed(true));
  }, [agentId]);

  const luna = usage?.per_luna.find(l => l.agent_id === agentId);
  const hosting = summary?.hosting.find(h => h.agent_id === agentId);

  const window = (label: string, w: { used_credits: number; limit_credits: number | null }) => (
    <div className="flex items-baseline gap-4 text-sm" key={label}>
      <dt className="w-40 flex-shrink-0" style={{ color: 'var(--text-dim)' }}>{label}</dt>
      <dd className="flex-1" style={{ color: 'var(--text)' }}>
        {credits(w.used_credits)}
        <span className="ml-2 text-xs" style={{ color: 'var(--text-dim)', opacity: 0.7 }}>
          {w.limit_credits != null ? `of ${w.limit_credits.toLocaleString()} cr limit` : 'no limit'}
        </span>
      </dd>
    </div>
  );

  return (
    <section
      className="rounded-2xl p-5 border"
      style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}
    >
      <h3 className="text-sm font-semibold uppercase tracking-wider mb-4" style={{ color: 'var(--text-dim)' }}>
        Spend
      </h3>
      {failed && (
        <p className="text-sm" style={{ color: 'var(--text-dim)' }}>Spend data is unavailable right now.</p>
      )}
      {!failed && !(usage && summary) && (
        <p className="text-sm" style={{ color: 'var(--text-dim)' }}>Loading…</p>
      )}
      {usage && summary && (
        <dl className="space-y-3">
          {luna ? (
            <>
              {window('Today', luna.daily)}
              {window('This month', luna.monthly)}
            </>
          ) : (
            <div className="text-sm" style={{ color: 'var(--text-dim)' }}>No usage recorded yet.</div>
          )}
          <div className="flex items-baseline gap-4 text-sm">
            <dt className="w-40 flex-shrink-0" style={{ color: 'var(--text-dim)' }}>Hosting</dt>
            <dd className="flex-1" style={{ color: hosting?.state === 'payment_due' ? '#ff6b6b' : 'var(--text)' }}>
              {hosting?.state == null
                ? 'not hosted (suspended Lunas cost nothing)'
                : hosting.state === 'payment_due'
                  ? 'payment due — add credits to restart'
                  : `${hosting.state} · ${hosting.price_credits?.toLocaleString()} cr until ${fmtDate(hosting.period_ends_at)}`}
            </dd>
          </div>
          <div className="pt-1">
            <Link to="/dashboard/billing" className="text-sm hover:underline" style={{ color: 'var(--moon)' }}>
              Balance, limits &amp; full usage →
            </Link>
          </div>
        </dl>
      )}
    </section>
  );
}
