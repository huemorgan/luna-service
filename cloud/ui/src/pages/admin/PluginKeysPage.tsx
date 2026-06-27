import { useCallback, useEffect, useState } from 'react';
import { Loader2, Plus, Trash2, Plug, ShieldCheck, ShieldAlert, Download } from 'lucide-react';

interface CatalogEntry {
  plugin_name: string;
  display_name: string;
  marketplace_url: string | null;
  category: string | null;
  tier: 'default' | 'supported';
  service_slug: string | null;
  key_mode: 'proxy' | 'env';
  suggested: { needs_review?: boolean } | null;
  enabled: boolean;
  keyed: boolean;
}
interface ServiceLite { slug: string; display_name: string; key_count: number }
interface AgentLight { id: string; slug: string; name: string }

const CAT = '/api/admin/plugin-catalog';
const GW = '/api/admin/gateway';

export default function PluginKeysPage() {
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [services, setServices] = useState<ServiceLite[]>([]);
  const [agents, setAgents] = useState<AgentLight[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [c, s, a] = await Promise.all([
      fetch(CAT), fetch(`${GW}/services`), fetch(`${GW}/agents-light`),
    ]);
    if (c.ok) setEntries(await c.json());
    if (s.ok) setServices(await s.json());
    if (a.ok) setAgents(await a.json());
    setLoading(false);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const patch = async (name: string, body: object) => {
    const r = await fetch(`${CAT}/${name}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (r.ok) refresh();
    else setError((await r.json().catch(() => null))?.detail || `Failed (${r.status})`);
  };
  const remove = async (name: string) => {
    if (!confirm(`Remove ${name} from the catalog?`)) return;
    if ((await fetch(`${CAT}/${name}`, { method: 'DELETE' })).ok) refresh();
  };

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} /></div>;
  }

  const defaults = entries.filter(e => e.tier === 'default');
  const supported = entries.filter(e => e.tier === 'supported');

  return (
    <div className="max-w-4xl">
      <h2 className="text-xl font-bold flex items-center gap-2 mb-2" style={{ color: 'var(--text)' }}>
        <Plug size={20} style={{ color: 'var(--moon)' }} />
        Plugin Keys
      </h2>
      <p className="text-sm mb-6" style={{ color: 'var(--text-dim)' }}>
        Attach our pooled keys to plugins. In <b>proxy</b> mode the real key never
        reaches the machine — the agent calls <code>/proxy/&lt;service&gt;</code> with its
        device token. <b>env</b> mode injects the real key on the machine (opt-in).
      </p>

      {error && (
        <div className="rounded-xl px-4 py-3 mb-4 text-sm" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
          {error}
        </div>
      )}

      <Section
        title="Default plugins"
        subtitle="Mirrors the baked plugin set. Key these so baked plugins start connected."
        tier="default" entries={defaults} services={services} agents={agents}
        onPatch={patch} onRemove={remove} onAdded={refresh} onError={setError}
      />
      <div className="h-8" />
      <Section
        title="Supported plugins"
        subtitle="Opt-in catalog. Key them, then install onto an agent to provision the key."
        tier="supported" entries={supported} services={services} agents={agents}
        onPatch={patch} onRemove={remove} onAdded={refresh} onError={setError}
      />
    </div>
  );
}

function Section({ title, subtitle, tier, entries, services, agents, onPatch, onRemove, onAdded, onError }: {
  title: string; subtitle: string; tier: 'default' | 'supported';
  entries: CatalogEntry[]; services: ServiceLite[]; agents: AgentLight[];
  onPatch: (name: string, body: object) => void;
  onRemove: (name: string) => void;
  onAdded: () => void;
  onError: (m: string | null) => void;
}) {
  const [showAdd, setShowAdd] = useState(false);
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>{title}</h3>
        <button
          onClick={() => setShowAdd(v => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold"
          style={{ background: 'var(--ink)', color: 'var(--moon)' }}
        >
          <Plus size={13} /> Add plugin
        </button>
      </div>
      <p className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>{subtitle}</p>

      {showAdd && (
        <AddPluginForm tier={tier} services={services}
          onDone={() => { setShowAdd(false); onAdded(); }} onError={onError} />
      )}

      {entries.length === 0 && !showAdd && (
        <p className="text-xs py-2" style={{ color: 'var(--text-dim)' }}>No plugins yet.</p>
      )}

      <div className="space-y-2">
        {entries.map(e => (
          <Row key={e.plugin_name} e={e} services={services} agents={agents}
            isSupported={tier === 'supported'} onPatch={onPatch} onRemove={onRemove} onError={onError} />
        ))}
      </div>
    </div>
  );
}

function Row({ e, services, agents, isSupported, onPatch, onRemove, onError }: {
  e: CatalogEntry; services: ServiceLite[]; agents: AgentLight[]; isSupported: boolean;
  onPatch: (name: string, body: object) => void;
  onRemove: (name: string) => void;
  onError: (m: string | null) => void;
}) {
  const inputStyle = { background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };
  return (
    <div className="rounded-xl border px-4 py-3" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex-1 min-w-[160px]">
          <div className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{e.display_name}</div>
          <div className="text-xs" style={{ color: 'var(--text-dim)' }}>
            {e.plugin_name}{e.category ? ` · ${e.category}` : ''}
          </div>
        </div>

        {e.service_slug && (e.keyed ? (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>
            <ShieldCheck size={12} /> keyed
          </span>
        ) : (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
            <ShieldAlert size={12} /> no key
          </span>
        ))}
        {e.suggested?.needs_review && !e.service_slug && (
          <span className="px-2 py-0.5 rounded-full text-xs" style={{ background: 'rgba(122,162,255,0.15)', color: '#7aa2ff' }}>needs review</span>
        )}

        {/* Key control */}
        <select
          value={e.service_slug || ''}
          onChange={ev => onPatch(e.plugin_name, { service_slug: ev.target.value })}
          className="px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle}
          title="Bound gateway service (pool key)"
        >
          <option value="">No key</option>
          {services.map(s => (
            <option key={s.slug} value={s.slug}>
              {s.display_name}{s.key_count ? ` (${s.key_count} key${s.key_count === 1 ? '' : 's'})` : ' — no keys'}
            </option>
          ))}
        </select>

        <select
          value={e.key_mode}
          onChange={ev => onPatch(e.plugin_name, { key_mode: ev.target.value })}
          className="px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle}
          title="proxy (key stays server-side) / env (real key on machine)"
        >
          <option value="proxy">proxy</option>
          <option value="env">env</option>
        </select>

        {isSupported && (
          <InstallControl plugin={e.plugin_name} agents={agents} onError={onError} />
        )}

        <button onClick={() => onRemove(e.plugin_name)} className="hover:opacity-80" style={{ color: '#ff6b6b' }} title="Remove from catalog">
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  );
}

function InstallControl({ plugin, agents, onError }: {
  plugin: string; agents: AgentLight[]; onError: (m: string | null) => void;
}) {
  const [agentId, setAgentId] = useState('');
  const [busy, setBusy] = useState(false);
  const inputStyle = { background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };

  const install = async () => {
    if (!agentId) return;
    setBusy(true); onError(null);
    const r = await fetch(`${CAT}/install`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: agentId, plugin_name: plugin }),
    });
    setBusy(false);
    if (!r.ok) onError((await r.json().catch(() => null))?.detail || `Install failed (${r.status})`);
  };

  return (
    <div className="flex items-center gap-1">
      <select value={agentId} onChange={e => setAgentId(e.target.value)}
        className="px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle}>
        <option value="">Install on…</option>
        {agents.map(a => <option key={a.id} value={a.id}>{a.slug}</option>)}
      </select>
      <button onClick={install} disabled={!agentId || busy}
        className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
        style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
        {busy ? <Loader2 className="animate-spin" size={12} /> : <Download size={12} />}
      </button>
    </div>
  );
}

function AddPluginForm({ tier, services, onDone, onError }: {
  tier: 'default' | 'supported'; services: ServiceLite[];
  onDone: () => void; onError: (m: string | null) => void;
}) {
  const [pluginName, setPluginName] = useState('');
  const [serviceSlug, setServiceSlug] = useState('');
  const [marketplaceUrl, setMarketplaceUrl] = useState('');
  const [saving, setSaving] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const inputStyle = { background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };

  const runSuggest = async (name: string) => {
    if (!name) return;
    const r = await fetch(`${CAT}/suggest?plugin_name=${encodeURIComponent(name)}`);
    if (!r.ok) return;
    const s = await r.json();
    if (!s.needs_review && services.some((x: ServiceLite) => x.slug === s.slug)) {
      setServiceSlug(s.slug);
      setHint(`Suggested service: ${s.display_name} (${s.upstream_url})`);
    } else {
      setHint(s.needs_review ? 'Unknown plugin — pick a service or add one in Key Registry.' : `Suggested service "${s.slug}" is not registered yet.`);
    }
  };

  const submit = async () => {
    setSaving(true); onError(null);
    const r = await fetch(CAT, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plugin_name: pluginName, tier, service_slug: serviceSlug || null, marketplace_url: marketplaceUrl || null }),
    });
    setSaving(false);
    if (r.ok) onDone();
    else onError((await r.json().catch(() => null))?.detail || `Failed (${r.status})`);
  };

  return (
    <div className="rounded-xl p-3 mb-3 space-y-2" style={{ background: 'var(--ink)', border: '1px solid var(--moon)' }}>
      <div className="flex items-center gap-2 flex-wrap">
        <input value={pluginName} onChange={e => setPluginName(e.target.value)} onBlur={e => runSuggest(e.target.value)}
          placeholder="plugin-monday" className="w-48 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} autoFocus />
        <select value={serviceSlug} onChange={e => setServiceSlug(e.target.value)}
          className="px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle}>
          <option value="">No key (pick service)</option>
          {services.map(s => <option key={s.slug} value={s.slug}>{s.display_name}</option>)}
        </select>
        <input value={marketplaceUrl} onChange={e => setMarketplaceUrl(e.target.value)}
          placeholder="marketplace url (optional)" className="flex-1 min-w-[160px] px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} />
        <button onClick={submit} disabled={saving || !pluginName}
          className="px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50" style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
          {saving ? <Loader2 className="animate-spin" size={12} /> : 'Add'}
        </button>
      </div>
      {hint && <p className="text-xs" style={{ color: 'var(--text-dim)' }}>{hint}</p>}
    </div>
  );
}
