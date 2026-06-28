import { useEffect, useRef, useState } from 'react';
import { Search, Plus, Lock, Loader2, KeyRound } from 'lucide-react';

export interface CatalogPlugin {
  name: string;
  version: string;
  description: string;
  sha256: string;
  bakeable: boolean;
  key_service?: string | null;
}

/** Shared marketplace search + results dropdown (plan 027).
 *  Used by the Default plugin set (List A, bakeable-only) and the Supported
 *  plugins list (List B, allows non-bakeable connectors). On pick it hands back
 *  the chosen catalog entry plus the marketplace base url so the caller can wire
 *  an install / catalog binding. */
export default function MarketplacePicker({
  excludeNames,
  allowNonBakeable = false,
  placeholder = 'Search the marketplace to add a plugin…',
  onPick,
}: {
  excludeNames: Set<string>;
  allowNonBakeable?: boolean;
  placeholder?: string;
  onPick: (plugin: CatalogPlugin, marketplaceUrl: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CatalogPlugin[]>([]);
  const [marketplace, setMarketplace] = useState('');
  const [searching, setSearching] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout>>(undefined);

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
          setMarketplace(data.marketplace || '');
          setResults((data.plugins || []).slice(0, 8));
        }
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(debounce.current);
  }, [query]);

  const pick = (p: CatalogPlugin) => {
    if (excludeNames.has(p.name)) return;
    if (!allowNonBakeable && !p.bakeable) return;
    onPick(p, marketplace);
    setQuery('');
    setResults([]);
  };

  return (
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
          placeholder={placeholder}
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
            const already = excludeNames.has(p.name);
            const blockedBake = !allowNonBakeable && !p.bakeable;
            const disabled = blockedBake || already;
            return (
              <button
                key={p.name}
                onClick={() => pick(p)}
                disabled={disabled}
                className="w-full flex items-center justify-between px-3 py-2.5 text-left transition-colors"
                style={{
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  opacity: blockedBake ? 0.55 : 1,
                  borderTop: '1px solid var(--ink-lighter)',
                }}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{p.name}</span>
                    <span
                      className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                      style={{ background: 'var(--ink-light)', color: 'var(--text-dim)' }}
                    >
                      v{p.version}
                    </span>
                    {p.key_service ? (
                      <span
                        className="flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded font-medium"
                        style={{ background: 'rgba(122,162,255,0.12)', color: '#7aa2ff' }}
                        title={`Provisions the ${p.key_service} gateway key`}
                      >
                        <KeyRound size={8} /> {p.key_service} key
                      </span>
                    ) : (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                        style={{ background: 'var(--ink-light)', color: 'var(--text-dim)' }}
                        title="No external key needed"
                      >
                        no key needed
                      </span>
                    )}
                    {!p.bakeable && (
                      <span
                        className="flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded font-medium"
                        style={{ background: 'rgba(250,204,21,0.1)', color: '#facc15' }}
                      >
                        <Lock size={8} /> connector{allowNonBakeable ? '' : ' — not bakeable'}
                      </span>
                    )}
                  </div>
                  {p.description && (
                    <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{p.description}</span>
                  )}
                </div>
                {already ? (
                  <span className="text-[10px]" style={{ color: 'var(--text-dim)' }}>added</span>
                ) : !disabled ? (
                  <Plus size={14} style={{ color: 'var(--moon)' }} />
                ) : null}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
