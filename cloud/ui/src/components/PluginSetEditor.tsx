import { useEffect, useRef, useState } from 'react';
import { Search, Trash2, Plus, Lock, Loader2 } from 'lucide-react';
import { KeyControls } from './pluginKeys';
import type { CatalogEntry, ServiceLite } from './pluginKeys';

export interface PluginSetEntry {
  name: string;
  version: string;
  sha256: string;
}

/** Optional per-row key binding (Defaults page). When provided, each baked
 *  plugin row also shows a service picker so admins set its default key here. */
export interface PluginKeying {
  services: ServiceLite[];
  catalogByName: Record<string, CatalogEntry>;
  onBind: (pluginName: string, serviceSlug: string) => void;
  onMode: (pluginName: string, mode: 'proxy' | 'env') => void;
}

export interface CatalogPlugin {
  name: string;
  version: string;
  description: string;
  sha256: string;
  bakeable: boolean;
}

/**
 * Shared editor for the image-baked plugin set (Plan 020). Shows the *included*
 * plugins with a remove control, plus a marketplace search to add more — instead
 * of listing the whole catalog with on/off toggles. Used by the per-image config
 * and the image Defaults page.
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
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CatalogPlugin[]>([]);
  const [searching, setSearching] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout>>(undefined);

  const included = value || [];
  const includedNames = new Set(included.map(e => e.name));

  useEffect(() => {
    clearTimeout(debounce.current);
    const q = query.trim();
    if (!q) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    debounce.current = setTimeout(async () => {
      try {
        const res = await fetch(`/api/admin/marketplace/catalog?q=${encodeURIComponent(q)}`);
        if (res.ok) {
          const data = await res.json();
          setResults((data.plugins || []).slice(0, 8));
        }
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(debounce.current);
  }, [query]);

  const add = (p: CatalogPlugin) => {
    if (!p.bakeable || includedNames.has(p.name)) return;
    onChange([...included, { name: p.name, version: p.version, sha256: p.sha256 }]);
    setQuery('');
    setResults([]);
  };

  const remove = (name: string) => {
    onChange(included.filter(e => e.name !== name));
  };

  return (
    <div>
      {/* Included list */}
      {included.length === 0 ? (
        <div className="text-xs py-2 mb-1" style={{ color: 'var(--text-dim)' }}>
          No plugins baked in. The build falls back to the{' '}
          <span className="font-mono">plugin-set.toml</span> seed.
        </div>
      ) : (
        <div className="mb-3">
          {included.map((e, i) => (
            <div
              key={e.name}
              className="flex items-center justify-between py-2.5"
              style={{
                borderBottom: i === included.length - 1 ? undefined : '1px solid var(--ink-lighter)',
              }}
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{e.name}</span>
                <span
                  className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                  style={{ background: 'var(--ink-light)', color: 'var(--text-dim)' }}
                >
                  v{e.version}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {keying && (
                  <KeyControls
                    pluginName={e.name}
                    entry={keying.catalogByName[e.name] || null}
                    services={keying.services}
                    onBind={keying.onBind}
                    onMode={keying.onMode}
                  />
                )}
                <button
                  onClick={() => remove(e.name)}
                  className="p-1.5 rounded-lg transition-colors hover:opacity-80"
                  style={{ color: '#ef4444' }}
                  title={`Remove ${e.name}`}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Search to add */}
      <div className="relative">
        <div
          className="flex items-center gap-2 rounded-lg px-3 py-2"
          style={{ background: 'var(--ink-light)', border: '1px solid var(--ink-lighter)' }}
        >
          {searching
            ? <Loader2 size={14} className="animate-spin" style={{ color: 'var(--text-dim)' }} />
            : <Search size={14} style={{ color: 'var(--text-dim)' }} />}
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search the marketplace to add a plugin…"
            className="bg-transparent text-sm outline-none flex-1"
            style={{ color: 'var(--text)' }}
          />
        </div>

        {query.trim() && (
          <div
            className="mt-1 rounded-lg border overflow-hidden"
            style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}
          >
            {results.length === 0 && !searching && (
              <div className="text-xs px-3 py-2.5" style={{ color: 'var(--text-dim)' }}>
                No matches.
              </div>
            )}
            {results.map(p => {
              const already = includedNames.has(p.name);
              const disabled = !p.bakeable || already;
              return (
                <button
                  key={p.name}
                  onClick={() => add(p)}
                  disabled={disabled}
                  className="w-full flex items-center justify-between px-3 py-2.5 text-left transition-colors"
                  style={{
                    cursor: disabled ? 'not-allowed' : 'pointer',
                    opacity: p.bakeable ? 1 : 0.55,
                    borderTop: '1px solid var(--ink-lighter)',
                  }}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{p.name}</span>
                      <span
                        className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                        style={{ background: 'var(--ink-light)', color: 'var(--text-dim)' }}
                      >
                        v{p.version}
                      </span>
                      {!p.bakeable && (
                        <span
                          className="flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded font-medium"
                          style={{ background: 'rgba(250,204,21,0.1)', color: '#facc15' }}
                        >
                          <Lock size={8} /> connector — not bakeable
                        </span>
                      )}
                    </div>
                    {p.description && (
                      <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{p.description}</span>
                    )}
                  </div>
                  {already ? (
                    <span className="text-[10px]" style={{ color: 'var(--text-dim)' }}>added</span>
                  ) : p.bakeable ? (
                    <Plus size={14} style={{ color: 'var(--moon)' }} />
                  ) : null}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
