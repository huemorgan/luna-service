import { useState } from 'react';
import { Plus, Trash2, Loader2 } from 'lucide-react';
import { KeyControls, InstallControl, CAT } from './pluginKeys';
import type { CatalogEntry, ServiceLite, AgentLight } from './pluginKeys';

/** List B (plan 026): opt-in plugins we support with a default key even before a
 *  user installs them. Add by name (the suggester pre-fills the service), bind a
 *  pool key, then install onto an agent to provision it. Lives on the Defaults
 *  page next to the baked plugin set. */
export default function SupportedPluginsEditor({
  entries, services, agents, onBind, onMode, onChanged, onError,
}: {
  entries: CatalogEntry[];
  services: ServiceLite[];
  agents: AgentLight[];
  onBind: (pluginName: string, serviceSlug: string) => void;
  onMode: (pluginName: string, mode: 'proxy' | 'env') => void;
  onChanged: () => void;
  onError: (m: string | null) => void;
}) {
  const [showAdd, setShowAdd] = useState(false);

  const remove = async (name: string) => {
    if (!confirm(`Remove ${name} from the supported list?`)) return;
    if ((await fetch(`${CAT}/${name}`, { method: 'DELETE' })).ok) onChanged();
  };

  return (
    <div>
      <div className="flex items-center justify-end mb-3">
        <button
          onClick={() => setShowAdd(v => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold"
          style={{ background: 'var(--ink-light)', color: 'var(--moon)', border: '1px solid var(--ink-lighter)' }}
        >
          <Plus size={13} /> Add supported plugin
        </button>
      </div>

      {showAdd && (
        <AddPluginForm services={services}
          onDone={() => { setShowAdd(false); onChanged(); }} onError={onError} />
      )}

      {entries.length === 0 && !showAdd && (
        <p className="text-xs py-1" style={{ color: 'var(--text-dim)' }}>
          No supported plugins yet. Add one to offer it with a default key.
        </p>
      )}

      <div>
        {entries.map((e, i) => (
          <div
            key={e.plugin_name}
            className="flex items-center justify-between py-2.5 gap-3 flex-wrap"
            style={{ borderBottom: i === entries.length - 1 ? undefined : '1px solid var(--ink-lighter)' }}
          >
            <div className="min-w-0">
              <div className="text-sm font-medium" style={{ color: 'var(--text)' }}>{e.display_name}</div>
              <div className="text-xs" style={{ color: 'var(--text-dim)' }}>
                {e.plugin_name}{e.category ? ` · ${e.category}` : ''}
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <KeyControls pluginName={e.plugin_name} entry={e} services={services} onBind={onBind} onMode={onMode} />
              <InstallControl plugin={e.plugin_name} agents={agents} onError={onError} />
              <button onClick={() => remove(e.plugin_name)} className="p-1.5 rounded-lg hover:opacity-80" style={{ color: '#ef4444' }} title="Remove from supported list">
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AddPluginForm({ services, onDone, onError }: {
  services: ServiceLite[]; onDone: () => void; onError: (m: string | null) => void;
}) {
  const [pluginName, setPluginName] = useState('');
  const [serviceSlug, setServiceSlug] = useState('');
  const [marketplaceUrl, setMarketplaceUrl] = useState('');
  const [saving, setSaving] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const inputStyle = { background: 'var(--ink-light)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };

  const runSuggest = async (name: string) => {
    if (!name) return;
    const r = await fetch(`${CAT}/suggest?plugin_name=${encodeURIComponent(name)}`);
    if (!r.ok) return;
    const s = await r.json();
    if (!s.needs_review && services.some(x => x.slug === s.slug)) {
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
      body: JSON.stringify({ plugin_name: pluginName, tier: 'supported', service_slug: serviceSlug || null, marketplace_url: marketplaceUrl || null }),
    });
    setSaving(false);
    if (r.ok) onDone();
    else onError((await r.json().catch(() => null))?.detail || `Failed (${r.status})`);
  };

  return (
    <div className="rounded-xl p-3 mb-3 space-y-2" style={{ background: 'var(--ink-light)', border: '1px solid var(--moon)' }}>
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
