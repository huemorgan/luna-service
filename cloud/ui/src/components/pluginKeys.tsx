import { ShieldCheck, ShieldAlert } from 'lucide-react';

/** Shared plugin↔key catalog types + controls (plan 026).
 *  Used by the Default plugin set rows and the Supported plugins list on the
 *  Defaults page. The catalog is keyed by plugin_name; binding a service to a
 *  baked plugin creates a `default`-tier entry, the supported list owns
 *  `supported`-tier entries. */

export interface CatalogEntry {
  plugin_name: string;
  display_name: string;
  marketplace_url: string | null;
  category: string | null;
  tier: 'default' | 'supported';
  service_slug: string | null;
  key_mode: 'proxy' | 'env';
  suggested: { needs_review?: boolean; slug?: string } | null;
  enabled: boolean;
  keyed: boolean;
}

export interface ServiceLite { slug: string; display_name: string; key_count: number; enabled?: boolean }
export interface AgentLight { id: string; slug: string; name: string }

/** Per-row key binding wiring shared by the Default plugin set and the Supported
 *  plugins list. `catalogByName` maps a plugin to its catalog entry (if any). */
export interface PluginKeying {
  services: ServiceLite[];
  catalogByName: Record<string, CatalogEntry>;
  onBind: (pluginName: string, serviceSlug: string) => void;
  onMode: (pluginName: string, mode: 'proxy' | 'env') => void;
}

export const CAT = '/api/admin/plugin-catalog';
export const GW = '/api/admin/gateway';

const inputStyle = {
  background: 'var(--ink-light)', color: 'var(--text)', border: '1px solid var(--ink-lighter)',
};

/** Service picker + proxy/env mode + keyed badge for one plugin. `entry` may be
 *  null when the plugin has no catalog binding yet (baked plugins). */
export function KeyControls({ pluginName, entry, services, onBind, onMode, allowedSlugs }: {
  pluginName: string;
  entry: CatalogEntry | null;
  services: ServiceLite[];
  onBind: (pluginName: string, serviceSlug: string) => void;
  onMode: (pluginName: string, mode: 'proxy' | 'env') => void;
  // When set, the picker only offers these services (a connector plugin only
  // gets its own service, never unrelated keys like Anthropic). The currently
  // bound service is always kept so it stays visible/changeable.
  allowedSlugs?: string[];
}) {
  const slug = entry?.service_slug || '';
  const allowed = allowedSlugs
    ? services.filter(s => allowedSlugs.includes(s.slug) || s.slug === slug)
    : services;
  return (
    <div className="flex items-center gap-1.5">
      {slug && (entry?.keyed ? (
        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px]" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }} title="The bound service has an active pool key">
          <ShieldCheck size={11} /> keyed
        </span>
      ) : (
        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px]" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }} title="No active pool key for this service yet">
          <ShieldAlert size={11} /> no key
        </span>
      ))}

      <select
        value={slug}
        onChange={e => onBind(pluginName, e.target.value)}
        className="px-2.5 py-1.5 rounded-lg text-xs outline-none cursor-pointer"
        style={inputStyle}
        title="Default key: bind a gateway pool service"
      >
        <option value="">No key</option>
        {allowed.map(s => (
          <option key={s.slug} value={s.slug}>
            {s.display_name}{s.key_count ? ` (${s.key_count} key${s.key_count === 1 ? '' : 's'})` : ' — no keys'}
          </option>
        ))}
      </select>

      {slug && (
        <select
          value={entry?.key_mode || 'proxy'}
          onChange={e => onMode(pluginName, e.target.value as 'proxy' | 'env')}
          className="px-2.5 py-1.5 rounded-lg text-xs outline-none cursor-pointer"
          style={inputStyle}
          title="proxy: key stays server-side · env: real key injected on the machine"
        >
          <option value="proxy">proxy</option>
          <option value="env">env</option>
        </select>
      )}
    </div>
  );
}