import { useEffect, useState } from 'react';
import { Loader2, Plus, Trash2, Cpu, Pencil } from 'lucide-react';
import DefaultsTabs from './DefaultsTabs';

type ModelKind = 'reasoning' | 'summarization' | 'embedding';

interface CatalogModel {
  id: string;
  provider: string;
  model: string;
  label: string | null;
  context_window: number | null;
  kinds: ModelKind[];
  aliases: string[];
  tier: string | null;
  input_cost: number | null;
  output_cost: number | null;
  recommended_default: boolean;
  deprecated: boolean;
  enabled: boolean;
  key_count: number;
}

const API = '/api/admin/gateway';
const ALL_KINDS: ModelKind[] = ['reasoning', 'summarization', 'embedding'];

/**
 * The global model catalog every Luna instance picks from (injected as
 * LUNA_MODEL_CATALOG; off-catalog calls are rejected at the proxy). Lives under
 * Defaults — it's a fleet-wide default, not a credential. Keys live in the Key
 * Registry. (Plan 020)
 */
export default function ModelsPage() {
  const [models, setModels] = useState<CatalogModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<CatalogModel | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    const res = await fetch(`${API}/models`);
    if (res.ok) setModels(await res.json());
    setLoading(false);
  };
  useEffect(() => { refresh(); }, []);

  const patch = async (id: string, body: object) => {
    const res = await fetch(`${API}/models/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (res.ok) refresh();
    else setError((await res.json().catch(() => null))?.detail || `Failed (${res.status})`);
  };

  const setDefault = (id: string) => patch(id, { recommended_default: true });

  const remove = async (m: CatalogModel) => {
    if (!confirm(`Remove ${m.provider}:${m.model} from the catalog? Agents can no longer select it.`)) return;
    const res = await fetch(`${API}/models/${m.id}`, { method: 'DELETE' });
    if (res.ok) refresh();
  };

  const byProvider = models.reduce<Record<string, CatalogModel[]>>((acc, m) => {
    (acc[m.provider] ||= []).push(m);
    return acc;
  }, {});

  return (
    <div className="max-w-4xl">
      <DefaultsTabs />

      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <Cpu size={20} style={{ color: 'var(--moon)' }} />
          Model catalog
        </h2>
        <button
          onClick={() => { setShowAdd(v => !v); setEditing(null); }}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:scale-105"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}
        >
          <Plus size={16} /> Add model
        </button>
      </div>
      <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>
        The models every Luna instance may use (injected as <code>LUNA_MODEL_CATALOG</code>).
        <b> In</b> = selectable; out = hidden. Off-catalog calls are rejected at the proxy. The
        <b> default</b> per kind is the head new images run unless an image or machine overrides it.
      </p>

      {error && (
        <div className="rounded-xl px-4 py-3 mb-4 text-sm" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
          {error}
        </div>
      )}

      {loading ? (
        <Loader2 className="animate-spin" size={16} style={{ color: 'var(--moon)' }} />
      ) : (
        <>
          {showAdd && <ModelForm onDone={() => { setShowAdd(false); refresh(); }} onError={setError} />}
          {editing && <ModelForm model={editing} onDone={() => { setEditing(null); refresh(); }} onError={setError} />}

          {models.length === 0 && !showAdd && (
            <p className="text-xs py-1" style={{ color: 'var(--text-dim)' }}>
              No models in the catalog yet. Seeded automatically on server start.
            </p>
          )}

          <div className="space-y-3">
            {Object.entries(byProvider).map(([provider, list]) => (
              <div key={provider}>
                <div className="text-xs font-semibold uppercase tracking-wide mb-1.5 flex items-center gap-2" style={{ color: 'var(--text-dim)' }}>
                  {provider}
                  <span className="px-1.5 py-0.5 rounded" style={{ background: 'var(--ink)', color: list[0]?.key_count ? '#78dca0' : '#ff6b6b' }}>
                    {list[0]?.key_count || 0} key{list[0]?.key_count === 1 ? '' : 's'}
                  </span>
                </div>
                <div className="space-y-1.5">
                  {list.map(m => (
                    <div
                      key={m.id}
                      className="flex items-center gap-3 px-3 py-2 rounded-lg text-xs"
                      style={{ background: 'var(--ink)', opacity: m.enabled ? 1 : 0.5 }}
                    >
                      <OnOffPill value={m.enabled} onChange={() => patch(m.id, { enabled: !m.enabled })} />
                      <span className="font-medium" style={{ color: 'var(--text)' }}>{m.label || m.model}</span>
                      <code style={{ color: 'var(--text-dim)' }}>{m.model}</code>
                      {m.kinds.map(k => (
                        <span key={k} className="px-1.5 py-0.5 rounded-full capitalize" style={{ background: 'var(--surface)', color: 'var(--text-dim)' }}>{k}</span>
                      ))}
                      {m.recommended_default ? (
                        <span className="px-1.5 py-0.5 rounded-full" style={{ background: 'rgba(120,220,160,0.15)', color: '#78dca0' }}>default</span>
                      ) : m.enabled && !m.deprecated ? (
                        <button onClick={() => setDefault(m.id)} className="px-1.5 py-0.5 rounded-full hover:opacity-80" style={{ background: 'var(--surface)', color: 'var(--text-dim)' }} title="Make this the default for its kind(s)">
                          set default
                        </button>
                      ) : null}
                      {m.deprecated && (
                        <span className="px-1.5 py-0.5 rounded-full" style={{ background: 'rgba(255,107,107,0.15)', color: '#ff6b6b' }}>deprecated</span>
                      )}
                      <span className="flex-1" />
                      <button onClick={() => { setEditing(m); setShowAdd(false); }} className="hover:opacity-80" style={{ color: 'var(--text-dim)' }}>
                        <Pencil size={12} />
                      </button>
                      <button onClick={() => remove(m)} className="hover:opacity-80" style={{ color: '#ff6b6b' }}>
                        <Trash2 size={12} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function OnOffPill({ value, onChange }: { value: boolean; onChange: () => void }) {
  return (
    <button onClick={onChange} className="flex items-center" style={{ color: 'var(--text-dim)' }}>
      <span
        className="relative inline-flex items-center flex-shrink-0 rounded-full transition-colors duration-200"
        style={{ width: 36, height: 20, background: value ? '#22c55e' : '#4b5563' }}
      >
        <span
          className="inline-block rounded-full bg-white shadow transition-transform duration-200"
          style={{ width: 16, height: 16, transform: value ? 'translateX(18px)' : 'translateX(2px)' }}
        />
      </span>
    </button>
  );
}

function ModelForm({ model, onDone, onError }: { model?: CatalogModel; onDone: () => void; onError: (m: string | null) => void }) {
  const editing = !!model;
  const [provider, setProvider] = useState(model?.provider || 'anthropic');
  const [modelId, setModelId] = useState(model?.model || '');
  const [label, setLabel] = useState(model?.label || '');
  const [kinds, setKinds] = useState<ModelKind[]>(model?.kinds || ['reasoning']);
  const [aliases, setAliases] = useState((model?.aliases || []).join(', '));
  const [contextWindow, setContextWindow] = useState(model?.context_window?.toString() || '');
  const [deprecated, setDeprecated] = useState(model?.deprecated || false);
  const [saving, setSaving] = useState(false);

  const toggleKind = (k: ModelKind) =>
    setKinds(ks => ks.includes(k) ? ks.filter(x => x !== k) : [...ks, k]);

  const submit = async () => {
    setSaving(true); onError(null);
    const body = {
      label: label || null,
      kinds,
      aliases: aliases.split(',').map(s => s.trim()).filter(Boolean),
      context_window: contextWindow ? Number(contextWindow) : null,
      deprecated,
      ...(editing ? {} : { provider, model: modelId }),
    };
    const url = editing ? `${API}/models/${model!.id}` : `${API}/models`;
    const res = await fetch(url, {
      method: editing ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    setSaving(false);
    if (res.ok) onDone();
    else onError((await res.json().catch(() => null))?.detail || `Failed (${res.status})`);
  };

  const inputStyle = { background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };

  return (
    <div className="rounded-lg p-3 mb-3 space-y-2" style={{ background: 'var(--ink)', border: '1px solid var(--moon)' }}>
      <div className="text-xs font-semibold" style={{ color: 'var(--text)' }}>
        {editing ? `Edit ${model!.provider}:${model!.model}` : 'New model'}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {!editing && (
          <>
            <select value={provider} onChange={e => setProvider(e.target.value)} className="px-2 py-1.5 rounded-lg text-xs outline-none" style={inputStyle}>
              <option value="anthropic">anthropic</option>
              <option value="openai">openai</option>
            </select>
            <input type="text" value={modelId} onChange={e => setModelId(e.target.value)} placeholder="model id (e.g. gpt-4.1)"
              className="w-48 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} autoFocus />
          </>
        )}
        <input type="text" value={label} onChange={e => setLabel(e.target.value)} placeholder="Label"
          className="w-40 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} />
        <input type="text" value={aliases} onChange={e => setAliases(e.target.value)} placeholder="aliases (comma-sep)"
          className="w-44 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} />
        <input type="number" value={contextWindow} onChange={e => setContextWindow(e.target.value)} placeholder="context"
          className="w-24 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} />
      </div>
      <div className="flex items-center gap-3">
        <span className="text-xs" style={{ color: 'var(--text-dim)' }}>Kinds:</span>
        {ALL_KINDS.map(k => (
          <label key={k} className="flex items-center gap-1 text-xs capitalize" style={{ color: 'var(--text)' }}>
            <input type="checkbox" checked={kinds.includes(k)} onChange={() => toggleKind(k)} /> {k}
          </label>
        ))}
        <label className="flex items-center gap-1 text-xs" style={{ color: 'var(--text)' }}>
          <input type="checkbox" checked={deprecated} onChange={e => setDeprecated(e.target.checked)} /> deprecated
        </label>
        <span className="flex-1" />
        <button onClick={submit} disabled={saving || (!editing && (!modelId || kinds.length === 0))}
          className="px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
          {saving ? <Loader2 className="animate-spin" size={12} /> : editing ? 'Save' : 'Create'}
        </button>
      </div>
    </div>
  );
}
