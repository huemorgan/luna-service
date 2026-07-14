// 039/009 — pricing simulator: replay recorded usage under a candidate config.
import { useCallback, useEffect, useRef, useState } from 'react';
import { FlaskConical, Loader2, RefreshCw, Download, XCircle, Repeat } from 'lucide-react';
import { API, StatusPill, apiError } from './api';
import type { PricingVersion } from './api';

interface SimSummary {
  id: string;
  state: string;
  filters: Record<string, unknown> | null;
  baseline_version_id: string | null;
  candidate_version_id: string | null;
  provider_cost_basis: string;
  transforms: Record<string, unknown> | null;
  replay_mode: string | null;
  funding_mode: string | null;
  event_count: number | null;
  config_hash: string;
  created_at: string | null;
  result_hash?: string | null;
  error?: string | null;
}

interface SideTotals {
  credits: number;
  face_value_micro_usd: number;
  cash_basis_micro_usd: number | null;
  vendor_micro_usd: number;
  margin_micro_usd: number;
  luna_absorbed_micro_usd: number;
  gross_profit_face_micro_usd: number;
  gross_profit_cash_micro_usd: number | null;
  hosting_credits: number;
  unpriced_calls: number;
  blocked_calls: number;
  blocked_credits: number;
  accounts_hit_zero: number;
  accounts_in_debt: number;
  rated_calls: number;
}

interface PerAccount {
  account_id: string;
  baseline_credits: number;
  candidate_credits: number;
  baseline_blocked: number;
  candidate_blocked: number;
}

interface SimResult {
  event_count: number;
  missing_events: number;
  logical_calls: number;
  accounts: number;
  baseline: SideTotals;
  candidate: SideTotals;
  delta: Record<string, number | null>;
  winners: PerAccount[];
  losers: PerAccount[];
  unrated_dimensions: string[];
  labels: Record<string, string>;
  result_hash: string;
  error?: string;
}

interface SimDetail extends SimSummary {
  result: SimResult | null;
}

