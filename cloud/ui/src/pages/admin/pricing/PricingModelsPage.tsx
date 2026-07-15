import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Cpu, Loader2, AlertTriangle, Plus, Save } from 'lucide-react';
import { API, StatusPill, apiError } from './api';
import type { ProviderCostVersionOut } from './api';
import { useTargetVersion } from './useTargetVersion';

/** LLM & services — tier lists, per-context LLM constants, SKU catalog,
 *  hosting price, and provider-cost versions. Internal-only economics:
 *  nothing here is ever exposed to customers or the Luna agent. */
export default function PricingModelsPage() {
  const t = useTargetVersion();

  if (t.loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  return (
    <div className="max-w-4xl">
      <h2 className="text-xl font-bold flex items-center gap-2 mb-2" style={{ color: 'var(--text)' }}>
        <Cpu size={20} style={{ color: 'var(--moon)' }} />
        LLM &amp; Services
      </h2>
      <p className="text-sm mb-4" style={{ color: 'var(--text-dim)' }}>
        Model tiers, rating constants, and the SKU catalog of the{' '}
        {t.isDraft ? 'current draft' : 'newest published version'}. Provider costs
        are versioned separately below and publish globally.
      </p>

      <TargetBanner t={t} />

      {t.target?.config && (
        <>
          <TierListsSection t={t} />
          <ConstantsSection t={t} />
          <SkuSection t={t} />
        </>
      )}
      {!t.target && (
        <p className="text-sm mb-8" style={{ color: 'var(--text-dim)' }}>No pricing versions exist yet.</p>
      )}

      <ProviderCostsSection />
    </div>
  );
}

type Target = ReturnType<typeof useTargetVersion>;

function TargetBanner({ t }: { t: Target }) {
  if (!t.target) return null;
  return (
    <>
      <div className="rounded-xl border px-4 py-3 mb-4 flex items-center gap-3 text-sm"
        style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
        <Link to={`/admin/pricing/versions/${t.target.id}`} className="font-semibold hover:underline"
          style={{ color: 'var(--text)' }}>
          v{t.target.version_number}{t.target.name ? ` — ${t.target.name}` : ''}
        </Link>
        <StatusPill status={t.target.status} />
        <span className="flex-1" />
        {!t.isDraft && (
          <button onClick={t.cloneNewestToDraft}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium"
            style={{ background: 'var(--ink)', color: 'var(--moon)' }}>
            <Plus size={12} /> Clone to draft to edit
          </button>
        )}
      </div>
      {(t.target.uncovered_models?.length ?? 0) > 0 && (
        <div className="rounded-xl px-4 py-3 mb-4 text-sm flex items-start gap-2"
          style={{ background: 'rgba(255,200,100,0.12)', color: '#ffc864' }}>
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>Enabled gateway models in neither tier (unpriced — publish blocked):{' '}
            <code>{t.target.uncovered_models!.join(', ')}</code></span>
        </div>
      )}
      {t.error && (
        <div className="rounded-xl px-4 py-3 mb-4 text-sm" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
          {t.error}
        </div>
      )}
      {t.notice && (
        <div className="rounded-xl px-4 py-3 mb-4 text-sm" style={{ background: 'rgba(120,220,160,0.12)', color: '#78dca0' }}>
          {t.notice}
        </div>
      )}
    </>
  );
}

function TierListsSection({ t }: { t: Target }) {
  const config = t.target!.config!;
  const [top, setTop] = useState(config.top_tier_models.join('\n'));
  const [mid, setMid] = useState(config.mid_tier_models.join('\n'));
  const inputStyle = { background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };
  const parse = (s: string) => s.split('\n').map(x => x.trim()).filter(Boolean);

  return (
    <Section title="Model tiers" hint="A model in neither list is not billable — its calls fail closed (sku_unpriced).">
      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="text-[11px] font-medium block mb-1" style={{ color: 'var(--text-dim)' }}>Top tier (one per line)</span>
          <textarea value={top} onChange={e => setTop(e.target.value)} readOnly={!t.isDraft} rows={6}
            spellCheck={false}
            className="w-full px-2.5 py-1.5 rounded-lg text-xs outline-none font-mono" style={inputStyle} />
        </label>
        <label className="block">
          <span className="text-[11px] font-medium block mb-1" style={{ color: 'var(--text-dim)' }}>Mid tier (one per line)</span>
          <textarea value={mid} onChange={e => setMid(e.target.value)} readOnly={!t.isDraft} rows={6}
            spellCheck={false}
            className="w-full px-2.5 py-1.5 rounded-lg text-xs outline-none font-mono" style={inputStyle} />
        </label>
      </div>
      {t.isDraft && (
        <SaveButton onClick={() => t.saveConfig(c => {
          c.top_tier_models = parse(top);
          c.mid_tier_models = parse(mid);
        })} />
      )}
    </Section>
  );
}

function ConstantsSection({ t }: { t: Target }) {
  const config = t.target!.config!;
  // Stored as integer micro-USD; shown/edited as credits (1 credit = 10000 µ$ = 1¢).
  const [values, setValues] = useState<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    for (const [ctx, tiers] of Object.entries(config.llm_constants)) {
      for (const [tier, v] of Object.entries(tiers)) out[`${ctx}.${tier}`] = String(v / 10_000);
    }
    return out;
  });
  const inputStyle = { background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };
  const contexts = Object.keys(config.llm_constants);

  return (
    <Section title="LLM constants"
      hint="Margin in credits added on top of vendor cost per LLM call (1 credit = $0.01). Contexts (agent/direct/forge) are internal classification — never customer-visible.">
      <table className="text-xs" style={{ color: 'var(--text)' }}>
        <thead>
          <tr style={{ color: 'var(--text-dim)' }}>
            <th className="text-left pr-4 py-1 font-medium">Context</th>
            {Object.keys(config.llm_constants[contexts[0]] ?? {}).map(tier => (
              <th key={tier} className="text-left pr-4 py-1 font-medium">{tier} tier</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {contexts.map(ctx => (
            <tr key={ctx}>
              <td className="pr-4 py-1 font-semibold">{ctx}</td>
              {Object.keys(config.llm_constants[ctx]).map(tier => (
                <td key={tier} className="pr-4 py-1">
                  <span className="inline-flex items-center gap-1.5">
                    <span style={{ color: 'var(--text-dim)' }}>credits/call</span>
                    <input type="number" step="any" value={values[`${ctx}.${tier}`] ?? ''} readOnly={!t.isDraft}
                      onChange={e => setValues(v => ({ ...v, [`${ctx}.${tier}`]: e.target.value }))}
                      className="w-24 px-2 py-1 rounded-lg outline-none" style={inputStyle} />
                  </span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {t.isDraft && (
        <SaveButton onClick={() => t.saveConfig(c => {
          for (const [key, raw] of Object.entries(values)) {
            const [ctx, tier] = key.split('.');
            c.llm_constants[ctx][tier] = Math.round(Number(raw) * 10_000);
          }
        })} />
      )}
    </Section>
  );
}

function SkuSection({ t }: { t: Target }) {
  const config = t.target!.config!;
  const [rows, setRows] = useState(() => config.skus.map(s => ({
    ...s, constantsText: JSON.stringify(s.constants ?? {}),
  })));
  const [hosting, setHosting] = useState(String(config.hosting.price_credits));
  const inputStyle = { background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };

  const save = () => t.saveConfig(c => {
    c.skus = rows.map(({ constantsText, ...sku }) => {
      const constants = JSON.parse(constantsText || '{}');
      return { ...sku, constants };
    });
    c.hosting.price_credits = Number(hosting);
    const hostingSku = c.skus.find(s => s.key === 'hosting_month');
    if (hostingSku?.constants) hostingSku.constants.price_credits = Number(hosting);
  });

  return (
    <Section title="SKU catalog"
      hint="Disabled SKUs fail closed at rating. An enabled SKU needs its formula's constants; unknown formulas are rejected.">
      <div className="rounded-xl border overflow-hidden mb-3" style={{ borderColor: 'var(--ink-lighter)' }}>
        <table className="w-full text-xs" style={{ color: 'var(--text)' }}>
          <thead>
            <tr style={{ background: 'var(--surface)', color: 'var(--text-dim)' }}>
              <th className="text-left px-3 py-2 font-medium">Key</th>
              <th className="text-left px-3 py-2 font-medium">Service</th>
              <th className="text-left px-3 py-2 font-medium">Formula</th>
              <th className="text-left px-3 py-2 font-medium">Constants</th>
              <th className="text-left px-3 py-2 font-medium">Enabled</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((sku, i) => (
              <tr key={sku.key} style={{ background: i % 2 ? 'var(--surface)' : 'transparent', opacity: sku.enabled ? 1 : 0.55 }}>
                <td className="px-3 py-2 font-mono font-semibold">{sku.key}</td>
                <td className="px-3 py-2">{sku.service}</td>
                <td className="px-3 py-2 font-mono">{sku.formula}</td>
                <td className="px-3 py-2">
                  <input type="text" value={sku.constantsText} readOnly={!t.isDraft} spellCheck={false}
                    onChange={e => setRows(r => r.map((x, j) => j === i ? { ...x, constantsText: e.target.value } : x))}
                    className="w-full px-2 py-1 rounded-lg outline-none font-mono" style={inputStyle} />
                </td>
                <td className="px-3 py-2">
                  <input type="checkbox" checked={sku.enabled} disabled={!t.isDraft}
                    onChange={e => setRows(r => r.map((x, j) => j === i ? { ...x, enabled: e.target.checked } : x))} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <label className="flex items-center gap-2 text-xs mb-1" style={{ color: 'var(--text-dim)' }}>
        Hosting price (per Luna / month)
        <span className="inline-flex items-center gap-1.5">
          <span>credits</span>
          <input type="number" value={hosting} readOnly={!t.isDraft} onChange={e => setHosting(e.target.value)}
            className="w-28 px-2 py-1 rounded-lg outline-none" style={inputStyle} />
        </span>
      </label>
      {t.isDraft && <SaveButton onClick={save} />}
    </Section>
  );
}

function ProviderCostsSection() {
  const [versions, setVersions] = useState<ProviderCostVersionOut[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [rates, setRates] = useState<Record<string, ProviderCostVersionOut>>({});
  const [showDraft, setShowDraft] = useState(false);
  const [draftJson, setDraftJson] = useState('');
  const [notes, setNotes] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const inputStyle = { background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };

  const refresh = async () => {
    const res = await fetch(`${API}/provider-costs`);
    if (res.ok) setVersions((await res.json()).versions);
  };
  useEffect(() => { refresh(); }, []);

  const toggle = async (id: string) => {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    if (!rates[id]) {
      const res = await fetch(`${API}/provider-costs/${id}`);
      if (res.ok) {
        const body = await res.json();
        setRates(r => ({ ...r, [id]: body }));
        // Prefill the draft editor with the newest rates for easy cloning.
        if (!draftJson) setDraftJson(JSON.stringify(body.rates, null, 2));
      }
    }
  };

  const createDraft = async () => {
    setError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(draftJson);
    } catch (e) {
      setError(`Invalid JSON: ${(e as Error).message}`);
      return;
    }
    const res = await fetch(`${API}/provider-costs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rates: parsed, notes: notes || null }),
    });
    if (res.ok) { setShowDraft(false); refresh(); }
    else setError(await apiError(res));
  };

  const publish = async (id: string) => {
    setError(null);
    const res = await fetch(`${API}/provider-costs/${id}/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    });
    if (res.ok) refresh();
    else setError(await apiError(res));
  };

  return (
    <Section title="Provider costs"
      hint="Versioned vendor rates for margin analytics. Publication is global and effective-dated — costs can never be pinned to a customer cohort.">
      {error && (
        <div className="rounded-xl px-4 py-3 mb-3 text-sm" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
          {error}
        </div>
      )}
      <div className="space-y-2 mb-3">
        {versions.map(v => (
          <div key={v.id} className="rounded-xl border" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
            <div role="button" tabIndex={0} onClick={() => toggle(v.id)}
              onKeyDown={e => { if (e.key === 'Enter') toggle(v.id); }}
              className="flex items-center gap-3 px-4 py-2.5 cursor-pointer">
              <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>cost v{v.version_number}</span>
              <StatusPill status={v.status} />
              <span className="text-xs" style={{ color: 'var(--text-dim)' }}>
                {v.effective_at ? `effective ${new Date(v.effective_at).toLocaleString()}` : 'no effective date'}
                {v.notes ? ` · ${v.notes}` : ''}
              </span>
              <span className="flex-1" />
              {v.status === 'draft' && (
                <>
                  <input type="text" value={reason} onChange={e => setReason(e.target.value)}
                    onClick={e => e.stopPropagation()}
                    placeholder="Reason to publish"
                    className="w-48 px-2 py-1 rounded-lg text-xs outline-none" style={inputStyle} />
                  <button onClick={e => { e.stopPropagation(); publish(v.id); }}
                    disabled={!reason.trim()}
                    className="px-2.5 py-1 rounded-lg text-xs font-semibold disabled:opacity-50"
                    style={{ background: 'rgba(120,220,160,0.2)', color: '#78dca0' }}>
                    Publish
                  </button>
                </>
              )}
            </div>
            {expanded === v.id && rates[v.id] && (
              <div className="px-4 pb-3 border-t pt-3" style={{ borderColor: 'var(--ink-lighter)' }}>
                <table className="w-full text-xs" style={{ color: 'var(--text)' }}>
                  <thead>
                    <tr style={{ color: 'var(--text-dim)' }}>
                      <th className="text-left pr-3 py-1 font-medium">Provider</th>
                      <th className="text-left pr-3 py-1 font-medium">SKU</th>
                      <th className="text-left pr-3 py-1 font-medium">Dimension</th>
                      <th className="text-right pr-3 py-1 font-medium">Rate</th>
                      <th className="text-left py-1 font-medium">Quality</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rates[v.id].rates!.map((r, i) => (
                      <tr key={i}>
                        <td className="pr-3 py-1">{r.provider}</td>
                        <td className="pr-3 py-1 font-mono">{r.sku}</td>
                        <td className="pr-3 py-1">{r.dimension}</td>
                        <td className="pr-3 py-1 text-right font-mono">{r.rate_numerator}/{r.rate_denominator} $/{r.unit}</td>
                        <td className="py-1">{r.quality}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ))}
      </div>
      <button onClick={() => setShowDraft(v => !v)}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium mb-2"
        style={{ background: 'var(--ink)', color: 'var(--moon)' }}>
        <Plus size={12} /> New cost draft
      </button>
      {showDraft && (
        <div className="rounded-lg p-3 space-y-2" style={{ background: 'var(--ink)', border: '1px solid var(--moon)' }}>
          <textarea value={draftJson} onChange={e => setDraftJson(e.target.value)} rows={10} spellCheck={false}
            placeholder='[{"provider":"anthropic","sku":"claude-opus-4-6","dimension":"input_tokens","unit":"mtok","rate_numerator":5,"rate_denominator":1}]'
            className="w-full px-2.5 py-1.5 rounded-lg text-xs outline-none font-mono"
            style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' }} />
          <div className="flex items-center gap-2">
            <input type="text" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Notes"
              className="flex-1 px-2.5 py-1.5 rounded-lg text-xs outline-none"
              style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' }} />
            <button onClick={createDraft}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold"
              style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
              Create draft
            </button>
          </div>
        </div>
      )}
    </Section>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="mb-8">
      <h3 className="text-sm font-bold mb-1" style={{ color: 'var(--text)' }}>{title}</h3>
      {hint && <p className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>{hint}</p>}
      {children}
    </div>
  );
}

function SaveButton({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold mt-2"
      style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
      <Save size={12} /> Save to draft
    </button>
  );
}
