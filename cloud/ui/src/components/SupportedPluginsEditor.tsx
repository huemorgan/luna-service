import { useState } from 'react';
import { CAT } from './pluginKeys';
import type { CatalogEntry, PluginKeying } from './pluginKeys';
import MarketplacePicker from './MarketplacePicker';
import type { CatalogPlugin } from './MarketplacePicker';
import PluginCard from './PluginCard';

/** List B (plan 026/027/028): opt-in plugins we offer with a default key even
 *  before a user installs them. Same expandable cards + default-key control as
 *  the baked Default set — the only difference is these are NOT bundled into the
 *  image. The binding is provisioned automatically when a user installs the
 *  plugin. No per-agent install action here. */
export default function SupportedPluginsEditor({
  entries, keying, onChanged, onError,
}: {
  entries: CatalogEntry[];
  keying: PluginKeying;
  onChanged: () => void;
  onError: (m: string | null) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
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
    if (r.ok || r.status === 409) onChanged();  // 409 = already in catalog
    else onError((await r.json().catch(() => null))?.detail || `Failed (${r.status})`);
  };

  const remove = async (name: string) => {
    if (!confirm(`Remove ${name} from the supported list?`)) return;
    if ((await fetch(`${CAT}/${name}`, { method: 'DELETE' })).ok) onChanged();
  };

  return (
    <div>
      {entries.length === 0 ? (
        <div className="text-xs py-2 mb-3" style={{ color: 'var(--text-dim)' }}>
          No supported plugins yet. Search the marketplace below to offer one with a default key.
        </div>
      ) : (
        <div className="rounded-xl border overflow-hidden mb-3" style={{ borderColor: 'var(--ink-lighter)' }}>
          {entries.map((e, i) => (
            <PluginCard
              key={e.plugin_name}
              variant="supported"
              name={e.plugin_name}
              keying={keying}
              keyServiceHint={e.service_slug || e.suggested?.slug || null}
              expanded={expanded === e.plugin_name}
              isLast={i === entries.length - 1}
              onToggle={() => setExpanded(expanded === e.plugin_name ? null : e.plugin_name)}
              onRemove={() => remove(e.plugin_name)}
            />
          ))}
        </div>
      )}

      {/* Search to add — supported list also offers non-bakeable connectors */}
      <MarketplacePicker
        excludeNames={includedNames}
        allowNonBakeable
        placeholder="Search the marketplace to offer a plugin…"
        onPick={add}
      />
    </div>
  );
}
