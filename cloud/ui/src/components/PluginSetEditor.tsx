import { useEffect, useState } from 'react';
import { Trash2, ChevronDown, ChevronRight, ArrowUpCircle, Check, Info } from 'lucide-react';
import { KeyControls } from './pluginKeys';
import type { CatalogEntry, ServiceLite } from './pluginKeys';
import MarketplacePicker from './MarketplacePicker';
import type { CatalogPlugin } from './MarketplacePicker';

export interface PluginSetEntry {
  name: string;
  version: string;
  sha256: string;
}

export type { CatalogPlugin };

/** Optional per-row key binding (Defaults page). When provided, each baked
 *  plugin card also shows a service picker so admins set its default key here. */
export interface PluginKeying {
  services: ServiceLite[];
  catalogByName: Record<string, CatalogEntry>;
  onBind: (pluginName: string, serviceSlug: string) => void;
  onMode: (pluginName: string, mode: 'proxy' | 'env') => void;
}

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
              entry={e}
              latest={latest[e.name]}
              keying={keying}
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

function PluginCard({ entry, latest, keying, expanded, isLast, onToggle, onRemove, onUpgrade }: {
  entry: PluginSetEntry;
  latest?: CatalogPlugin;
  keying?: PluginKeying;
  expanded: boolean;
  isLast: boolean;
  onToggle: () => void;
  onRemove: () => void;
  onUpgrade: () => void;
}) {
  const catEntry = keying?.catalogByName[entry.name] || null;
  const keyed = !!catEntry?.keyed;
  const hasUpdate = !!latest && latest.version !== entry.version;
  // Only connector plugins that consume an external key get a key control, and
  // it's scoped to their own service. Leaf plugins (interview, charts…) show no
  // key at all. Fall back to any existing binding so old data stays editable.
  const keyService = latest?.key_service || catEntry?.service_slug || null;
  const needsKey = !!keying && !!keyService;
  // A keyed plugin is "provisionable" through the gateway only when an enabled
  // gateway service exists for it. Otherwise it needs a key but has no
  // provisioning path yet — we say so with an (i) instead of a dead dropdown.
  const svc = keyService ? keying?.services.find(s => s.slug === keyService) : undefined;
  const provisionable = !!svc && svc.enabled !== false;
  const svcLabel = svc?.display_name || titleCase(keyService || '');
  const noProvisionReason =
    `${entry.name} needs a ${svcLabel} key, but there's no gateway provisioning for it yet — ` +
    `no enabled service is registered for "${keyService}". It can't pool a key here until that ` +
    `service is set up and the plugin ships base-url proxy support (plan change-all-to-key-provisioning).`;
  const showKey = needsKey && (provisionable || !!catEntry?.service_slug);
  const allowedSlugs = [keyService, catEntry?.service_slug].filter(Boolean) as string[];

  return (
    <div style={{ borderBottom: isLast ? undefined : '1px solid var(--ink-lighter)' }}>
      {/* Collapsed header (minimal line) */}
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        className="flex items-center gap-2.5 px-3.5 py-2.5 cursor-pointer"
        style={{ background: expanded ? 'var(--ink-light)' : 'transparent' }}
      >
        {expanded ? <ChevronDown size={15} style={{ color: 'var(--text-dim)' }} /> : <ChevronRight size={15} style={{ color: 'var(--text-dim)' }} />}
        <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{entry.name}</span>
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--ink)', color: 'var(--text-dim)' }}>
          v{entry.version}
        </span>
        <div className="flex-1" />
        {hasUpdate && (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px]" style={{ background: 'rgba(122,162,255,0.15)', color: '#7aa2ff' }} title={`Update available: v${entry.version} → v${latest!.version}`}>
            <ArrowUpCircle size={11} /> update
          </span>
        )}
        {showKey && catEntry?.service_slug ? (keyed ? (
          <span className="px-2 py-0.5 rounded-full text-[10px]" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>keyed</span>
        ) : (
          <span className="px-2 py-0.5 rounded-full text-[10px]" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>no key</span>
        )) : needsKey && !provisionable ? (
          <span
            className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px]"
            style={{ background: 'rgba(250,204,21,0.12)', color: '#facc15' }}
            title={noProvisionReason}
          >
            needs key <Info size={10} />
          </span>
        ) : null}
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="px-3.5 pb-3.5 pt-1 space-y-3" style={{ background: 'var(--ink-light)' }}>
          {showKey && keying && (
            <DetailRow label="Default key">
              <KeyControls
                pluginName={entry.name}
                entry={catEntry}
                services={keying.services}
                onBind={keying.onBind}
                onMode={keying.onMode}
                allowedSlugs={allowedSlugs}
              />
            </DetailRow>
          )}

          {!showKey && needsKey && !provisionable && (
            <DetailRow label="Key">
              <div className="flex items-start gap-1.5 max-w-[420px]">
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] shrink-0" style={{ background: 'rgba(250,204,21,0.12)', color: '#facc15' }}>
                  needs {svcLabel} key
                </span>
                <span className="flex items-start gap-1 text-[11px] leading-snug" style={{ color: 'var(--text-dim)' }}>
                  <Info size={12} className="shrink-0 mt-0.5" />
                  No gateway provisioning yet — no enabled service for <span className="font-mono">{keyService}</span>. Register the service + a pool key and ship base-url proxy support before a key can be pooled here.
                </span>
              </div>
            </DetailRow>
          )}

          <DetailRow label="Version">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono" style={{ color: 'var(--text)' }}>v{entry.version}</span>
              {hasUpdate ? (
                <>
                  <span className="text-xs" style={{ color: 'var(--text-dim)' }}>→</span>
                  <span className="text-xs font-mono" style={{ color: '#7aa2ff' }}>v{latest!.version}</span>
                  <button
                    onClick={onUpgrade}
                    className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold"
                    style={{ background: 'var(--moon)', color: 'var(--ink)' }}
                  >
                    <ArrowUpCircle size={12} /> Update
                  </button>
                </>
              ) : (
                <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--text-dim)' }}>
                  <Check size={12} style={{ color: '#22c55e' }} /> up to date
                </span>
              )}
            </div>
          </DetailRow>

          <div className="flex justify-end pt-1">
            <button
              onClick={onRemove}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium hover:opacity-80"
              style={{ color: '#ff6b6b', border: '1px solid rgba(255,107,107,0.3)' }}
            >
              <Trash2 size={12} /> Remove from set
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function titleCase(slug: string): string {
  return slug.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 flex-wrap">
      <span className="text-xs font-medium" style={{ color: 'var(--text-dim)' }}>{label}</span>
      {children}
    </div>
  );
}