const usd = (micro: number | null) =>
  micro == null ? '—' : `$${(micro / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export default function PricingSimulationsPage() {
  const [sims, setSims] = useState<SimSummary[]>([]);
  const [versions, setVersions] = useState<PricingVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<SimDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    const res = await fetch(`${API}/simulations`);
    if (res.ok) setSims((await res.json()).simulations);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    fetch(`${API}/versions`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => setVersions(d.versions))
      .catch(() => setVersions([]));
  }, [load]);

  // Poll while any run is pending/running — the durable worker executes them.
  useEffect(() => {
    const active = sims.some(s => s.state === 'pending' || s.state === 'running');
    if (active && pollRef.current == null) {
      pollRef.current = window.setInterval(load, 3000);
    } else if (!active && pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current != null) { window.clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [sims, load]);

  const open = async (id: string) => {
    setError(null);
    const res = await fetch(`${API}/simulations/${id}`);
    if (res.ok) setSelected(await res.json());
    else setError(await apiError(res));
  };

  const act = async (id: string, action: 'rerun' | 'cancel') => {
    setError(null);
    const res = await fetch(`${API}/simulations/${id}/${action}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    if (!res.ok) setError(await apiError(res));
    await load();
    if (selected?.id === id && action === 'cancel') await open(id);
  };

  const vLabel = (id: string | null) => {
    const v = versions.find(x => x.id === id);
    return v ? `v${v.version_number}${v.name ? ` — ${v.name}` : ''}` : (id ? id.slice(0, 8) : '—');
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  return (
    <div className="max-w-5xl">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <FlaskConical size={20} style={{ color: 'var(--moon)' }} />
          Pricing Simulator
        </h2>
        <button onClick={() => { setLoading(true); load(); }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors hover:opacity-80"
          style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text-dim)' }}>
          <RefreshCw size={12} /> Refresh
        </button>
      </div>
      <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>
        Replays recorded usage under a candidate config — reads production events,
        never writes to the ledger. Runs pin an event manifest, so a rerun always
        reproduces the same result.
      </p>

      {error && (
        <div className="rounded-xl px-4 py-3 text-sm mb-4"
          style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>{error}</div>
      )}

      <CreateForm versions={versions} onCreated={load} onError={setError} />

      <h3 className="text-sm font-semibold uppercase tracking-wide mb-3" style={{ color: 'var(--text-dim)' }}>Runs</h3>
      {sims.length === 0 ? (
        <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>No simulations yet.</p>
      ) : (
        <table className="w-full text-sm mb-8">
          <thead>
            <tr style={{ color: 'var(--text-dim)' }} className="text-left text-xs">
              <th className="pb-2 font-medium">Created</th>
              <th className="pb-2 font-medium">Baseline → Candidate</th>
              <th className="pb-2 font-medium">Mode</th>
              <th className="pb-2 font-medium">Events</th>
              <th className="pb-2 font-medium">State</th>
              <th className="pb-2 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {sims.map(s => (
              <tr key={s.id} className="border-t cursor-pointer hover:opacity-80"
                style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)' }}
                onClick={() => open(s.id)}>
                <td className="py-2 pr-3 text-xs" style={{ color: 'var(--text-dim)' }}>
                  {s.created_at ? new Date(s.created_at).toLocaleString() : '—'}
                </td>
                <td className="py-2 pr-3 text-xs">{vLabel(s.baseline_version_id)} → {vLabel(s.candidate_version_id)}</td>
                <td className="py-2 pr-3 text-xs" style={{ color: 'var(--text-dim)' }}>
                  {s.replay_mode}{s.replay_mode === 'wallet_constrained' ? ` / ${s.funding_mode}` : ''}
                </td>
                <td className="py-2 pr-3 text-xs">{s.event_count ?? '—'}</td>
                <td className="py-2 pr-3"><StatusPill status={s.state} /></td>
                <td className="py-2 text-right">
                  <span className="flex items-center gap-2 justify-end" onClick={e => e.stopPropagation()}>
                    {s.state === 'succeeded' && (
                      <>
                        <a href={`${API}/simulations/${s.id}/csv`} title="Download per-account CSV"
                          className="hover:opacity-80"><Download size={14} style={{ color: 'var(--moon)' }} /></a>
                        <button onClick={() => act(s.id, 'rerun')} title="Rerun stored manifest"
                          className="hover:opacity-80"><Repeat size={14} style={{ color: 'var(--text-dim)' }} /></button>
                      </>
                    )}
                    {(s.state === 'pending' || s.state === 'running') && (
                      <button onClick={() => act(s.id, 'cancel')} title="Cancel"
                        className="hover:opacity-80"><XCircle size={14} style={{ color: '#ff6b6b' }} /></button>
                    )}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected && <Detail sim={selected} vLabel={vLabel} onClose={() => setSelected(null)} />}
    </div>
  );
}

