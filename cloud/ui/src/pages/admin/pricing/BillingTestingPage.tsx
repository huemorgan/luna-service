// 040 — cost benchmark: run the playbook against a flagged test agent,
// see per-item credit/$ costs, the full trigger log, and monthly projections.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Gauge, Loader2, RefreshCw, Download, XCircle, Target } from 'lucide-react';
import { API, StatusPill, apiError } from './api';

interface AgentLight { id: string; slug: string; name: string | null }

interface PlaybookItem {
  key: string; title: string; category: string; kind: string;
  smoke: boolean; default_included: boolean; plugins: string[];
  notes: string | null; window_seconds: number;
}

interface Playbook {
  playbook_version: string;
  items: PlaybookItem[];
  smoke_keys: string[];
  default_keys: string[];
  uncovered_plugins: string[];
  presets: Record<string, Record<string, number>>;
}

interface RunSummary {
  id: string; agent_id: string; agent_slug: string | null;
  playbook_version: string; item_keys: string[]; repetitions: number;
  state: string; progress: Record<string, unknown> | null;
  totals: Record<string, number> | null; error: string | null;
  started_at: string | null; finished_at: string | null; created_at: string | null;
}

interface Step {
  id: string; seq: number; item_key: string; repetition: number; status: string;
  latency_ms: number | null; llm_requests: number;
  input_tokens: number; output_tokens: number;
  cache_read_tokens: number; cache_write_tokens: number;
  per_model: Record<string, Record<string, number>> | null;
  credits: number; vendor_cost_micro_usd: number; margin_micro_usd: number;
  error: string | null;
}

interface ActionAvg {
  item_key: string; samples: number; failed: number;
  avg_credits: number; median_credits: number; avg_vendor_cost_micro_usd: number;
  avg_llm_requests: number; avg_input_tokens: number; avg_output_tokens: number;
  avg_cache_read_tokens: number; avg_cache_write_tokens: number;
  avg_latency_ms: number;
}

interface RunDetail extends RunSummary {
  steps: Step[];
  medians: Record<string, { credits: number; vendor_cost_micro_usd: number; samples: number }>;
  averages: ActionAvg[];
}

interface TrigEvent {
  id: string; step_id: string; ts: string | null; call_id: string | null;
  service: string; sku: string | null; provider: string | null; model: string | null;
  attempt_number: number; quantities: Record<string, number> | null;
  vendor_cost_micro_usd: number; credits: number; cost_source: string | null;
}

interface Projection {
  per_item: Array<{ item_key: string; freq: number; unit_credits: number;
    credits: number; vendor_cost_micro_usd: number; note?: string }>;
  missing_items: string[];
  metered_credits: number; hosting_credits: number; monthly_credits: number;
  monthly_revenue_micro_usd: number; monthly_vendor_micro_usd: number;
  monthly_margin_micro_usd: number;
  background_daily: { credits: number; vendor_cost_micro_usd: number };
}

const usd = (micro: number | null | undefined) =>
  micro == null ? '—' : `$${(micro / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 3 })}`;

