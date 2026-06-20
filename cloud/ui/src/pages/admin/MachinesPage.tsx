import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  Server, Loader2, RefreshCw, ArrowUpCircle, ChevronDown, ChevronRight,
  Settings, Webhook, Layers, Plus, Trash2, Check, Cable, Brain,
} from 'lucide-react';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ModelEntry {
  provider: string;
  model: string;
}

interface Machine {
  agent_id: string;
  agent_name: string;
  agent_slug: string;
  agent_status: string;
  machine_id: string | null;
  runtime_kind: string | null;
  image_version: string | null;
  fly_state: string | null;
  fly_region: string | null;
  fly_image: string | null;
  fly_created_at: string | null;
  composio_accounts_mode: 'hosted' | 'user' | 'both';
  composio_accounts_mode_override: 'hosted' | 'user' | 'both' | null;
  // Plan 017.1 — per-machine model override
  primary_model: ModelEntry;
  fast_model: ModelEntry;
  primary_model_override: ModelEntry | null;
  fast_model_override: ModelEntry | null;
}

interface ImageOption {
  id: string;
  version: string;
  is_main: boolean;
  build_status: string;
  git_branch: string | null;
  built_at: string | null;
  created_at: string | null;
}

// Plan 018: model options come from the system catalog (/api/admin/gateway/models),
// not a hardcoded list, so they can never drift from what the proxy actually serves.
interface CatalogModel {
  provider: string;
  model: string;
  label: string | null;
  kinds: ('reasoning' | 'summarization' | 'embedding')[];
  enabled: boolean;
  recommended_default: boolean;
  deprecated: boolean;
}


interface Delivery {
  id: string;
  webhook_id: string;
  connected_account_id: string | null;
  agent_slug: string | null;
  status: string;
  attempts: number;
  last_status_code: number | null;
  last_error: string | null;
  created_at: string | null;
  delivered_at: string | null;
  next_attempt_at: string | null;
}

interface AccountLink {
  connected_account_id: string;
  agent_slug: string | null;
  app_name: string | null;
  source: string;
  created_at: string | null;
  last_seen_at: string | null;
}

const STATE_COLORS: Record<string, string> = {
  started: '#22c55e',
  running: '#22c55e',
  stopped: '#94a3b8',
  suspended: '#94a3b8',
  created: '#facc15',
  destroying: '#ef4444',
  destroyed: '#ef4444',
};

const DELIVERY_STATUS_COLORS: Record<string, string> = {
  delivered: '#22c55e',
  pending: '#eab308',
  unroutable: '#f97316',
  dead: '#ef4444',
};

function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

type TabKey = 'overview' | 'settings' | 'webhooks';

const TABS: { key: TabKey; label: string; icon: React.ElementType }[] = [
  { key: 'overview', label: 'Overview', icon: Layers },
  { key: 'settings', label: 'Settings', icon: Settings },
  { key: 'webhooks', label: 'Webhooks', icon: Webhook },
];

/* ------------------------------------------------------------------ */
/*  Connectors plugin section (Settings tab)                          */
/* ------------------------------------------------------------------ */

interface ModeOption {
  value: 'inherit' | 'hosted' | 'user' | 'both';
  label: string;
  description: string;
}

