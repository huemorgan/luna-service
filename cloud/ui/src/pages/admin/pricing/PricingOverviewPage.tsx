import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Coins, Loader2, AlertTriangle } from 'lucide-react';
import { API, StatusPill, creditsUsd } from './api';
import type { Overview } from './api';

export default function PricingOverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/overview`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }
  if (!data) return <p className="text-sm" style={{ color: 'var(--text-dim)' }}>Failed to load overview.</p>;

  const dv = data.default_version;
  const attention = data.dead_billing_jobs + data.needs_reconciliation_holds > 0;

  return (
    <div className="max-w-4xl">
      <h2 className="text-xl font-bold flex items-center gap-2 mb-2" style={{ color: 'var(--text)' }}>
        <Coins size={20} style={{ color: 'var(--moon)' }} />
        Pricing Overview
      </h2>
      <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>
        Commercial pricing state. Liability and debt come from the rebuildable
        balance projection — the ledger stays authoritative.
      </p>

      <div className="rounded-xl border p-5 mb-6" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
        <div className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-dim)' }}>
          New-account default version
        </div>
        {dv ? (
          <div className="flex items-center gap-3">
            <Link to={`/admin/pricing/versions/${dv.id}`} className="text-sm font-semibold hover:underline" style={{ color: 'var(--text)' }}>
              v{dv.version_number}{dv.name ? ` — ${dv.name}` : ''}
            </Link>
            <StatusPill status={dv.status} />
          </div>
        ) : (
          <span className="text-sm" style={{ color: '#ff6b6b' }}>
            No published version — new accounts get no pricing assignment.
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
        <Stat label="Customer liability" value={creditsUsd(data.customer_liability_credits)} />
        <Stat label="Uncovered debt" value={creditsUsd(data.uncovered_debt_credits)}
          alert={data.uncovered_debt_credits > 0} />
        <Stat label="Assigned accounts" value={String(data.assigned_accounts)} />
        <Stat label="Dead billing jobs" value={String(data.dead_billing_jobs)}
          alert={data.dead_billing_jobs > 0} />
        <Stat label="Reconciliation holds" value={String(data.needs_reconciliation_holds)}
          alert={data.needs_reconciliation_holds > 0} />
        <Stat label="Versions" value={Object.entries(data.version_status_counts)
          .map(([s, n]) => `${n} ${s}`).join(' · ') || 'none'} />
      </div>

      {attention && (
        <div className="rounded-xl px-4 py-3 text-sm flex items-center gap-2"
          style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
          <AlertTriangle size={16} />
          Billing work needs operator attention — check dead jobs / reconciliation holds.
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, alert }: { label: string; value: string; alert?: boolean }) {
  return (
    <div className="rounded-xl border p-4" style={{ background: 'var(--surface)', borderColor: alert ? '#ff6b6b' : 'var(--ink-lighter)' }}>
      <div className="text-xs mb-1" style={{ color: 'var(--text-dim)' }}>{label}</div>
      <div className="text-sm font-semibold" style={{ color: alert ? '#ff6b6b' : 'var(--text)' }}>{value}</div>
    </div>
  );
}
