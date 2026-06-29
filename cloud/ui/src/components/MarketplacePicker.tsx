import { useEffect, useMemo, useRef, useState } from 'react';
import { Search, Plus, Lock, Loader2, KeyRound, Store, X } from 'lucide-react';

export interface CatalogPlugin {
  name: string;
  version: string;
  description: string;
  sha256: string;
  bakeable: boolean;
  key_service?: string | null;
}

/** Badges shared by the inline dropdown and the browse modal. */
function PluginBadges({ p, allowNonBakeable }: { p: CatalogPlugin; allowNonBakeable: boolean }) {
  return (
    <>
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
    </>
  );
}

/** Shared marketplace search + results dropdown (plan 027) and full-inventory
 *  browse modal (plan 030). Used by the Default plugin set (List A,
 *  bakeable-only) and the Supported plugins list (List B, allows non-bakeable
 *  connectors). On pick it hands back the chosen catalog entry plus the
 *  marketplace base url so the caller can wire an install / catalog binding. */
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
  const [browseOpen, setBrowseOpen] = useState(false);
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

  const pick = (p: CatalogPlugin, marketplaceUrl: string) => {
    if (excludeNames.has(p.name)) return;
    if (!allowNonBakeable && !p.bakeable) return;
    onPick(p, marketplaceUrl);
    setQuery('');
    setResults([]);
  };

  return (
    <div className="relative">
      <div className="flex items-center gap-2">
        <div
          className="flex items-center gap-2 rounded-lg px-3 py-2 flex-1"
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
        <button
          type="button"
          onClick={() => setBrowseOpen(true)}
          title="Browse the full marketplace"
          className="flex items-center justify-center rounded-lg px-3 py-2 transition-colors hover:scale-105"
          style={{ background: 'var(--ink-light)', border: '1px solid var(--ink-lighter)', color: 'var(--moon)' }}
        >
          <Store size={16} />
        </button>
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
                onClick={() => pick(p, marketplace)}
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
                    <PluginBadges p={p} allowNonBakeable={allowNonBakeable} />
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

      {browseOpen && (
        <BrowseModal
          excludeNames={excludeNames}
          allowNonBakeable={allowNonBakeable}
          onClose={() => setBrowseOpen(false)}
          onPick={pick}
        />
      )}
    </div>
  );
}

type KeyFilter = 'all' | 'needs' | 'none';

/** Full marketplace inventory popup (plan 030). Filterable; addable plugins on
 *  top, already-selected / unavailable greyed at the bottom. */
function BrowseModal({
  excludeNames,
  allowNonBakeable,
  onClose,
  onPick,
}: {
  excludeNames: Set<string>;
  allowNonBakeable: boolean;
  onClose: () => void;
  onPick: (plugin: CatalogPlugin, marketplaceUrl: string) => void;
}) {
  const [plugins, setPlugins] = useState<CatalogPlugin[]>([]);
  const [marketplace, setMarketplace] = useState('');
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [keyFilter, setKeyFilter] = useState<KeyFilter>('all');

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/admin/marketplace/catalog');
        if (res.ok) {
          const data = await res.json();
          setMarketplace(data.marketplace || '');
          setPlugins(data.plugins || []);
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const { available, unavailable } = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const matched = plugins.filter(p => {
      if (needle && !(p.name.toLowerCase().includes(needle) || (p.description || '').toLowerCase().includes(needle))) {
        return false;
      }
      if (keyFilter === 'needs' && !p.key_service) return false;
      if (keyFilter === 'none' && p.key_service) return false;
      return true;
    });
    const av: CatalogPlugin[] = [];
    const un: CatalogPlugin[] = [];
    for (const p of matched) {
      const already = excludeNames.has(p.name);
      const blockedBake = !allowNonBakeable && !p.bakeable;
      (already || blockedBake ? un : av).push(p);
    }
    return { available: av, unavailable: un };
  }, [plugins, filter, keyFilter, excludeNames, allowNonBakeable]);

  const FILTERS: { key: KeyFilter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'needs', label: 'Needs key' },
    { key: 'none', label: 'No key' },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center p-6 overflow-auto"
      style={{ background: 'rgba(0,0,0,0.6)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-2xl border my-10 flex flex-col"
        style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)', maxHeight: '80vh' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: 'var(--ink-lighter)' }}>
          <div className="flex items-center gap-2">
            <Store size={18} style={{ color: 'var(--moon)' }} />
            <span className="text-base font-semibold" style={{ color: 'var(--text)' }}>Marketplace</span>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg transition-colors hover:opacity-70" style={{ color: 'var(--text-dim)' }}>
            <X size={18} />
          </button>
        </div>

        {/* Filters */}
        <div className="px-5 py-3 border-b flex flex-wrap items-center gap-2" style={{ borderColor: 'var(--ink-lighter)' }}>
          <div
            className="flex items-center gap-2 rounded-lg px-3 py-2 flex-1 min-w-[200px]"
            style={{ background: 'var(--ink-light)', border: '1px solid var(--ink-lighter)' }}
          >
            <Search size={14} style={{ color: 'var(--text-dim)' }} />
            <input
              autoFocus
              type="text"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Filter plugins…"
              className="bg-transparent text-sm outline-none flex-1"
              style={{ color: 'var(--text)' }}
            />
          </div>
          <div className="flex items-center gap-1">
            {FILTERS.map(f => {
              const active = keyFilter === f.key;
              return (
                <button
                  key={f.key}
                  onClick={() => setKeyFilter(f.key)}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                  style={{
                    background: active ? 'var(--moon)' : 'var(--ink-light)',
                    color: active ? 'var(--ink)' : 'var(--text-dim)',
                    border: '1px solid var(--ink-lighter)',
                  }}
                >
                  {f.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Body */}
        <div className="overflow-auto px-2 py-2">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={20} className="animate-spin" style={{ color: 'var(--text-dim)' }} />
            </div>
          ) : (
            <>
              {available.length === 0 && unavailable.length === 0 && (
                <div className="text-xs px-3 py-8 text-center" style={{ color: 'var(--text-dim)' }}>
                  No plugins match.
                </div>
              )}
              {available.map(p => (
                <button
                  key={p.name}
                  onClick={() => onPick(p, marketplace)}
                  className="group w-full flex items-center justify-between px-3 py-2.5 text-left rounded-lg transition-colors hover:bg-[var(--ink-light)]"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{p.name}</span>
                      <PluginBadges p={p} allowNonBakeable={allowNonBakeable} />
                    </div>
                    {p.description && (
                      <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{p.description}</span>
                    )}
                  </div>
                  <Plus size={15} style={{ color: 'var(--moon)' }} />
                </button>
              ))}

              {unavailable.length > 0 && (
                <div className="px-3 pt-4 pb-1 text-[10px] font-semibold uppercase tracking-wide" style={{ color: 'var(--text-dim)' }}>
                  Already added / unavailable
                </div>
              )}
              {unavailable.map(p => {
                const already = excludeNames.has(p.name);
                return (
                  <div
                    key={p.name}
                    className="w-full flex items-center justify-between px-3 py-2.5 rounded-lg"
                    style={{ opacity: 0.45, cursor: 'not-allowed' }}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{p.name}</span>
                        <PluginBadges p={p} allowNonBakeable={allowNonBakeable} />
                      </div>
                      {p.description && (
                        <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{p.description}</span>
                      )}
                    </div>
                    <span className="text-[10px]" style={{ color: 'var(--text-dim)' }}>
                      {already ? 'added' : 'not bakeable'}
                    </span>
                  </div>
                );
              })}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