export default function BillingTestingPage() {
  const [playbook, setPlaybook] = useState<Playbook | null>(null);
  const [targets, setTargets] = useState<AgentLight[]>([]);
  const [agents, setAgents] = useState<AgentLight[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    const [t, r] = await Promise.all([
      fetch(`${API}/benchmark/targets`),
      fetch(`${API}/benchmark/runs`),
    ]);
    if (t.ok) setTargets((await t.json()).targets);
    if (r.ok) setRuns((await r.json()).runs);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    fetch(`${API}/benchmark/playbook`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(setPlaybook).catch(() => setPlaybook(null));
    fetch('/api/admin/gateway/agents-light')
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(setAgents).catch(() => setAgents([]));
  }, [load]);

  // Poll while a run is live — the billing worker executes it.
  useEffect(() => {
    const active = runs.some(r => r.state === 'pending' || r.state === 'running');
    if (active && pollRef.current == null) {
      pollRef.current = window.setInterval(async () => {
        await load();
        if (selected) {
          const res = await fetch(`${API}/benchmark/runs/${selected.id}`);
          if (res.ok) setSelected(await res.json());
        }
      }, 4000);
    } else if (!active && pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current != null) { window.clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [runs, selected, load]);

  const open = async (id: string) => {
    setError(null);
    const res = await fetch(`${API}/benchmark/runs/${id}`);
    if (res.ok) setSelected(await res.json());
    else setError(await apiError(res));
  };

  const abort = async (id: string) => {
    const res = await fetch(`${API}/benchmark/runs/${id}/abort`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    if (!res.ok) setError(await apiError(res));
    await load();
    if (selected?.id === id) await open(id);
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
          <Gauge size={20} style={{ color: 'var(--moon)' }} />
          Billing testing
        </h2>
        <button onClick={() => { setLoading(true); load(); }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors hover:opacity-80"
          style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text-dim)' }}>
          <RefreshCw size={12} /> Refresh
        </button>
      </div>
      <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>
        Live-fire cost benchmark: drives a flagged test agent through the usage playbook
        and attributes every billable event to the action that triggered it. Runs spend
        the target's wallet for real — flag dedicated test agents only.
      </p>

      {error && (
        <div className="rounded-xl px-4 py-3 text-sm mb-4"
          style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>{error}</div>
      )}
      {playbook && playbook.uncovered_plugins.length > 0 && (
        <div className="rounded-xl px-4 py-3 text-xs mb-4"
          style={{ background: 'rgba(255,200,100,0.12)', color: '#ffc864' }}>
          Plugins without playbook coverage: {playbook.uncovered_plugins.join(', ')}
        </div>
      )}

      <TargetsCard agents={agents} targets={targets} onChanged={load} onError={setError} />
      {playbook && (
        <RunForm playbook={playbook} targets={targets} onCreated={load} onError={setError} />
      )}

      <h3 className="text-sm font-semibold uppercase tracking-wide mb-3" style={{ color: 'var(--text-dim)' }}>Runs</h3>
      {runs.length === 0 ? (
        <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>No benchmark runs yet.</p>
      ) : (
        <table className="w-full text-sm mb-8">
          <thead>
            <tr style={{ color: 'var(--text-dim)' }} className="text-left text-xs">
              <th className="pb-2 font-medium">Created</th>
              <th className="pb-2 font-medium">Agent</th>
              <th className="pb-2 font-medium">Items × reps</th>
              <th className="pb-2 font-medium">Progress</th>
              <th className="pb-2 font-medium text-right">Credits</th>
              <th className="pb-2 font-medium text-right">Vendor $</th>
              <th className="pb-2 font-medium">State</th>
              <th className="pb-2 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {runs.map(r => (
              <tr key={r.id} className="border-t cursor-pointer hover:opacity-80"
                style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)' }}
                onClick={() => open(r.id)}>
                <td className="py-2 pr-3 text-xs" style={{ color: 'var(--text-dim)' }}>
                  {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
                </td>
                <td className="py-2 pr-3 text-xs font-mono">{r.agent_slug ?? r.agent_id.slice(0, 8)}</td>
                <td className="py-2 pr-3 text-xs">{r.item_keys.length} × {r.repetitions}</td>
                <td className="py-2 pr-3 text-xs" style={{ color: 'var(--text-dim)' }}>
                  {r.state === 'running' && r.progress
                    ? `${r.progress.step}/${r.progress.total_steps} · ${r.progress.item}`
                    : '—'}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-xs">
                  {r.totals ? r.totals.credits.toLocaleString() : '—'}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-xs">
                  {r.totals ? usd(r.totals.vendor_cost_micro_usd) : '—'}
                </td>
                <td className="py-2 pr-3"><StatusPill status={r.state} /></td>
                <td className="py-2 text-right">
                  <span className="flex items-center gap-2 justify-end" onClick={e => e.stopPropagation()}>
                    {(r.state === 'succeeded' || r.state === 'failed') && (
                      <a href={`${API}/benchmark/runs/${r.id}/export`} title="Export full trigger log (JSON)"
                        className="hover:opacity-80"><Download size={14} style={{ color: 'var(--moon)' }} /></a>
                    )}
                    {(r.state === 'pending' || r.state === 'running') && (
                      <button onClick={() => abort(r.id)} title="Abort"
                        className="hover:opacity-80"><XCircle size={14} style={{ color: '#ff6b6b' }} /></button>
                    )}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected && playbook && (
        <RunDetailCard run={selected} playbook={playbook} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function TargetsCard({ agents, targets, onChanged, onError }: {
  agents: AgentLight[];
  targets: AgentLight[];
  onChanged: () => Promise<void>;
  onError: (e: string | null) => void;
}) {
  const [agentId, setAgentId] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const targetIds = new Set(targets.map(t => t.id));

  const setFlag = async (id: string, target: boolean, why: string) => {
    onError(null);
    setBusy(true);
    const res = await fetch(`${API}/benchmark/targets/${id}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target, reason: why }),
    });
    if (!res.ok) onError(await apiError(res));
    else { setReason(''); await onChanged(); }
    setBusy(false);
  };

  const inputStyle = {
    background: 'var(--ink)', borderColor: 'var(--ink-lighter)', color: 'var(--text)',
  } as const;

  return (
    <div className="rounded-xl border p-5 mb-6" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
      <div className="text-xs font-semibold uppercase tracking-wide mb-3 flex items-center gap-1.5"
        style={{ color: 'var(--text-dim)' }}>
        <Target size={12} /> Benchmark targets
      </div>
      {targets.length === 0 ? (
        <p className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>
          No agents flagged. A run refuses any agent not flagged here.
        </p>
      ) : (
        <ul className="text-xs font-mono space-y-1 mb-3" style={{ color: 'var(--text)' }}>
          {targets.map(t => (
            <li key={t.id} className="flex items-center gap-2">
              {t.slug}
              <button onClick={() => setFlag(t.id, false, 'unflagged from admin UI')}
                disabled={busy} className="hover:opacity-80 text-xs" style={{ color: '#ff6b6b' }}>
                unflag
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs" style={{ color: 'var(--text-dim)' }}>
          Agent
          <select value={agentId} onChange={e => setAgentId(e.target.value)}
            className="mt-1 block rounded-lg border px-3 py-2 text-sm" style={inputStyle}>
            <option value="">— pick an agent —</option>
            {agents.filter(a => !targetIds.has(a.id)).map(a => (
              <option key={a.id} value={a.id}>{a.slug}{a.name ? ` — ${a.name}` : ''}</option>
            ))}
          </select>
        </label>
        <label className="text-xs flex-1 min-w-48" style={{ color: 'var(--text-dim)' }}>
          Reason
          <input value={reason} onChange={e => setReason(e.target.value)}
            placeholder="why this agent is a safe test target"
            className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={inputStyle} />
        </label>
        <button onClick={() => setFlag(agentId, true, reason)}
          disabled={busy || !agentId || !reason.trim()}
          className="px-4 py-2 rounded-lg text-sm font-medium transition-colors hover:opacity-90 disabled:opacity-50"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
          Flag as target
        </button>
      </div>
    </div>
  );
}

function RunForm({ playbook, targets, onCreated, onError }: {
  playbook: Playbook;
  targets: AgentLight[];
  onCreated: () => Promise<void>;
  onError: (e: string | null) => void;
}) {
  const [agentId, setAgentId] = useState('');
  const [mode, setMode] = useState<'smoke' | 'default' | 'custom'>('smoke');
  const [keys, setKeys] = useState<Set<string>>(new Set(playbook.smoke_keys));
  const [repetitions, setRepetitions] = useState(3);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (targets.length === 1) setAgentId(targets[0].id);
  }, [targets]);

  useEffect(() => {
    if (mode === 'smoke') setKeys(new Set(playbook.smoke_keys));
    if (mode === 'default') setKeys(new Set(playbook.default_keys));
  }, [mode, playbook]);

  const toggle = (key: string) => {
    setMode('custom');
    setKeys(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const submit = async () => {
    onError(null);
    setBusy(true);
    const res = await fetch(`${API}/benchmark/runs`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_id: agentId, item_keys: [...keys], repetitions, reason,
      }),
    });
    if (!res.ok) onError(await apiError(res));
    else { setReason(''); await onCreated(); }
    setBusy(false);
  };

  const categories = [...new Set(playbook.items.map(i => i.category))];
  const inputStyle = {
    background: 'var(--ink)', borderColor: 'var(--ink-lighter)', color: 'var(--text)',
  } as const;

  return (
    <div className="rounded-xl border p-5 mb-8" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
      <div className="text-xs font-semibold uppercase tracking-wide mb-3" style={{ color: 'var(--text-dim)' }}>
        New run · playbook {playbook.playbook_version}
      </div>
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <label className="text-xs" style={{ color: 'var(--text-dim)' }}>
          Target agent
          <select value={agentId} onChange={e => setAgentId(e.target.value)}
            className="mt-1 block rounded-lg border px-3 py-2 text-sm" style={inputStyle}>
            <option value="">— pick a target —</option>
            {targets.map(t => <option key={t.id} value={t.id}>{t.slug}</option>)}
          </select>
        </label>
        <label className="text-xs" style={{ color: 'var(--text-dim)' }}>
          Item set
          <select value={mode} onChange={e => setMode(e.target.value as typeof mode)}
            className="mt-1 block rounded-lg border px-3 py-2 text-sm" style={inputStyle}>
            <option value="smoke">smoke — cheap subset</option>
            <option value="default">default — full catalog</option>
            <option value="custom">custom</option>
          </select>
        </label>
        <label className="text-xs" style={{ color: 'var(--text-dim)' }}>
          Repetitions
          <input type="number" min={1} max={10} value={repetitions}
            onChange={e => setRepetitions(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
            className="mt-1 block w-20 rounded-lg border px-3 py-2 text-sm" style={inputStyle} />
        </label>
        <label className="text-xs flex-1 min-w-48" style={{ color: 'var(--text-dim)' }}>
          Reason
          <input value={reason} onChange={e => setReason(e.target.value)}
            placeholder="required — this spends the target's wallet"
            className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={inputStyle} />
        </label>
        <button onClick={submit} disabled={busy || !agentId || !reason.trim() || keys.size === 0}
          className="px-4 py-2 rounded-lg text-sm font-medium transition-colors hover:opacity-90 disabled:opacity-50"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
          {busy ? 'Starting…' : `Run ${keys.size} item${keys.size === 1 ? '' : 's'}`}
        </button>
      </div>
      <div className="space-y-2">
        {categories.map(cat => (
          <div key={cat}>
            <div className="text-xs font-medium mb-1" style={{ color: 'var(--text-dim)' }}>{cat}</div>
            <div className="flex flex-wrap gap-1.5">
              {playbook.items.filter(i => i.category === cat).map(i => (
                <button key={i.key} onClick={() => toggle(i.key)}
                  title={`${i.title}${i.notes ? ` — ${i.notes}` : ''} (${i.plugins.join(', ')})`}
                  className="px-2 py-1 rounded-md text-xs font-mono border transition-colors"
                  style={{
                    borderColor: keys.has(i.key) ? 'var(--moon)' : 'var(--ink-lighter)',
                    color: keys.has(i.key) ? 'var(--moon)' : 'var(--text-dim)',
                    background: keys.has(i.key) ? 'rgba(255,255,255,0.04)' : 'transparent',
                  }}>
                  {i.key}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RunDetailCard({ run, playbook, onClose }: {
  run: RunDetail;
  playbook: Playbook;
  onClose: () => void;
}) {
  const [events, setEvents] = useState<TrigEvent[] | null>(null);
  const [eventStep, setEventStep] = useState<string>('');
  const [showSteps, setShowSteps] = useState(false);
  const titles = Object.fromEntries(playbook.items.map(i => [i.key, i.title]));

  const loadEvents = async (stepId: string) => {
    setEventStep(stepId);
    const q = stepId ? `?step_id=${stepId}` : '';
    const res = await fetch(`${API}/benchmark/runs/${run.id}/events${q}`);
    if (res.ok) setEvents((await res.json()).events);
  };

  const t = run.totals;
  return (
    <div className="rounded-xl border p-5 mb-8" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold font-mono" style={{ color: 'var(--text)' }}>
            {run.agent_slug ?? run.agent_id.slice(0, 8)}
          </span>
          <StatusPill status={run.state} />
          <a href={`${API}/benchmark/runs/${run.id}/export`}
            className="text-xs hover:opacity-80 flex items-center gap-1" style={{ color: 'var(--moon)' }}>
            <Download size={12} /> export
          </a>
        </div>
        <button onClick={onClose} className="text-xs hover:opacity-80" style={{ color: 'var(--text-dim)' }}>close</button>
      </div>

      {run.error && (
        <div className="rounded-xl px-4 py-3 text-sm mb-3"
          style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>{run.error}</div>
      )}

      {t && (
        <div className="text-xs mb-4" style={{ color: 'var(--text-dim)' }}>
          {t.steps} steps ({t.failed_steps} failed) · {t.llm_requests} LLM requests ·{' '}
          {t.input_tokens.toLocaleString()} in / {t.output_tokens.toLocaleString()} out tokens ·{' '}
          <span style={{ color: 'var(--text)' }}>{t.credits.toLocaleString()} credits</span> ·{' '}
          vendor {usd(t.vendor_cost_micro_usd)} · background {t.background_credits} cr
        </div>
      )}

      {run.averages && run.averages.length > 0 && (
        <div className="mb-4">
          <div className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-dim)' }}>
            Action averages · per repetition, over {run.repetitions} rep{run.repetitions === 1 ? '' : 's'}
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr style={{ color: 'var(--text-dim)' }} className="text-left">
                <th className="pb-2 font-medium">Action</th>
                <th className="pb-2 font-medium text-right">Samples</th>
                <th className="pb-2 font-medium text-right">Avg credits</th>
                <th className="pb-2 font-medium text-right">Median</th>
                <th className="pb-2 font-medium text-right">Avg vendor $</th>
                <th className="pb-2 font-medium text-right">Avg LLM calls</th>
                <th className="pb-2 font-medium text-right">Avg tokens in/out</th>
                <th className="pb-2 font-medium text-right">Avg latency</th>
              </tr>
            </thead>
            <tbody style={{ color: 'var(--text)' }}>
              {run.averages.map(a => (
                <tr key={a.item_key} className="border-t" style={{ borderColor: 'var(--ink-lighter)' }}>
                  <td className="py-1.5 pr-2">
                    <span className="font-mono">{a.item_key}</span>
                    <span className="ml-2" style={{ color: 'var(--text-dim)' }}>{titles[a.item_key] ?? ''}</span>
                    {a.failed > 0 && (
                      <span className="ml-2" style={{ color: '#ff6b6b' }}>{a.failed} failed</span>
                    )}
                  </td>
                  <td className="py-1.5 pr-2 text-right font-mono">{a.samples}</td>
                  <td className="py-1.5 pr-2 text-right font-mono font-semibold">
                    {a.avg_credits.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                  </td>
                  <td className="py-1.5 pr-2 text-right font-mono" style={{ color: 'var(--text-dim)' }}>
                    {a.median_credits.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                  </td>
                  <td className="py-1.5 pr-2 text-right font-mono">{usd(a.avg_vendor_cost_micro_usd)}</td>
                  <td className="py-1.5 pr-2 text-right font-mono">
                    {a.avg_llm_requests.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                  </td>
                  <td className="py-1.5 pr-2 text-right font-mono">
                    {Math.round(a.avg_input_tokens).toLocaleString()}/{Math.round(a.avg_output_tokens).toLocaleString()}
                  </td>
                  <td className="py-1.5 text-right font-mono">{(a.avg_latency_ms / 1000).toFixed(1)}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <button onClick={() => setShowSteps(s => !s)}
        className="text-xs font-semibold uppercase tracking-wide mb-2 hover:opacity-80 block"
        style={{ color: 'var(--text-dim)' }}>
        {showSteps ? '▾' : '▸'} Individual steps · {run.steps.length}
      </button>
      {showSteps && (
      <table className="w-full text-sm mb-4">
        <thead>
          <tr style={{ color: 'var(--text-dim)' }} className="text-left text-xs">
            <th className="pb-2 font-medium">#</th>
            <th className="pb-2 font-medium">Item</th>
            <th className="pb-2 font-medium">Rep</th>
            <th className="pb-2 font-medium">Status</th>
            <th className="pb-2 font-medium text-right">Latency</th>
            <th className="pb-2 font-medium text-right">Reqs</th>
            <th className="pb-2 font-medium text-right">Tokens in/out</th>
            <th className="pb-2 font-medium text-right">Credits</th>
            <th className="pb-2 font-medium text-right">Vendor $</th>
            <th className="pb-2 font-medium"></th>
          </tr>
        </thead>
        <tbody style={{ color: 'var(--text)' }}>
          {run.steps.map(s => (
            <tr key={s.id} className="border-t" style={{ borderColor: 'var(--ink-lighter)' }}>
              <td className="py-1.5 pr-2 text-xs" style={{ color: 'var(--text-dim)' }}>{s.seq}</td>
              <td className="py-1.5 pr-2 text-xs font-mono" title={s.error ?? undefined}>{s.item_key}</td>
              <td className="py-1.5 pr-2 text-xs">{s.repetition}</td>
              <td className="py-1.5 pr-2"><StatusPill status={s.status} /></td>
              <td className="py-1.5 pr-2 text-right font-mono text-xs">
                {s.latency_ms != null ? `${(s.latency_ms / 1000).toFixed(1)}s` : '—'}
              </td>
              <td className="py-1.5 pr-2 text-right font-mono text-xs">{s.llm_requests}</td>
              <td className="py-1.5 pr-2 text-right font-mono text-xs">
                {s.input_tokens.toLocaleString()}/{s.output_tokens.toLocaleString()}
              </td>
              <td className="py-1.5 pr-2 text-right font-mono text-xs">{s.credits.toLocaleString()}</td>
              <td className="py-1.5 pr-2 text-right font-mono text-xs">{usd(s.vendor_cost_micro_usd)}</td>
              <td className="py-1.5 text-right">
                <button onClick={() => loadEvents(s.id)} className="text-xs hover:opacity-80"
                  style={{ color: 'var(--moon)' }}>log</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      )}

      {!events && (
        <button onClick={() => loadEvents('')} className="text-xs hover:opacity-80 mb-4 block"
          style={{ color: 'var(--moon)' }}>
          show trigger log — everything that fired, verbatim quantities
        </button>
      )}

      {events && (
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-dim)' }}>
              Trigger log {eventStep ? '(step)' : '(run)'} · {events.length} events
            </div>
            <div className="flex gap-3">
              <button onClick={() => loadEvents('')} className="text-xs hover:opacity-80" style={{ color: 'var(--moon)' }}>
                whole run
              </button>
              <button onClick={() => setEvents(null)} className="text-xs hover:opacity-80" style={{ color: 'var(--text-dim)' }}>
                hide
              </button>
            </div>
          </div>
          <div className="overflow-x-auto rounded-lg border" style={{ borderColor: 'var(--ink-lighter)' }}>
            <table className="w-full text-xs">
              <thead>
                <tr style={{ color: 'var(--text-dim)' }} className="text-left">
                  <th className="p-2 font-medium">ts</th>
                  <th className="p-2 font-medium">model / service</th>
                  <th className="p-2 font-medium">attempt</th>
                  <th className="p-2 font-medium">quantities</th>
                  <th className="p-2 font-medium text-right">vendor $</th>
                  <th className="p-2 font-medium text-right">credits</th>
                </tr>
              </thead>
              <tbody style={{ color: 'var(--text)' }}>
                {events.map(e => (
                  <tr key={e.id} className="border-t" style={{ borderColor: 'var(--ink-lighter)' }}>
                    <td className="p-2 font-mono" style={{ color: 'var(--text-dim)' }}>
                      {e.ts ? new Date(e.ts).toLocaleTimeString() : '—'}
                    </td>
                    <td className="p-2 font-mono">{e.model ?? e.service}</td>
                    <td className="p-2">{e.attempt_number}</td>
                    <td className="p-2 font-mono" style={{ color: 'var(--text-dim)' }}>
                      {e.quantities ? Object.entries(e.quantities).map(([k, v]) => `${k}=${v}`).join(' ') : '—'}
                    </td>
                    <td className="p-2 text-right font-mono">{usd(e.vendor_cost_micro_usd)}</td>
                    <td className="p-2 text-right font-mono">{e.credits || ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <ProjectionPanel runId={run.id} presets={playbook.presets} />
    </div>
  );
}

function ProjectionPanel({ runId, presets }: { runId: string; presets: Record<string, Record<string, number>> }) {
  const [preset, setPreset] = useState('regular');
  const [hosting, setHosting] = useState(999);
  const [proj, setProj] = useState<Projection | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setErr(null);
    const res = await fetch(`${API}/benchmark/projection`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_id: runId, preset, hosting_credits: hosting }),
    });
    if (res.ok) setProj(await res.json());
    else setErr(await apiError(res));
  };

  const inputStyle = {
    background: 'var(--ink)', borderColor: 'var(--ink-lighter)', color: 'var(--text)',
  } as const;

  return (
    <div className="border-t pt-4" style={{ borderColor: 'var(--ink-lighter)' }}>
      <div className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-dim)' }}>
        Monthly projection
      </div>
      <div className="flex items-end gap-3 mb-3">
        <label className="text-xs" style={{ color: 'var(--text-dim)' }}>
          Usage profile
          <select value={preset} onChange={e => setPreset(e.target.value)}
            className="mt-1 block rounded-lg border px-3 py-2 text-sm" style={inputStyle}>
            {Object.keys(presets).map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <label className="text-xs" style={{ color: 'var(--text-dim)' }}>
          Hosting credits / month
          <input type="number" min={0} value={hosting}
            onChange={e => setHosting(Math.max(0, Number(e.target.value) || 0))}
            className="mt-1 block w-28 rounded-lg border px-3 py-2 text-sm" style={inputStyle} />
        </label>
        <button onClick={run}
          className="px-4 py-2 rounded-lg text-sm font-medium transition-colors hover:opacity-90"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
          Project
        </button>
      </div>
      {err && <div className="text-xs mb-2" style={{ color: '#ff6b6b' }}>{err}</div>}
      {proj && (
        <>
          <div className="text-sm mb-2" style={{ color: 'var(--text)' }}>
            <span className="font-semibold">{Math.round(proj.monthly_credits).toLocaleString()} credits/month</span>
            {' '}({usd(proj.monthly_revenue_micro_usd)} revenue · vendor {usd(proj.monthly_vendor_micro_usd)}
            {' '}· margin {usd(proj.monthly_margin_micro_usd)}) — metered{' '}
            {Math.round(proj.metered_credits).toLocaleString()} + hosting {proj.hosting_credits}
          </div>
          {proj.missing_items.length > 0 && (
            <div className="text-xs mb-2" style={{ color: '#ffc864' }}>
              Not measured in this run: {proj.missing_items.join(', ')}
            </div>
          )}
          <table className="w-full text-xs mb-2">
            <thead>
              <tr style={{ color: 'var(--text-dim)' }} className="text-left">
                <th className="pb-1 font-medium">Item</th>
                <th className="pb-1 font-medium text-right">Freq / month</th>
                <th className="pb-1 font-medium text-right">Unit credits</th>
                <th className="pb-1 font-medium text-right">Credits</th>
                <th className="pb-1 font-medium text-right">Vendor $</th>
              </tr>
            </thead>
            <tbody style={{ color: 'var(--text)' }}>
              {proj.per_item.map(row => (
                <tr key={row.item_key} className="border-t" style={{ borderColor: 'var(--ink-lighter)' }}>
                  <td className="py-1 pr-2 font-mono" title={row.note}>{row.item_key}</td>
                  <td className="py-1 pr-2 text-right font-mono">{row.freq}</td>
                  <td className="py-1 pr-2 text-right font-mono">{row.unit_credits.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                  <td className="py-1 pr-2 text-right font-mono">{Math.round(row.credits).toLocaleString()}</td>
                  <td className="py-1 text-right font-mono">{usd(row.vendor_cost_micro_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
