import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { GitBranch, Loader2, Copy, Rocket } from 'lucide-react';
import { API, StatusPill, apiError } from './api';
import type { PricingVersion, Rollout } from './api';

export default function PricingVersionsPage() {
  const [versions, setVersions] = useState<PricingVersion[]>([]);
  const [rollouts, setRollouts] = useState<Rollout[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showRollout, setShowRollout] = useState(false);

  const refresh = async () => {
    const [v, r] = await Promise.all([
      fetch(`${API}/versions`),
      fetch(`${API}/rollouts`),
    ]);
    if (v.ok) setVersions((await v.json()).versions);
    if (r.ok) setRollouts((await r.json()).rollouts);
    setLoading(false);
  };
  useEffect(() => { refresh(); }, []);

  const clone = async (id: string) => {
    setError(null);
    const res = await fetch(`${API}/versions/${id}/clone`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (res.ok) refresh();
    else setError(await apiError(res));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  const versionLabel = (id: string) => {
    const v = versions.find(x => x.id === id);
    return v ? `v${v.version_number}` : id.slice(0, 8);
  };

  return (
    <div className="max-w-4xl">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <GitBranch size={20} style={{ color: 'var(--moon)' }} />
          Pricing Versions
        </h2>
        <button
          onClick={() => setShowRollout(v => !v)}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:scale-105"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}
        >
          <Rocket size={16} />
          New Rollout
        </button>
      </div>
      <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>
        Published versions are immutable forever — change pricing by cloning into a
        draft, editing, publishing, then rolling out. Rollback = roll out a prior version.
      </p>

      {error && (
        <div className="rounded-xl px-4 py-3 mb-4 text-sm" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
          {error}
        </div>
      )}

      {showRollout && (
        <RolloutForm versions={versions.filter(v => v.status === 'published')}
          onDone={() => { setShowRollout(false); refresh(); }} onError={setError} />
      )}

      <div className="space-y-2 mb-10">
        {versions.map(v => (
          <div key={v.id} className="rounded-xl border flex items-center gap-3 px-5 py-3"
            style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
            <Link to={`/admin/pricing/versions/${v.id}`} className="flex-1 hover:opacity-80">
              <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
                v{v.version_number}{v.name ? ` — ${v.name}` : ''}
              </span>
              <div className="text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>
                {v.published_at
                  ? `published ${new Date(v.published_at).toLocaleDateString()}`
                  : v.created_at ? `created ${new Date(v.created_at).toLocaleDateString()}` : ''}
                {v.notes ? ` · ${v.notes}` : ''}
              </div>
            </Link>
            <StatusPill status={v.status} />
            <button onClick={() => clone(v.id)} title="Clone into a new draft"
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium"
              style={{ background: 'var(--ink)', color: 'var(--moon)' }}>
              <Copy size={12} /> Clone
            </button>
          </div>
        ))}
        {versions.length === 0 && (
          <p className="text-xs" style={{ color: 'var(--text-dim)' }}>No versions. The seed creates v1 on deploy.</p>
        )}
      </div>

      <h3 className="text-sm font-bold flex items-center gap-2 mb-3" style={{ color: 'var(--text)' }}>
        <Rocket size={16} style={{ color: 'var(--moon)' }} />
        Rollouts
      </h3>
      {rollouts.length === 0 ? (
        <p className="text-xs" style={{ color: 'var(--text-dim)' }}>No rollouts yet.</p>
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--ink-lighter)' }}>
          <table className="w-full text-xs" style={{ color: 'var(--text)' }}>
            <thead>
              <tr style={{ background: 'var(--surface)', color: 'var(--text-dim)' }}>
                <th className="text-left px-4 py-2 font-medium">Version</th>
                <th className="text-left px-4 py-2 font-medium">Audience</th>
                <th className="text-left px-4 py-2 font-medium">Effective</th>
                <th className="text-left px-4 py-2 font-medium">Status</th>
                <th className="text-right px-4 py-2 font-medium">Applied / Failed</th>
              </tr>
            </thead>
            <tbody>
              {rollouts.map((r, i) => (
                <tr key={r.id} style={{ background: i % 2 ? 'var(--surface)' : 'transparent' }}>
                  <td className="px-4 py-2 font-semibold">{versionLabel(r.commercial_pricing_version_id)}</td>
                  <td className="px-4 py-2">{r.audience.replaceAll('_', ' ')}
                    {r.selected_account_ids ? ` (${r.selected_account_ids.length})` : ''}</td>
                  <td className="px-4 py-2">{r.effective_at ? new Date(r.effective_at).toLocaleString() : '—'}</td>
                  <td className="px-4 py-2"><StatusPill status={r.status} /></td>
                  <td className="px-4 py-2 text-right">
                    {r.accounts_applied ?? '—'} / {r.accounts_failed ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RolloutForm({ versions, onDone, onError }: {
  versions: PricingVersion[];
  onDone: () => void;
  onError: (m: string | null) => void;
}) {
  const [versionId, setVersionId] = useState(versions[0]?.id ?? '');
  const [audience, setAudience] = useState('new_accounts');
  const [effectiveAt, setEffectiveAt] = useState('');
  const [selectedIds, setSelectedIds] = useState('');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  const inputStyle = { background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };

  const submit = async () => {
    setSaving(true);
    onError(null);
    const body: Record<string, unknown> = { version_id: versionId, audience, reason };
    if (effectiveAt) body.effective_at = new Date(effectiveAt).toISOString();
    if (audience === 'selected_accounts') {
      body.selected_account_ids = selectedIds.split(/[\s,]+/).filter(Boolean);
    }
    const res = await fetch(`${API}/rollouts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    setSaving(false);
    if (res.ok) onDone();
    else onError(await apiError(res));
  };

  return (
    <div className="rounded-2xl p-5 border mb-4 space-y-2" style={{ background: 'var(--surface)', borderColor: 'var(--moon)' }}>
      <div className="text-sm font-semibold mb-1" style={{ color: 'var(--text)' }}>New rollout</div>
      <div className="flex items-center gap-2 flex-wrap">
        <select value={versionId} onChange={e => setVersionId(e.target.value)}
          className="px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle}>
          {versions.map(v => (
            <option key={v.id} value={v.id}>v{v.version_number}{v.name ? ` — ${v.name}` : ''}</option>
          ))}
        </select>
        <select value={audience} onChange={e => setAudience(e.target.value)}
          className="px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle}>
          <option value="new_accounts">New accounts (default from effective time)</option>
          <option value="selected_accounts">Selected accounts (canary)</option>
          <option value="all_accounts">All accounts</option>
        </select>
        <input type="datetime-local" value={effectiveAt} onChange={e => setEffectiveAt(e.target.value)}
          title="Effective at (empty = now)"
          className="px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} />
      </div>
      {audience === 'selected_accounts' && (
        <textarea value={selectedIds} onChange={e => setSelectedIds(e.target.value)}
          placeholder="Account IDs (comma or newline separated)" rows={2}
          className="w-full px-2.5 py-1.5 rounded-lg text-xs outline-none font-mono" style={inputStyle} />
      )}
      <div className="flex items-center gap-2">
        <input type="text" value={reason} onChange={e => setReason(e.target.value)}
          placeholder="Reason (required — recorded in the audit log)"
          className="flex-1 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} />
        <button onClick={submit} disabled={saving || !versionId || !reason.trim()}
          className="px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
          {saving ? <Loader2 className="animate-spin" size={12} /> : 'Schedule'}
        </button>
      </div>
      <p className="text-xs" style={{ color: 'var(--text-dim)' }}>
        Runs as a durable billing job at the effective time. Existing accounts keep their
        version unless the audience includes them; all-accounts also records the
        next-renewal migration intent for subscriptions.
      </p>
    </div>
  );
}
