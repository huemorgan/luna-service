import { ChevronDown, ChevronRight, ArrowUpCircle, Check, Info, Trash2, PackageOpen } from 'lucide-react';
import { KeyControls } from './pluginKeys';
import type { PluginKeying } from './pluginKeys';
import type { CatalogPlugin } from './MarketplacePicker';

/**
 * One expandable plugin row, shared by the Default plugin set (`variant="baked"`)
 * and the Supported plugins list (`variant="supported"`). Collapsed shows a
 * minimal line (name + badges); expanded reveals the default-key binding. The
 * only behavioural differences between the two lists:
 *  - baked: shows the pinned version + "update available → Update".
 *  - supported: shows a "not bundled" tag and a provisioned-on-install note,
 *    no version pin, and always offers the key control (binding is the point).
 */
export default function PluginCard({
  name, version, latest, keying, keyServiceHint, variant,
  expanded, isLast, onToggle, onRemove, onUpgrade,
}: {
  name: string;
  version?: string;
  latest?: CatalogPlugin;
  keying?: PluginKeying;
  keyServiceHint?: string | null;
  variant: 'baked' | 'supported';
  expanded: boolean;
  isLast: boolean;
  onToggle: () => void;
  onRemove: () => void;
  onUpgrade?: () => void;
}) {
  const supported = variant === 'supported';
  const catEntry = keying?.catalogByName[name] || null;
  const keyed = !!catEntry?.keyed;
  const hasUpdate = !supported && !!latest && !!version && latest.version !== version;

  // The service this plugin's key flows through.
  const keyService = keyServiceHint || latest?.key_service || catEntry?.service_slug || null;
  const svc = keyService ? keying?.services.find(s => s.slug === keyService) : undefined;
  const provisionable = !!svc && svc.enabled !== false;
  const svcLabel = svc?.display_name || titleCase(keyService || '');

  // Supported plugins always offer the key control (binding is the whole point).
  // Baked plugins only show it when they actually consume an external key.
  const needsKey = !!keying && (supported || !!keyService);
  const showKey = supported
    ? !!keying
    : needsKey && (provisionable || !!catEntry?.service_slug);

  // Scope the picker to the intended service when it's registered; otherwise let
  // the admin pick from any registered key service (supported), or fall through
  // to the no-provisioning hint (baked).
  const allowedSlugs = keyService && provisionable
    ? ([keyService, catEntry?.service_slug].filter(Boolean) as string[])
    : undefined;

  const noProvisionReason =
    `${name} needs a ${svcLabel} key, but there's no gateway provisioning for it yet — ` +
    `no enabled service is registered for "${keyService}".`;

  return (
    <div style={{ borderBottom: isLast ? undefined : '1px solid var(--ink-lighter)' }}>
      {/* Collapsed header */}
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        className="flex items-center gap-2.5 px-3.5 py-2.5 cursor-pointer"
        style={{ background: expanded ? 'var(--ink-light)' : 'transparent' }}
      >
        {expanded ? <ChevronDown size={15} style={{ color: 'var(--text-dim)' }} /> : <ChevronRight size={15} style={{ color: 'var(--text-dim)' }} />}
        <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{name}</span>
        {supported ? (
          <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'var(--ink)', color: 'var(--text-dim)' }} title="Not baked into the image — installed on demand">
            <PackageOpen size={10} /> not bundled
          </span>
        ) : (
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--ink)', color: 'var(--text-dim)' }}>
            v{version}
          </span>
        )}
        <div className="flex-1" />
        {hasUpdate && (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px]" style={{ background: 'rgba(122,162,255,0.15)', color: '#7aa2ff' }} title={`Update available: v${version} → v${latest!.version}`}>
            <ArrowUpCircle size={11} /> update
          </span>
        )}
        {showKey ? (keyed ? (
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
                pluginName={name}
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
                  No gateway provisioning yet — no enabled service for <span className="font-mono">{keyService}</span>. Register the service + a pool key first.
                </span>
              </div>
            </DetailRow>
          )}

          {supported && (
            <p className="text-[11px] leading-snug" style={{ color: 'var(--text-dim)' }}>
              Not bundled into the image. When a user installs this plugin, the bound key is
              provisioned by default.
            </p>
          )}

          {!supported && (
            <DetailRow label="Version">
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono" style={{ color: 'var(--text)' }}>v{version}</span>
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
          )}

          <div className="flex justify-end pt-1">
            <button
              onClick={onRemove}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium hover:opacity-80"
              style={{ color: '#ff6b6b', border: '1px solid rgba(255,107,107,0.3)' }}
            >
              <Trash2 size={12} /> {supported ? 'Remove from supported list' : 'Remove from set'}
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
