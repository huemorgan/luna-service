import { useEffect, useState } from 'react';
import MarketplacePicker from './MarketplacePicker';
import type { CatalogPlugin } from './MarketplacePicker';
import PluginCard from './PluginCard';
import type { PluginKeying } from './pluginKeys';

export interface PluginSetEntry {
  name: string;
  version: string;
  sha256: string;
}

export type { CatalogPlugin };
export type { PluginKeying };

/**
 * Editor for the image-baked plugin set (Plan 020 + 026). Each included plugin
 * is an expandable card: collapsed shows a minimal line (name + version +
 * badges); expanded reveals the default-key binding and a version/upgrade row.
 * A marketplace search adds more. Used by the image Defaults page.
 */
export default function PluginSetEditor({
  value,
  onChange,
  keying,
}: {
  value: PluginSetEntry[];
  onChange: (next: PluginSetEntry[]) => void;
  keying?: PluginKeying;
}) {
  const [latest, setLatest] = useState<Record<string, CatalogPlugin>>({});
  const [expanded, setExpanded] = useState<string | null>(null);

  const included = value || [];
  const includedNames = new Set(included.map(e => e.name));

  // Full marketplace index (for per-plugin "update available" detection).
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/admin/marketplace/catalog');
        if (res.ok) {
          const data = await res.json();
          const map: Record<string, CatalogPlugin> = {};
          for (const p of data.plugins || []) map[p.name] = p;
          setLatest(map);
        }
      } catch { /* marketplace down — no upgrade hints, list still works */ }
    })();
  }, []);

  const add = (p: CatalogPlugin) => {
    if (!p.bakeable || includedNames.has(p.name)) return;
    onChange([...included, { name: p.name, version: p.version, sha256: p.sha256 }]);
  };

  const remove = (name: string) => {
    onChange(included.filter(e => e.name !== name));
  };

  const upgrade = (name: string) => {
    const l = latest[name];
    if (!l) return;
    onChange(included.map(e => e.name === name ? { name, version: l.version, sha256: l.sha256 } : e));
  };

  return (
    <div>
      {/* Included list — one grouped box of expandable plugin cards */}
      {included.length === 0 ? (
        <div className="text-xs py-2 mb-3" style={{ color: 'var(--text-dim)' }}>
          No plugins baked in. The build falls back to the{' '}
          <span className="font-mono">plugin-set.toml</span> seed.
        </div>
      ) : (
        <div className="rounded-xl border overflow-hidden mb-3" style={{ borderColor: 'var(--ink-lighter)' }}>
          {included.map((e, i) => (
            <PluginCard
              key={e.name}
              variant="baked"
              name={e.name}
              version={e.version}
              latest={latest[e.name]}
              keying={keying}
              keyServiceHint={latest[e.name]?.key_service}
              expanded={expanded === e.name}
              isLast={i === included.length - 1}
              onToggle={() => setExpanded(expanded === e.name ? null : e.name)}
              onRemove={() => remove(e.name)}
              onUpgrade={() => upgrade(e.name)}
            />
          ))}
        </div>
      )}

      {/* Search to add — baked set only takes bakeable plugins */}
      <MarketplacePicker excludeNames={includedNames} onPick={add} />
    </div>
  );
}