function CreateForm({ versions, onCreated, onError }: {
  versions: PricingVersion[];
  onCreated: () => Promise<void>;
  onError: (e: string | null) => void;
}) {
  const published = versions.find(v => v.status === 'published');
  const [baseline, setBaseline] = useState('');
  const [candidate, setCandidate] = useState('');
  const [replayMode, setReplayMode] = useState('full_demand');
  const [fundingMode, setFundingMode] = useState('actual_grants');
  const [filtersText, setFiltersText] = useState('');
  const [transformsText, setTransformsText] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (published && !baseline) setBaseline(published.id);
    if (published && !candidate) setCandidate(published.id);
  }, [published, baseline, candidate]);

  const submit = async () => {
    onError(null);
    let filters: unknown = null, transforms: unknown = null;
    try {
      filters = filtersText.trim() ? JSON.parse(filtersText) : null;
      transforms = transformsText.trim() ? JSON.parse(transformsText) : null;
    } catch {
      onError('Filters/transforms must be valid JSON.');
      return;
    }
    setBusy(true);
    const res = await fetch(`${API}/simulations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        baseline_version_id: baseline,
        candidate_version_id: candidate,
        replay_mode: replayMode,
        funding_mode: fundingMode,
        filters, transforms,
      }),
    });
    if (!res.ok) onError(await apiError(res));
    else await onCreated();
    setBusy(false);
  };

  const inputStyle = {
    background: 'var(--ink)', borderColor: 'var(--ink-lighter)', color: 'var(--text)',
  } as const;

  return (
    <div className="rounded-xl border p-5 mb-8" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
      <div className="text-xs font-semibold uppercase tracking-wide mb-3" style={{ color: 'var(--text-dim)' }}>
        New simulation
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
        <label className="text-xs" style={{ color: 'var(--text-dim)' }}>
          Baseline version
          <select value={baseline} onChange={e => setBaseline(e.target.value)}
            className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={inputStyle}>
            {versions.map(v => (
              <option key={v.id} value={v.id}>
                v{v.version_number}{v.name ? ` — ${v.name}` : ''} ({v.status})
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs" style={{ color: 'var(--text-dim)' }}>
          Candidate version
          <select value={candidate} onChange={e => setCandidate(e.target.value)}
            className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={inputStyle}>
            {versions.map(v => (
              <option key={v.id} value={v.id}>
                v{v.version_number}{v.name ? ` — ${v.name}` : ''} ({v.status})
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs" style={{ color: 'var(--text-dim)' }}>
          Replay mode
          <select value={replayMode} onChange={e => setReplayMode(e.target.value)}
            className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={inputStyle}>
            <option value="full_demand">full_demand — rate every call</option>
            <option value="wallet_constrained">wallet_constrained — block at zero balance</option>
          </select>
        </label>
        <label className="text-xs" style={{ color: 'var(--text-dim)' }}>
          Funding mode (wallet replay only)
          <select value={fundingMode} onChange={e => setFundingMode(e.target.value)}
            disabled={replayMode !== 'wallet_constrained'}
            className="mt-1 w-full rounded-lg border px-3 py-2 text-sm disabled:opacity-50" style={inputStyle}>
            <option value="actual_grants">actual_grants — lots as they were</option>
            <option value="candidate_products">candidate_products — payments remapped to candidate products</option>
          </select>
        </label>
        <label className="text-xs" style={{ color: 'var(--text-dim)' }}>
          Filters (JSON, optional)
          <textarea value={filtersText} onChange={e => setFiltersText(e.target.value)}
            placeholder='{"period_start": "2026-06-01T00:00:00Z", "account_ids": ["…"]}'
            rows={2} className="mt-1 w-full rounded-lg border px-3 py-2 text-xs font-mono" style={inputStyle} />
        </label>
        <label className="text-xs" style={{ color: 'var(--text-dim)' }}>
          Transforms (JSON, optional)
          <textarea value={transformsText} onChange={e => setTransformsText(e.target.value)}
            placeholder='{"cost_multiplier": "0.5", "volume_multiplier": "1.5"}'
            rows={2} className="mt-1 w-full rounded-lg border px-3 py-2 text-xs font-mono" style={inputStyle} />
        </label>
      </div>
      <button onClick={submit} disabled={busy || !baseline || !candidate}
        className="px-4 py-2 rounded-lg text-sm font-medium transition-colors hover:opacity-90 disabled:opacity-50"
        style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
        {busy ? 'Creating…' : 'Run simulation'}
      </button>
    </div>
  );
}

function Detail({ sim, vLabel, onClose }: {
  sim: SimDetail;
  vLabel: (id: string | null) => string;
  onClose: () => void;
}) {
  const r = sim.result;
  return (
    <div className="rounded-xl border p-5 mb-8" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
            {vLabel(sim.baseline_version_id)} → {vLabel(sim.candidate_version_id)}
          </span>
          <StatusPill status={sim.state} />
        </div>
        <button onClick={onClose} className="text-xs hover:opacity-80" style={{ color: 'var(--text-dim)' }}>close</button>
      </div>

      {sim.state === 'failed' && r?.error && (
        <div className="rounded-xl px-4 py-3 text-sm mb-3"
          style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>{r.error}</div>
      )}
      {!r && sim.state !== 'failed' && (
        <p className="text-sm" style={{ color: 'var(--text-dim)' }}>
          {sim.state === 'cancelled' ? 'Cancelled — no result was published.' : 'Result pending — the billing worker runs it.'}
        </p>
      )}

      {r && !r.error && (
        <>
          <div className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>
            {r.logical_calls} calls · {r.accounts} accounts · {r.event_count} events
            {r.missing_events > 0 && <span style={{ color: '#ffc864' }}> · {r.missing_events} missing since manifest</span>}
            {' · '}hash <span className="font-mono">{r.result_hash.slice(0, 12)}</span>
          </div>
          <table className="w-full text-sm mb-4">
            <thead>
              <tr style={{ color: 'var(--text-dim)' }} className="text-left text-xs">
                <th className="pb-2 font-medium">Metric</th>
                <th className="pb-2 font-medium text-right">Baseline</th>
                <th className="pb-2 font-medium text-right">Candidate</th>
                <th className="pb-2 font-medium text-right">Δ</th>
              </tr>
            </thead>
            <tbody style={{ color: 'var(--text)' }}>
              <Row label="Credits" b={r.baseline.credits.toLocaleString()} c={r.candidate.credits.toLocaleString()}
                d={r.delta.credits} />
              <Row label={`Face value (${r.labels.face_value})`} b={usd(r.baseline.face_value_micro_usd)}
                c={usd(r.candidate.face_value_micro_usd)} d={null} />
              <Row label={`Cash basis (${r.labels.cash_basis})`} b={usd(r.baseline.cash_basis_micro_usd)}
                c={usd(r.candidate.cash_basis_micro_usd)} d={null} />
              <Row label="Vendor cost" b={usd(r.baseline.vendor_micro_usd)} c={usd(r.candidate.vendor_micro_usd)} d={null} />
              <Row label="Luna absorbed" b={usd(r.baseline.luna_absorbed_micro_usd)}
                c={usd(r.candidate.luna_absorbed_micro_usd)} d={null} />
              <Row label="Gross profit (face)" b={usd(r.baseline.gross_profit_face_micro_usd)}
                c={usd(r.candidate.gross_profit_face_micro_usd)} d={null} />
              <Row label="Hosting credits" b={r.baseline.hosting_credits.toLocaleString()}
                c={r.candidate.hosting_credits.toLocaleString()} d={r.delta.hosting_credits} />
              <Row label="Rated / unpriced calls" b={`${r.baseline.rated_calls} / ${r.baseline.unpriced_calls}`}
                c={`${r.candidate.rated_calls} / ${r.candidate.unpriced_calls}`} d={null} />
              <Row label="Blocked calls (credits)" b={`${r.baseline.blocked_calls} (${r.baseline.blocked_credits})`}
                c={`${r.candidate.blocked_calls} (${r.candidate.blocked_credits})`} d={r.delta.blocked_credits} />
              <Row label="Accounts hit zero / in debt"
                b={`${r.baseline.accounts_hit_zero ?? '—'} / ${r.baseline.accounts_in_debt ?? '—'}`}
                c={`${r.candidate.accounts_hit_zero ?? '—'} / ${r.candidate.accounts_in_debt ?? '—'}`} d={null} />
            </tbody>
          </table>

          {r.unrated_dimensions.length > 0 && (
            <div className="text-xs mb-4" style={{ color: '#ffc864' }}>
              Unrated dimensions: {r.unrated_dimensions.join(', ')}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <AccountList title="Winners (pay less)" rows={r.winners.filter(a => a.candidate_credits < a.baseline_credits)} />
            <AccountList title="Losers (pay more)" rows={r.losers.filter(a => a.candidate_credits > a.baseline_credits)} />
          </div>
        </>
      )}
    </div>
  );
}

function Row({ label, b, c, d }: { label: string; b: string; c: string; d: number | null | undefined }) {
  return (
    <tr className="border-t" style={{ borderColor: 'var(--ink-lighter)' }}>
      <td className="py-1.5 pr-3 text-xs" style={{ color: 'var(--text-dim)' }}>{label}</td>
      <td className="py-1.5 pr-3 text-right font-mono text-xs">{b}</td>
      <td className="py-1.5 pr-3 text-right font-mono text-xs">{c}</td>
      <td className="py-1.5 text-right font-mono text-xs"
        style={{ color: d == null ? 'var(--text-dim)' : d > 0 ? '#ffc864' : d < 0 ? '#78dca0' : 'var(--text-dim)' }}>
        {d == null ? '' : d > 0 ? `+${d.toLocaleString()}` : d.toLocaleString()}
      </td>
    </tr>
  );
}

function AccountList({ title, rows }: { title: string; rows: PerAccount[] }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-dim)' }}>{title}</div>
      {rows.length === 0 ? (
        <p className="text-xs" style={{ color: 'var(--text-dim)' }}>none</p>
      ) : (
        <ul className="text-xs font-mono space-y-1" style={{ color: 'var(--text)' }}>
          {rows.map(a => (
            <li key={a.account_id}>
              {a.account_id.slice(0, 8)}… {a.baseline_credits} → {a.candidate_credits}
              {' '}({a.candidate_credits - a.baseline_credits > 0 ? '+' : ''}{a.candidate_credits - a.baseline_credits})
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
