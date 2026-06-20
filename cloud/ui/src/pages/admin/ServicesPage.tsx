import { useEffect, useState } from 'react';
import {
  KeyRound, Loader2, Plus, Trash2, ChevronDown, ChevronRight,
  Snowflake, BarChart3, Cpu, Pencil,
} from 'lucide-react';

interface Service {
  slug: string;
  display_name: string;
  upstream_url: string;
  auth_style: string;
  luna_credential_name: string;
  luna_env_key_var: string;
  luna_env_base_url_var: string;
  enabled: boolean;
  provision_by_default: boolean;
  key_count: number;
}

interface PoolKey {
  id: string;
  service_slug: string;
  scope: string;
  priority: number;
  label: string;
  is_active: boolean;
  on_cooldown: boolean;
  cooldown_until: string | null;
  last_used_at: string | null;
}

interface AgentLight { id: string; slug: string; name: string }

interface UsageRow {
  agent_id: string | null;
  agent_slug: string | null;
  service_slug: string;
  billable: boolean;
  requests: number;
  input_tokens: number;
  output_tokens: number;
}

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

export default function ServicesPage() {
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddService, setShowAddService] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [usage, setUsage] = useState<UsageRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    const res = await fetch(`${API}/services`);
    if (res.ok) setServices(await res.json());
    const u = await fetch(`${API}/usage`);
    if (u.ok) setUsage(await u.json());
    setLoading(false);
  };

  useEffect(() => { refresh(); }, []);

  const toggleService = async (svc: Service, field: 'enabled' | 'provision_by_default') => {
    const res = await fetch(`${API}/services/${svc.slug}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: !svc[field] }),
    });
    if (res.ok) refresh();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  return (
    <div className="max-w-4xl">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <KeyRound size={20} style={{ color: 'var(--moon)' }} />
          Key Registry
        </h2>
        <button
          onClick={() => setShowAddService(v => !v)}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:scale-105"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}
        >
          <Plus size={16} />
          Add Service
        </button>
      </div>
      <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>
        Credential gateway registry. Tenant machines call <code>/proxy/&lt;slug&gt;</code> with their
        tenant token; the real key is injected here and never reaches the machine.
      </p>

      {error && (
        <div className="rounded-xl px-4 py-3 mb-4 text-sm" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
          {error}
        </div>
      )}

      {showAddService && (
        <AddServiceForm
          onDone={() => { setShowAddService(false); refresh(); }}
          onError={setError}
        />
      )}

      <div className="space-y-2 mb-10">
        {services.map(svc => (
          <ServiceRow
            key={svc.slug}
            svc={svc}
            expanded={expanded === svc.slug}
            onToggleExpand={() => setExpanded(expanded === svc.slug ? null : svc.slug)}
            onToggleField={toggleService}
            onError={setError}
            onChanged={refresh}
          />
        ))}
      </div>

      <ModelsSection onError={setError} />

      <UsageSection usage={usage} />
    </div>
  );
}

function ServiceRow({ svc, expanded, onToggleExpand, onToggleField, onError, onChanged }: {
  svc: Service;
  expanded: boolean;
  onToggleExpand: () => void;
  onToggleField: (svc: Service, field: 'enabled' | 'provision_by_default') => void;
  onError: (msg: string | null) => void;
  onChanged: () => void;
}) {
  return (
    <div className="rounded-xl border" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
      <div
        onClick={onToggleExpand}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggleExpand(); } }}
        role="button"
        tabIndex={0}
        className="w-full flex items-center gap-3 px-5 py-3 text-left cursor-pointer"
      >
        {expanded ? <ChevronDown size={16} style={{ color: 'var(--text-dim)' }} /> : <ChevronRight size={16} style={{ color: 'var(--text-dim)' }} />}
        <div className="flex-1">
          <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{svc.display_name}</span>
          <div className="text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>
            <a
              href={svc.upstream_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={e => e.stopPropagation()}
              className="hover:underline"
              style={{ color: 'var(--text-dim)' }}
            >
              {svc.upstream_url}
            </a>
            {' · '}{svc.key_count} key{svc.key_count === 1 ? '' : 's'}
          </div>
        </div>
      </div>

      {expanded && (
        <div className="px-5 pb-4 border-t pt-4" style={{ borderColor: 'var(--ink-lighter)' }}>
          <div className="flex items-center gap-4 mb-4 text-xs" style={{ color: 'var(--text-dim)' }}>
            <span>Env: <code>{svc.luna_env_key_var}</code> / <code>{svc.luna_env_base_url_var}</code></span>
            <span>Vault: <code>{svc.luna_credential_name}</code></span>
          </div>
          <div className="flex items-center gap-3 mb-4">
            <OnOffPill label="Enabled" description="gateway accepts requests" value={svc.enabled} onChange={() => onToggleField(svc, 'enabled')} />
            <OnOffPill label="Provision by default" description="auto-add key for new agents" value={svc.provision_by_default} onChange={() => onToggleField(svc, 'provision_by_default')} />
          </div>
          <KeyPool slug={svc.slug} onError={onError} onChanged={onChanged} />
        </div>
      )}
    </div>
  );
}

function OnOffPill({ label, description, value, onChange }: {
  label: string;
  description?: string;
  value: boolean;
  onChange: () => void;
}) {
  return (
    <button
      onClick={onChange}
      className="flex items-center gap-2.5 text-xs font-medium group"
      style={{ color: 'var(--text-dim)' }}
    >
      <span
        className="relative inline-flex items-center flex-shrink-0 rounded-full transition-colors duration-200"
        style={{
          width: 36,
          height: 20,
          background: value ? '#22c55e' : '#4b5563',
        }}
      >
        <span
          className="inline-block rounded-full bg-white shadow transition-transform duration-200"
          style={{
            width: 16,
            height: 16,
            transform: value ? 'translateX(18px)' : 'translateX(2px)',
          }}
        />
      </span>
      <span style={{ color: value ? 'var(--text)' : 'var(--text-dim)' }}>{label}</span>
      {description && (
        <span style={{ fontWeight: 400 }}>— {description}</span>
      )}
    </button>
  );
}

function KeyPool({ slug, onError, onChanged }: { slug: string; onError: (m: string | null) => void; onChanged: () => void }) {
  const [keys, setKeys] = useState<PoolKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);

  const refresh = async () => {
    const res = await fetch(`${API}/services/${slug}/keys`);
    if (res.ok) setKeys(await res.json());
    setLoading(false);
  };

  useEffect(() => { refresh(); }, [slug]);

  const patchKey = async (id: string, body: object) => {
    const res = await fetch(`${API}/keys/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) { refresh(); onChanged(); }
  };

  const deleteKey = async (id: string) => {
    if (!confirm('Delete this key? Traffic falls back to the next key in the chain.')) return;
    const res = await fetch(`${API}/keys/${id}`, { method: 'DELETE' });
    if (res.ok) { refresh(); onChanged(); }
  };

  if (loading) return <Loader2 className="animate-spin" size={16} style={{ color: 'var(--moon)' }} />;

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-dim)' }}>Key pool</span>
        <button
          onClick={() => setShowAdd(v => !v)}
          className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium"
          style={{ background: 'var(--ink)', color: 'var(--moon)' }}
        >
          <Plus size={12} /> Add key
        </button>
      </div>

      {showAdd && (
        <AddKeyForm
          slug={slug}
          onDone={() => { setShowAdd(false); refresh(); onChanged(); }}
          onError={onError}
        />
      )}

      {keys.length === 0 && !showAdd && (
        <p className="text-xs py-1" style={{ color: 'var(--text-dim)' }}>
          No keys. Requests for this service will fail until a key is added.
        </p>
      )}

      <div className="space-y-1.5">
        {keys.map(k => (
          <div
            key={k.id}
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-xs"
            style={{ background: 'var(--ink)', opacity: k.is_active ? 1 : 0.5 }}
          >
            <span className="font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--surface)', color: 'var(--moon)' }}>
              P{k.priority}
            </span>
            <span className="font-medium" style={{ color: 'var(--text)' }}>{k.label || '(unlabeled)'}</span>
            <span style={{ color: 'var(--text-dim)' }}>{k.scope}</span>
            {k.on_cooldown && (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded-full" style={{ background: 'rgba(122,162,255,0.15)', color: '#7aa2ff' }} title={`Cooling down until ${k.cooldown_until}`}>
                <Snowflake size={10} /> cooldown
              </span>
            )}
            {k.last_used_at && <span style={{ color: 'var(--text-dim)' }}>used {new Date(k.last_used_at).toLocaleTimeString()}</span>}
            <span className="flex-1" />
            {k.on_cooldown && (
              <button onClick={() => patchKey(k.id, { clear_cooldown: true })} className="hover:opacity-80" style={{ color: 'var(--text-dim)' }}>
                clear cooldown
              </button>
            )}
            <button onClick={() => patchKey(k.id, { is_active: !k.is_active })} className="hover:opacity-80" style={{ color: 'var(--text-dim)' }}>
              {k.is_active ? 'deactivate' : 'activate'}
            </button>
            <button onClick={() => deleteKey(k.id)} className="hover:opacity-80" style={{ color: '#ff6b6b' }}>
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function AddKeyForm({ slug, onDone, onError }: { slug: string; onDone: () => void; onError: (m: string | null) => void }) {
  const [apiKey, setApiKey] = useState('');
  const [label, setLabel] = useState('');
  const [priority, setPriority] = useState(1);
  const [scopeKind, setScopeKind] = useState<'global' | 'agent'>('global');
  const [agentId, setAgentId] = useState('');
  const [agents, setAgents] = useState<AgentLight[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`${API}/agents-light`).then(r => r.ok ? r.json() : []).then(setAgents);
  }, []);

  const submit = async () => {
    setSaving(true);
    onError(null);
    const scope = scopeKind === 'global' ? 'global' : `agent:${agentId}`;
    const res = await fetch(`${API}/services/${slug}/keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey, label, priority, scope }),
    });
    setSaving(false);
    if (res.ok) {
      setApiKey('');
      onDone();
    } else {
      const detail = (await res.json().catch(() => null))?.detail || `Failed (${res.status})`;
      onError(detail);
    }
  };

  const inputStyle = { background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };

  return (
    <div className="rounded-lg p-3 mb-2 space-y-2" style={{ background: 'var(--ink)', border: '1px solid var(--moon)' }}>
      <input
        type="password"
        value={apiKey}
        onChange={e => setApiKey(e.target.value)}
        placeholder="API key value (write-only — never shown again)"
        className="w-full px-2.5 py-1.5 rounded-lg text-xs outline-none"
        style={inputStyle}
        autoFocus
      />
      <div className="flex items-center gap-2">
        <input
          type="text" value={label} onChange={e => setLabel(e.target.value)} placeholder="Label (e.g. anthropic-main)"
          className="flex-1 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle}
        />
        <input
          type="number" min={1} value={priority} onChange={e => setPriority(Number(e.target.value))} title="Priority (1 = primary)"
          className="w-16 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle}
        />
        <select
          value={scopeKind} onChange={e => setScopeKind(e.target.value as 'global' | 'agent')}
          className="px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle}
        >
          <option value="global">Global</option>
          <option value="agent">Agent override</option>
        </select>
        {scopeKind === 'agent' && (
          <select value={agentId} onChange={e => setAgentId(e.target.value)} className="px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle}>
            <option value="">Select agent…</option>
            {agents.map(a => <option key={a.id} value={a.id}>{a.slug}</option>)}
          </select>
        )}
        <button
          onClick={submit}
          disabled={saving || !apiKey || (scopeKind === 'agent' && !agentId)}
          className="px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}
        >
          {saving ? <Loader2 className="animate-spin" size={12} /> : 'Save'}
        </button>
      </div>
    </div>
  );
}

function AddServiceForm({ onDone, onError }: { onDone: () => void; onError: (m: string | null) => void }) {
  const [slug, setSlug] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [upstreamUrl, setUpstreamUrl] = useState('');
  const [authStyle, setAuthStyle] = useState('header:Authorization:Bearer');
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    setSaving(true);
    onError(null);
    const res = await fetch(`${API}/services`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        slug, display_name: displayName || slug, upstream_url: upstreamUrl, auth_style: authStyle,
      }),
    });
    setSaving(false);
    if (res.ok) onDone();
    else {
      const detail = (await res.json().catch(() => null))?.detail || `Failed (${res.status})`;
      onError(detail);
    }
  };

  const inputStyle = { background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };

  return (
    <div className="rounded-2xl p-5 border mb-4 space-y-2" style={{ background: 'var(--surface)', borderColor: 'var(--moon)' }}>
      <div className="text-sm font-semibold mb-1" style={{ color: 'var(--text)' }}>New service</div>
      <div className="flex items-center gap-2">
        <input type="text" value={slug} onChange={e => setSlug(e.target.value)} placeholder="slug (e.g. composio)"
          className="w-44 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} autoFocus />
        <input type="text" value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder="Display name"
          className="w-44 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} />
        <input type="text" value={upstreamUrl} onChange={e => setUpstreamUrl(e.target.value)} placeholder="https://api.example.com"
          className="flex-1 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} />
        <select value={authStyle} onChange={e => setAuthStyle(e.target.value)}
          className="px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle}>
          <option value="header:Authorization:Bearer">Authorization: Bearer</option>
          <option value="header:x-api-key">x-api-key</option>
        </select>
        <button onClick={submit} disabled={saving || !slug || !upstreamUrl}
          className="px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
          {saving ? <Loader2 className="animate-spin" size={12} /> : 'Create'}
        </button>
      </div>
      <p className="text-xs" style={{ color: 'var(--text-dim)' }}>
        Env var names derive from the slug (LUNA_&lt;SLUG&gt;_API_KEY / _BASE_URL). The service is
        live as soon as it's created — no restart.
      </p>
    </div>
  );
}

function ModelsSection({ onError }: { onError: (m: string | null) => void }) {
  const [models, setModels] = useState<CatalogModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<CatalogModel | null>(null);

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
    else onError((await res.json().catch(() => null))?.detail || `Failed (${res.status})`);
  };

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
    <div className="mb-10">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <Cpu size={16} style={{ color: 'var(--moon)' }} />
          Model catalog
        </h3>
        <button
          onClick={() => { setShowAdd(v => !v); setEditing(null); }}
          className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium"
          style={{ background: 'var(--ink)', color: 'var(--moon)' }}
        >
          <Plus size={12} /> Add model
        </button>
      </div>
      <p className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>
        The models tenants may use (injected as <code>LUNA_MODEL_CATALOG</code>). <b>In</b> = selectable;
        out = hidden. Off-catalog calls are rejected at the proxy. The <b>default</b> head new images
        run is set under <b>Luna Images → Defaults</b> (it falls back to the catalog default below).
      </p>

      {loading ? (
        <Loader2 className="animate-spin" size={16} style={{ color: 'var(--moon)' }} />
      ) : (
        <>
          {showAdd && (
            <ModelForm onDone={() => { setShowAdd(false); refresh(); }} onError={onError} />
          )}
          {editing && (
            <ModelForm model={editing} onDone={() => { setEditing(null); refresh(); }} onError={onError} />
          )}

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
                      <OnOffPill label="" value={m.enabled} onChange={() => patch(m.id, { enabled: !m.enabled })} />
                      <span className="font-medium" style={{ color: 'var(--text)' }}>{m.label || m.model}</span>
                      <code style={{ color: 'var(--text-dim)' }}>{m.model}</code>
                      {m.kinds.map(k => (
                        <span key={k} className="px-1.5 py-0.5 rounded-full capitalize" style={{ background: 'var(--surface)', color: 'var(--text-dim)' }}>{k}</span>
                      ))}
                      {m.recommended_default && (
                        <span className="px-1.5 py-0.5 rounded-full" style={{ background: 'rgba(120,220,160,0.15)', color: '#78dca0' }}>default</span>
                      )}
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

function UsageSection({ usage }: { usage: UsageRow[] }) {
  return (
    <div>
      <h3 className="text-sm font-bold flex items-center gap-2 mb-3" style={{ color: 'var(--text)' }}>
        <BarChart3 size={16} style={{ color: 'var(--moon)' }} />
        Usage (managed vs BYOK)
      </h3>
      {usage.length === 0 ? (
        <p className="text-xs" style={{ color: 'var(--text-dim)' }}>No proxied requests yet.</p>
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--ink-lighter)' }}>
          <table className="w-full text-xs" style={{ color: 'var(--text)' }}>
            <thead>
              <tr style={{ background: 'var(--surface)', color: 'var(--text-dim)' }}>
                <th className="text-left px-4 py-2 font-medium">Agent</th>
                <th className="text-left px-4 py-2 font-medium">Service</th>
                <th className="text-left px-4 py-2 font-medium">Billing</th>
                <th className="text-right px-4 py-2 font-medium">Requests</th>
                <th className="text-right px-4 py-2 font-medium">Tokens in</th>
                <th className="text-right px-4 py-2 font-medium">Tokens out</th>
              </tr>
            </thead>
            <tbody>
              {usage.map((r, i) => (
                <tr key={i} style={{ background: i % 2 ? 'var(--surface)' : 'transparent' }}>
                  <td className="px-4 py-2">{r.agent_slug || <span style={{ color: 'var(--text-dim)' }}>BYOK / unknown</span>}</td>
                  <td className="px-4 py-2">{r.service_slug}</td>
                  <td className="px-4 py-2">
                    <span className="px-2 py-0.5 rounded-full" style={{
                      background: r.billable ? 'rgba(120,220,160,0.15)' : 'rgba(122,162,255,0.15)',
                      color: r.billable ? '#78dca0' : '#7aa2ff',
                    }}>
                      {r.billable ? 'billable' : 'BYOK'}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right">{r.requests}</td>
                  <td className="px-4 py-2 text-right">{r.input_tokens || '—'}</td>
                  <td className="px-4 py-2 text-right">{r.output_tokens || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