function ConnectorsPluginSection({
  machine, busy, onChange,
}: {
  machine: Machine;
  busy: boolean;
  onChange: (value: 'inherit' | 'hosted' | 'user' | 'both') => void;
}) {
  const current: ModeOption['value'] =
    machine.composio_accounts_mode_override ?? 'inherit';

  const options: ModeOption[] = [
    {
      value: 'inherit',
      label: `Inherit image default (${machine.composio_accounts_mode})`,
      description:
        'Use whatever the image config says. This is the safest default — change the image config to roll it out to every machine at once.',
    },
    {
      value: 'hosted',
      label: 'Hosted only',
      description:
        "The user sees one Composio tab labeled 'Included with Luna Cloud' and uses our shared key. They cannot enter their own.",
    },
    {
      value: 'user',
      label: 'User-provided only',
      description:
        'The user must paste their own Composio API key. No hosted tab is shown. Useful for BYO-account customers.',
    },
    {
      value: 'both',
      label: 'Both',
      description:
        'Both tabs are visible. The user can pick the hosted Luna key or paste their own.',
    },
  ];

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ background: 'var(--ink)', borderColor: 'var(--ink-lighter)' }}
    >
      <div
        className="flex items-center gap-2 px-4 py-3 border-b"
        style={{ borderColor: 'var(--ink-lighter)' }}
      >
        <Cable size={14} style={{ color: 'var(--moon)' }} />
        <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
          Connectors plugin (Composio)
        </span>
      </div>
      <div className="px-4 py-3">
        <p className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>
          Controls how the connectors plugin lets this Luna talk to Composio.
          The plugin renders one tab per allowed account source in the agent's
          Settings → Connectors page.
        </p>
        <div
          className="rounded-lg overflow-hidden"
          style={{ border: '1px solid var(--ink-lighter)', opacity: busy ? 0.6 : 1 }}
        >
          {options.map((opt, i) => {
            const selected = current === opt.value;
            return (
              <label
                key={opt.value}
                className="flex items-start gap-3 px-3 py-2.5 cursor-pointer transition-colors"
                style={{
                  background: selected ? 'rgba(201,184,255,0.08)' : 'transparent',
                  borderTop: i === 0 ? 'none' : '1px solid var(--ink-lighter)',
                }}
              >
                <input
                  type="radio"
                  name={`mode-${machine.agent_id}`}
                  value={opt.value}
                  checked={selected}
                  disabled={busy}
                  onChange={() => onChange(opt.value)}
                  className="mt-0.5"
                  style={{ accentColor: 'var(--moon)' }}
                />
                <div className="min-w-0">
                  <div className="text-sm font-medium" style={{ color: 'var(--text)' }}>
                    {opt.label}
                  </div>
                  <div className="text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>
                    {opt.description}
                  </div>
                </div>
              </label>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Models section (Settings tab)                                      */
/* ------------------------------------------------------------------ */

function ModelsSection({
  machine, busy, catalog, onChange,
}: {
  machine: Machine;
  busy: boolean;
  catalog: CatalogModel[];
  onChange: (role: 'primary' | 'fast', value: string) => void;
}) {
  // The API returns the override AS the resolved value (override wins), so we
  // can't show the image default separately without another fetch. Keep the UI
  // honest: dropdown reflects what's effective, "override" hint shows when
  // it's a per-machine choice vs. the image default.
  const renderRow = (
    role: 'primary' | 'fast',
    title: string,
    description: string,
    resolved: ModelEntry,
    override: ModelEntry | null,
  ) => {
    const kind = role === 'primary' ? 'reasoning' : 'summarization';
    const kindModels = catalog.filter(m => m.enabled && m.kinds.includes(kind));
    const selectValue = override ? `${override.provider}:${override.model}` : 'inherit';
    return (
      <div className="py-3" style={{ borderTop: '1px solid var(--ink-lighter)' }}>
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{title}</span>
              {override && (
                <span className="text-[10px] px-1.5 py-0.5 rounded" style={{
                  background: 'rgba(201,184,255,0.15)', color: 'var(--moon)',
                }}>override</span>
              )}
            </div>
            <div className="text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>{description}</div>
            <div className="text-[11px] mt-1 font-mono" style={{ color: 'var(--text-dim)' }}>
              currently: {resolved.provider}:{resolved.model}
            </div>
          </div>
          <select
            value={selectValue}
            disabled={busy}
            onChange={e => onChange(role, e.target.value)}
            className="rounded-lg px-2.5 py-1.5 text-xs outline-none disabled:opacity-50"
            style={{
              background: 'var(--ink-light)',
              color: 'var(--text)',
              border: '1px solid var(--ink-lighter)',
              minWidth: 220,
            }}
          >
            <option value="inherit">Inherit image / catalog default</option>
            {kindModels.map(m => (
              <option key={`${m.provider}:${m.model}`} value={`${m.provider}:${m.model}`}>
                {m.provider} — {m.label || m.model}{m.recommended_default ? ' (default)' : ''}
              </option>
            ))}
          </select>
        </div>
      </div>
    );
  };

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ background: 'var(--ink)', borderColor: 'var(--ink-lighter)' }}
    >
      <div
        className="flex items-center gap-2 px-4 py-3 border-b"
        style={{ borderColor: 'var(--ink-lighter)' }}
      >
        <Brain size={14} style={{ color: 'var(--moon)' }} />
        <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
          Models
        </span>
      </div>
      <div className="px-4 pb-3">
        <p className="text-xs mt-3" style={{ color: 'var(--text-dim)' }}>
          Override the model selection just for this machine. Sets
          <span className="font-mono"> LUNA_PRIMARY_MODEL </span>
          and
          <span className="font-mono"> LUNA_FAST_MODEL </span>
          on the running Fly machine.
        </p>
        {renderRow(
          'primary',
          'Top model',
          'Heavy reasoning, tool use, primary chat. Higher cost.',
          machine.primary_model,
          machine.primary_model_override,
        )}
        {renderRow(
          'fast',
          'Fast model',
          'Cheap, low-latency. Used for summaries, classifications, lightweight calls.',
          machine.fast_model,
          machine.fast_model_override,
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Webhooks tab                                                       */
/* ------------------------------------------------------------------ */

function WebhooksTab({
  machine, links, deliveries, onChange,
}: {
  machine: Machine;
  links: AccountLink[];
  deliveries: Delivery[];
  onChange: () => void;
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [newAccount, setNewAccount] = useState('');
  const [newApp, setNewApp] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleAdd = async () => {
    setError(null);
    const res = await fetch('/api/admin/relay/links', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        connected_account_id: newAccount.trim(),
        agent_slug: machine.agent_slug,
        app_name: newApp.trim() || null,
      }),
    });
    if (res.ok) {
      setNewAccount(''); setNewApp(''); setShowAdd(false);
      onChange();
    } else {
      const body = await res.json().catch(() => null);
      setError(body?.detail || `Failed (${res.status})`);
    }
  };

  const handleDelete = async (accountId: string) => {
    const res = await fetch(`/api/admin/relay/links/${encodeURIComponent(accountId)}`, {
      method: 'DELETE',
    });
    if (res.ok) onChange();
  };

  return (
    <div className="space-y-4">
      {/* Account links */}
      <div
        className="rounded-xl border overflow-hidden"
        style={{ background: 'var(--ink)', borderColor: 'var(--ink-lighter)' }}
      >
        <div
          className="flex items-center justify-between px-4 py-3 border-b"
          style={{ borderColor: 'var(--ink-lighter)' }}
        >
          <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
            Account links <span className="font-normal" style={{ color: 'var(--text-dim)' }}>({links.length})</span>
          </span>
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors hover:opacity-80"
            style={{ background: 'var(--moon)', color: 'var(--ink)' }}
          >
            <Plus size={11} /> Add link
          </button>
        </div>

        {showAdd && (
          <div className="px-4 py-3 border-b flex flex-wrap items-end gap-3" style={{ borderColor: 'var(--ink-lighter)' }}>
            <label className="flex flex-col gap-1 text-[11px]" style={{ color: 'var(--text-dim)' }}>
              Connected account ID
              <input
                value={newAccount}
                onChange={e => setNewAccount(e.target.value)}
                placeholder="ca_…"
                className="px-2.5 py-1.5 rounded-lg text-xs outline-none"
                style={{ background: 'var(--ink-light)', border: '1px solid var(--ink-lighter)', color: 'var(--text)', minWidth: 200 }}
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px]" style={{ color: 'var(--text-dim)' }}>
              Agent slug
              <input
                value={machine.agent_slug}
                disabled
                className="px-2.5 py-1.5 rounded-lg text-xs"
                style={{ background: 'var(--ink-light)', border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px]" style={{ color: 'var(--text-dim)' }}>
              App (optional)
              <input
                value={newApp}
                onChange={e => setNewApp(e.target.value)}
                placeholder="gmail"
                className="px-2.5 py-1.5 rounded-lg text-xs outline-none"
                style={{ background: 'var(--ink-light)', border: '1px solid var(--ink-lighter)', color: 'var(--text)' }}
              />
            </label>
            <button
              onClick={handleAdd}
              disabled={!newAccount.trim()}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all hover:scale-105 disabled:opacity-50"
              style={{ background: 'var(--moon)', color: 'var(--ink)' }}
            >
              Save
            </button>
            {error && <span className="text-[11px]" style={{ color: '#ef4444' }}>{error}</span>}
          </div>
        )}

        {links.length === 0 ? (
          <div className="px-4 py-6 text-center text-xs" style={{ color: 'var(--text-dim)' }}>
            No account links yet. They're captured automatically the first time
            this agent connects something through Composio.
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--ink-lighter)' }}>
                <th className="text-left text-[11px] font-medium px-4 py-2" style={{ color: 'var(--text-dim)' }}>Connected Account</th>
                <th className="text-left text-[11px] font-medium px-4 py-2" style={{ color: 'var(--text-dim)' }}>App</th>
                <th className="text-left text-[11px] font-medium px-4 py-2" style={{ color: 'var(--text-dim)' }}>Source</th>
                <th className="text-left text-[11px] font-medium px-4 py-2" style={{ color: 'var(--text-dim)' }}>Last Seen</th>
                <th className="text-right text-[11px] font-medium px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {links.map(l => (
                <tr key={l.connected_account_id} className="border-t" style={{ borderColor: 'var(--ink-lighter)' }}>
                  <td className="px-4 py-2 text-xs font-mono" style={{ color: 'var(--text)' }}>{l.connected_account_id}</td>
                  <td className="px-4 py-2 text-xs" style={{ color: 'var(--text-dim)' }}>{l.app_name || '—'}</td>
                  <td className="px-4 py-2 text-xs" style={{ color: 'var(--text-dim)' }}>{l.source}</td>
                  <td className="px-4 py-2 text-xs" style={{ color: 'var(--text-dim)' }}>{fmtTime(l.last_seen_at)}</td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => handleDelete(l.connected_account_id)}
                      className="p-1 rounded transition-all hover:scale-110"
                      style={{ color: '#ef4444' }}
                      title="Delete link"
                    >
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Deliveries */}
      <div
        className="rounded-xl border overflow-hidden"
        style={{ background: 'var(--ink)', borderColor: 'var(--ink-lighter)' }}
      >
        <div
          className="px-4 py-3 border-b"
          style={{ borderColor: 'var(--ink-lighter)' }}
        >
          <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
            Recent deliveries <span className="font-normal" style={{ color: 'var(--text-dim)' }}>({deliveries.length})</span>
          </span>
        </div>
        {deliveries.length === 0 ? (
          <div className="px-4 py-6 text-center text-xs" style={{ color: 'var(--text-dim)' }}>
            No webhook deliveries for this agent yet.
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--ink-lighter)' }}>
                <th className="text-left text-[11px] font-medium px-4 py-2" style={{ color: 'var(--text-dim)' }}>Status</th>
                <th className="text-left text-[11px] font-medium px-4 py-2" style={{ color: 'var(--text-dim)' }}>Connected Account</th>
                <th className="text-left text-[11px] font-medium px-4 py-2" style={{ color: 'var(--text-dim)' }}>Attempts</th>
                <th className="text-left text-[11px] font-medium px-4 py-2" style={{ color: 'var(--text-dim)' }}>Received</th>
              </tr>
            </thead>
            <tbody>
              {deliveries.slice(0, 10).map(d => (
                <tr key={d.id} className="border-t" style={{ borderColor: 'var(--ink-lighter)' }}>
                  <td className="px-4 py-2">
                    <span
                      className="text-[11px] px-2 py-0.5 rounded-full font-medium"
                      style={{
                        color: DELIVERY_STATUS_COLORS[d.status] || 'var(--text-dim)',
                        background: `${DELIVERY_STATUS_COLORS[d.status] || '#888'}22`,
                      }}
                      title={d.last_error || undefined}
                    >
                      {d.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs font-mono" style={{ color: 'var(--text-dim)' }}>{d.connected_account_id || '—'}</td>
                  <td className="px-4 py-2 text-xs" style={{ color: 'var(--text-dim)' }}>{d.attempts}</td>
                  <td className="px-4 py-2 text-xs" style={{ color: 'var(--text-dim)' }}>{fmtTime(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Machine card                                                       */
/* ------------------------------------------------------------------ */

function MachineCard({
  machine, links, deliveries, busy, catalog, images, onUpdateImage, onSetMode, onSetModel, onWebhooksChange,
}: {
  machine: Machine;
  links: AccountLink[];
  deliveries: Delivery[];
  busy: boolean;
  catalog: CatalogModel[];
  images: ImageOption[];
  onUpdateImage: (imageId: string) => void;
  onSetMode: (value: 'inherit' | 'hosted' | 'user' | 'both') => void;
  onSetModel: (role: 'primary' | 'fast', value: string) => void;
  onWebhooksChange: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const hasOverride =
    !!machine.composio_accounts_mode_override
    || !!machine.primary_model_override
    || !!machine.fast_model_override;

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{
        background: 'var(--surface)',
        borderColor: hasOverride ? 'var(--moon)' : 'var(--ink-lighter)',
        boxShadow: hasOverride ? '0 0 20px rgba(201,184,255,0.08)' : 'none',
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-5 py-4 cursor-pointer select-none"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-4 min-w-0">
          <div
            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
            style={{ background: STATE_COLORS[machine.fly_state || ''] || '#94a3b8' }}
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
                {machine.agent_name}
              </span>
              <span
                className="text-[11px] font-mono px-2 py-0.5 rounded-full"
                style={{ background: 'var(--ink-light)', color: 'var(--text-dim)' }}
              >
                {machine.agent_slug}
              </span>
              {hasOverride && (
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                  style={{ background: 'rgba(201,184,255,0.15)', color: 'var(--moon)' }}
                >
                  override
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 mt-1 text-xs" style={{ color: 'var(--text-dim)' }}>
              <span className="capitalize">{machine.fly_state || machine.agent_status}</span>
              <span>·</span>
              <span>{machine.fly_region || '—'}</span>
              <span>·</span>
              <span className="font-mono">v{machine.image_version || '?'}</span>
              <span>·</span>
              <span className="font-mono">{machine.machine_id ? machine.machine_id.slice(0, 12) : '—'}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {expanded
            ? <ChevronDown size={16} style={{ color: 'var(--text-dim)' }} />
            : <ChevronRight size={16} style={{ color: 'var(--text-dim)' }} />
          }
        </div>
      </div>

      {/* Expanded body */}
      {expanded && (
        <div style={{ borderTop: '1px solid var(--ink-lighter)' }}>
          {/* Tab strip */}
          <div
            className="flex items-center gap-1 px-5 pt-3"
            style={{ borderBottom: '1px solid var(--ink-lighter)' }}
          >
            {TABS.map(t => {
              const active = activeTab === t.key;
              return (
                <button
                  key={t.key}
                  onClick={() => setActiveTab(t.key)}
                  className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors"
                  style={{
                    color: active ? 'var(--moon)' : 'var(--text-dim)',
                    borderBottom: '2px solid',
                    borderColor: active ? 'var(--moon)' : 'transparent',
                    marginBottom: -1,
                  }}
                >
                  <t.icon size={12} />
                  {t.label}
                </button>
              );
            })}
          </div>

          <div className="px-5 py-4">
            {activeTab === 'overview' && (
              <OverviewTab machine={machine} busy={busy} images={images} onUpdateImage={onUpdateImage} />
            )}
            {activeTab === 'settings' && (
              <div className="space-y-4">
                <ModelsSection machine={machine} busy={busy} catalog={catalog} onChange={onSetModel} />
                <ConnectorsPluginSection machine={machine} busy={busy} onChange={onSetMode} />
              </div>
            )}
            {activeTab === 'webhooks' && (
              <WebhooksTab
                machine={machine}
                links={links}
                deliveries={deliveries}
                onChange={onWebhooksChange}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function OverviewTab({
  machine, busy, images, onUpdateImage,
}: {
  machine: Machine;
  busy: boolean;
  images: ImageOption[];
  onUpdateImage: (imageId: string) => void;
}) {
  const builtImages = images
    .filter(i => i.build_status === 'built')
    .slice()
    .sort((a, b) => {
      const ta = new Date(a.built_at || a.created_at || 0).getTime();
      const tb = new Date(b.built_at || b.created_at || 0).getTime();
      return tb - ta;
    });
  const mainImage = builtImages.find(i => i.is_main);
  const [target, setTarget] = useState<string>('');
  // Default the picker to the main image (or first built) once images load.
  useEffect(() => {
    if (!target && builtImages.length) {
      setTarget((mainImage || builtImages[0]).id);
    }
  }, [builtImages, mainImage, target]);
  const selected = builtImages.find(i => i.id === target);
  const sameVersion = selected?.version === machine.image_version;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs">
        <span style={{ color: 'var(--text-dim)' }}>Image version</span>
        <span className="font-mono" style={{ color: 'var(--text)' }}>{machine.image_version || '—'}</span>

        <span style={{ color: 'var(--text-dim)' }}>State</span>
        <span className="capitalize" style={{ color: 'var(--text)' }}>{machine.fly_state || machine.agent_status}</span>

        <span style={{ color: 'var(--text-dim)' }}>Region</span>
        <span style={{ color: 'var(--text)' }}>{machine.fly_region || '—'}</span>

        <span style={{ color: 'var(--text-dim)' }}>Machine ID</span>
        <span className="font-mono break-all" style={{ color: 'var(--text)' }}>{machine.machine_id || '—'}</span>

        <span style={{ color: 'var(--text-dim)' }}>Runtime</span>
        <span style={{ color: 'var(--text)' }}>{machine.runtime_kind || '—'}</span>

        {machine.fly_image && (
          <>
            <span style={{ color: 'var(--text-dim)' }}>Fly image tag</span>
            <span className="font-mono break-all" style={{ color: 'var(--text)' }}>{machine.fly_image}</span>
          </>
        )}

        {machine.fly_created_at && (
          <>
            <span style={{ color: 'var(--text-dim)' }}>Fly created</span>
            <span style={{ color: 'var(--text)' }}>{fmtTime(machine.fly_created_at)}</span>
          </>
        )}
      </div>
      {machine.machine_id && (
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={target}
            onChange={e => setTarget(e.target.value)}
            disabled={busy || builtImages.length === 0}
            className="rounded-lg px-3 py-1.5 text-xs font-medium outline-none cursor-pointer"
            style={{ background: 'var(--ink-light)', color: 'var(--text)', border: '1px solid var(--ink-lighter)', minWidth: 200 }}
          >
            {builtImages.length === 0 && <option value="">No built images</option>}
            {builtImages.map(i => (
              <option key={i.id} value={i.id}>
                {fmtTime(i.built_at || i.created_at)} · v{i.version}
                {i.is_main ? ' (main)' : i.git_branch && i.git_branch !== 'main' ? ` (${i.git_branch})` : ''}
                {i.version === machine.image_version ? ' — current' : ''}
              </option>
            ))}
          </select>
          <button
            onClick={() => target && onUpdateImage(target)}
            disabled={busy || !target || sameVersion}
            title={sameVersion ? 'Machine already on this image version' : undefined}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:bg-[var(--ink-light)] disabled:opacity-50"
            style={{ border: '1px solid var(--ink-lighter)', color: 'var(--moon)' }}
          >
            {busy ? <Loader2 className="animate-spin" size={12} /> : <ArrowUpCircle size={12} />}
            {sameVersion ? 'Up to date' : `Switch to v${selected?.version ?? ''}`}
          </button>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function MachinesPage() {
  const [machines, setMachines] = useState<Machine[]>([]);
  const [links, setLinks] = useState<AccountLink[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [catalog, setCatalog] = useState<CatalogModel[]>([]);
  const [images, setImages] = useState<ImageOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [migratingAll, setMigratingAll] = useState(false);
  const [migrateResult, setMigrateResult] = useState<{ updated: number; errors: { machine_id: string; agent: string; error: string }[] } | null>(null);

  const fetchAll = useCallback(async () => {
    const [mRes, lRes, dRes, cRes, iRes] = await Promise.all([
      fetch('/api/admin/machines'),
      fetch('/api/admin/relay/links'),
      fetch('/api/admin/relay/deliveries?limit=200'),
      fetch('/api/admin/gateway/models'),
      fetch('/api/admin/images'),
    ]);
    if (mRes.ok) setMachines(await mRes.json());
    if (lRes.ok) setLinks(await lRes.json());
    if (dRes.ok) setDeliveries(await dRes.json());
    if (cRes.ok) setCatalog(await cRes.json());
    if (iRes.ok) setImages(await iRes.json());
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const linksByAgent = useMemo(() => {
    const map: Record<string, AccountLink[]> = {};
    for (const l of links) {
      const key = l.agent_slug || '';
      if (!map[key]) map[key] = [];
      map[key].push(l);
    }
    return map;
  }, [links]);

  const deliveriesByAgent = useMemo(() => {
    const map: Record<string, Delivery[]> = {};
    for (const d of deliveries) {
      const key = d.agent_slug || '';
      if (!map[key]) map[key] = [];
      map[key].push(d);
    }
    return map;
  }, [deliveries]);

  const handleUpdateImage = async (machineId: string, imageId?: string) => {
    setBusy(machineId);
    const res = await fetch(`/api/admin/machines/${machineId}/update-image`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(imageId ? { image_id: imageId } : {}),
    });
    if (res.ok) await fetchAll();
    else {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      alert(`Update failed: ${err.detail || JSON.stringify(err)}`);
    }
    setBusy(null);
  };

  const handleSetMode = async (machineId: string, value: 'inherit' | 'hosted' | 'user' | 'both') => {
    setBusy(machineId);
    const accounts_mode = value === 'inherit' ? null : value;
    await fetch(`/api/admin/machines/${machineId}/services/composio`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ accounts_mode }),
    });
    await fetchAll();
    setBusy(null);
  };

  const handleSetModel = async (machineId: string, role: 'primary' | 'fast', value: string) => {
    setBusy(machineId);
    const body: Record<string, unknown> = {};
    if (value === 'inherit') {
      body[role === 'primary' ? 'clear_primary' : 'clear_fast'] = true;
    } else {
      const [provider, ...rest] = value.split(':');
      body[role] = { provider, model: rest.join(':') };
    }
    await fetch(`/api/admin/machines/${machineId}/models`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    await fetchAll();
    setBusy(null);
  };

  const handleMigrateAll = async () => {
    setMigratingAll(true);
    setMigrateResult(null);
    const res = await fetch('/api/admin/machines/migrate-all', { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      setMigrateResult(data);
      await fetchAll();
    }
    setMigratingAll(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  return (
    <div className="w-full max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <Server size={20} style={{ color: 'var(--moon)' }} />
          Machines
          <span className="text-sm font-normal" style={{ color: 'var(--text-dim)' }}>({machines.length})</span>
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchAll}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-all hover:scale-105"
            style={{ border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}
          >
            <RefreshCw size={14} />
          </button>
          <button
            onClick={handleMigrateAll}
            disabled={migratingAll}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:scale-105 disabled:opacity-50"
            style={{ background: 'var(--moon)', color: 'var(--ink)' }}
          >
            {migratingAll ? <Loader2 className="animate-spin" size={14} /> : <ArrowUpCircle size={14} />}
            Update All to Main
          </button>
        </div>
      </div>

      {migrateResult && (
        <div
          className="rounded-xl p-4 border mb-4 text-sm flex items-start gap-2"
          style={{
            background: 'var(--surface)',
            borderColor: migrateResult.errors.length ? '#ef4444' : '#22c55e',
          }}
        >
          <Check size={16} style={{ color: migrateResult.errors.length ? '#ef4444' : '#22c55e', marginTop: 2 }} />
          <div>
            <span style={{ color: 'var(--text)' }}>Updated {migrateResult.updated} machine{migrateResult.updated !== 1 ? 's' : ''}</span>
            {migrateResult.errors.length > 0 && (
              <div className="mt-2 space-y-1">
                {migrateResult.errors.map((e, i) => (
                  <div key={i} className="text-xs" style={{ color: '#ef4444' }}>
                    {e.agent}: {e.error}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {machines.length === 0 ? (
        <div className="rounded-2xl p-12 border text-center" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          <Server size={48} className="mx-auto mb-4" style={{ color: 'var(--moon)', opacity: 0.5 }} />
          <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--text)' }}>No machines</h3>
          <p className="text-sm" style={{ color: 'var(--text-dim)' }}>No agents with active runtimes found.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {machines.map(m => (
            <MachineCard
              key={m.agent_id}
              machine={m}
              links={linksByAgent[m.agent_slug] || []}
              deliveries={deliveriesByAgent[m.agent_slug] || []}
              busy={busy === m.machine_id}
              catalog={catalog}
              images={images}
              onUpdateImage={(imageId) => m.machine_id && handleUpdateImage(m.machine_id, imageId)}
              onSetMode={(v) => m.machine_id && handleSetMode(m.machine_id, v)}
              onSetModel={(r, v) => m.machine_id && handleSetModel(m.machine_id, r, v)}
              onWebhooksChange={fetchAll}
            />
          ))}
        </div>
      )}
    </div>
  );
}
