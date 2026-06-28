import { Trash2 } from 'lucide-react';
import { KeyControls, InstallControl, CAT } from './pluginKeys';
import type { CatalogEntry, ServiceLite, AgentLight } from './pluginKeys';
import MarketplacePicker from './MarketplacePicker';
import type { CatalogPlugin } from './MarketplacePicker';

/** List B (plan 026/027): opt-in plugins we support with a default key even
 *  before a user installs them. Add straight from the marketplace (same picker
 *  as the baked set) — the server suggester binds the key service from the
 *  plugin's manifest. Then bind/confirm the key and install onto an agent. */
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
  const includedNames = new Set(entries.map(e => e.plugin_name));

  const add = async (p: CatalogPlugin, marketplaceUrl: string) => {
    onError(null);
    // Let the server suggester fill service_slug from the plugin's key_service.
    const r = await fetch(CAT, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        plugin_name: p.name,
        display_name: p.name,
        tier: 'supported',
        marketplace_url: marketplaceUrl || null,
        service_slug: null,
      }),
    });
    if (r.ok) onChanged();
    else if (r.status === 409) onChanged(); // already in catalog — just refresh
    else onError((await r.json().catch(() => null))?.detail || `Failed (${r.status})`);
  };

  const remove = async (name: string) => {
    if (!confirm(`Remove ${name} from the supported list?`)) return;
    if ((await fetch(`${CAT}/${name}`, { method: 'DELETE' })).ok) onChanged();
  };

  return (
    <div>
      <MarketplacePicker
        excludeNames={includedNames}
        allowNonBakeable
        placeholder="Search the marketplace to offer a plugin…"
        onPick={add}
      />

      {entries.length === 0 && (
        <p className="text-xs py-2 mt-1" style={{ color: 'var(--text-dim)' }}>
          No supported plugins yet. Search the marketplace above to offer one with a default key.
        </p>
      )}

      <div className="mt-2">
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
