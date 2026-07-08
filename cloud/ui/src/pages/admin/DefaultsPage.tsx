import { useEffect, useState, useCallback, useRef } from 'react';
import { Loader2, Brain, Boxes, Check, Plug } from 'lucide-react';
import DefaultsTabs from './DefaultsTabs';
import DefaultsStaleBanner from '../../components/DefaultsStaleBanner';
import PluginSetEditor from '../../components/PluginSetEditor';
import type { PluginSetEntry, PluginKeying } from '../../components/PluginSetEditor';
import SupportedPluginsEditor from '../../components/SupportedPluginsEditor';
import MachineConfigEditor from '../../components/MachineConfigEditor';
import type { MachineConfig } from '../../components/MachineConfigEditor';
import { CAT, GW } from '../../components/pluginKeys';
import type { CatalogEntry, ServiceLite } from '../../components/pluginKeys';

const DEFAULT_MACHINE: MachineConfig = { cpu_kind: 'shared', cpus: 1, memory_mb: 1024, region: 'sjc' };

interface ModelHead { provider?: string; model?: string }
interface Defaults {
  models: { primary: ModelHead; fast: ModelHead };
  plugin_set: PluginSetEntry[];
  machine: MachineConfig;
}
interface CatalogModel {
  provider: string;
  model: string;
  label?: string;
  kinds: string[];
  enabled: boolean;
  recommended_default?: boolean;
}

export default function DefaultsPage() {
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [catalog, setCatalog] = useState<CatalogModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const saveTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Plan 026 — plugin↔key catalog, surfaced inline next to the baked set.
  const [keyCatalog, setKeyCatalog] = useState<CatalogEntry[]>([]);
  const [services, setServices] = useState<ServiceLite[]>([]);
  const [keyError, setKeyError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    const [defRes, modelsRes] = await Promise.all([
      fetch('/api/admin/defaults'),
      fetch('/api/admin/gateway/models'),
    ]);
    if (defRes.ok) {
      const d = await defRes.json();
      setDefaults({
        models: { primary: d.models?.primary || {}, fast: d.models?.fast || {} },
        plugin_set: d.plugin_set || [],
        machine: { ...DEFAULT_MACHINE, ...(d.machine || {}) },
      });
    }
    if (modelsRes.ok) setCatalog((await modelsRes.json()).filter((m: CatalogModel) => m.enabled));
    setLoading(false);
  }, []);

  const fetchKeys = useCallback(async () => {
    const [c, s] = await Promise.all([fetch(CAT), fetch(`${GW}/services`)]);
    if (c.ok) setKeyCatalog(await c.json());
    if (s.ok) setServices(await s.json());
  }, []);

  useEffect(() => { fetchData(); fetchKeys(); }, [fetchData, fetchKeys]);

  // Bind/clear a plugin's default key. Baked plugins may have no catalog row yet
  // — picking a service creates a `default`-tier entry; clearing it PATCHes "".
  const bindKey = useCallback(async (pluginName: string, serviceSlug: string, tier: 'default' | 'supported') => {
    setKeyError(null);
    const existing = keyCatalog.find(e => e.plugin_name === pluginName);
    let r: Response;
    if (existing) {
      r = await fetch(`${CAT}/${pluginName}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ service_slug: serviceSlug }),
      });
    } else {
      r = await fetch(CAT, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_name: pluginName, tier, service_slug: serviceSlug || null }),
      });
    }
    if (r.ok) fetchKeys();
    else setKeyError((await r.json().catch(() => null))?.detail || `Failed (${r.status})`);
  }, [keyCatalog, fetchKeys]);

  const setMode = useCallback(async (pluginName: string, mode: 'proxy' | 'env') => {
    setKeyError(null);
    const r = await fetch(`${CAT}/${pluginName}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key_mode: mode }),
    });
    if (r.ok) fetchKeys();
    else setKeyError((await r.json().catch(() => null))?.detail || `Failed (${r.status})`);
  }, [fetchKeys]);

  const save = useCallback(async (patch: Partial<Defaults>) => {
    setSaveStatus('saving');
    clearTimeout(saveTimer.current);
    await fetch('/api/admin/defaults', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    setSaveStatus('saved');
    saveTimer.current = setTimeout(() => setSaveStatus('idle'), 2000);
  }, []);

  const updateModel = (role: 'primary' | 'fast', modelKey: string) => {
    if (!defaults) return;
    const entry = catalog.find(m => m.model === modelKey);
    const value = modelKey && entry ? { provider: entry.provider, model: entry.model } : {};
    const models = { ...defaults.models, [role]: value };
    setDefaults({ ...defaults, models });
    save({ models });
  };

  const updatePluginSet = (next: PluginSetEntry[]) => {
    if (!defaults) return;
    setDefaults({ ...defaults, plugin_set: next });
    save({ plugin_set: next });
  };

  const updateMachine = async (machine: MachineConfig) => {
    if (!defaults) return;
    setDefaults({ ...defaults, machine });
    await save({ machine });
  };

  const catalogByName: Record<string, CatalogEntry> = {};
  for (const e of keyCatalog) catalogByName[e.plugin_name] = e;
  const keying: PluginKeying = {
    services,
    catalogByName,
    onBind: (name, slug) => bindKey(name, slug, 'default'),
    onMode: setMode,
  };
  const supportedKeying: PluginKeying = {
    services,
    catalogByName,
    onBind: (name, slug) => bindKey(name, slug, 'supported'),
    onMode: setMode,
  };
  const supported = keyCatalog.filter(e => e.tier === 'supported');

  if (loading || !defaults) {
    return (
      <div>
        <DefaultsTabs />
        <div className="flex items-center justify-center py-20">
          <Loader2 className="animate-spin" size={28} style={{ color: 'var(--moon)' }} />
        </div>
      </div>
    );
  }

  return (
    <div>
      <DefaultsTabs />

      <DefaultsStaleBanner refreshKey={saveStatus} />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--text)' }}>Image Defaults</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-dim)' }}>
            Applied to new images and to any image that hasn't overridden the value.
          </p>
        </div>
        {saveStatus !== 'idle' && (
          <span className="flex items-center gap-1.5 text-xs" style={{ color: 'var(--text-dim)' }}>
            {saveStatus === 'saving'
              ? <><Loader2 size={12} className="animate-spin" /> Saving…</>
              : <><Check size={12} style={{ color: '#4ade80' }} /> Saved</>}
          </span>
        )}
      </div>

      <div className="space-y-6" style={{ maxWidth: 720 }}>
        {/* Default model */}
        <SectionCard icon={Brain} title="Default model">
          <div>
            <p className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>
              The head new images run unless an image or machine overrides it.
              Empty inherits the catalog default (Defaults → Models).
            </p>
            {(['primary', 'fast'] as const).map((role, i) => {
              const kind = role === 'primary' ? 'reasoning' : 'summarization';
              const currentModel = defaults.models[role]?.model || '';
              const kindModels = catalog.filter(m => m.kinds.includes(kind));
              const inList = kindModels.some(m => m.model === currentModel);
              const options = [
                { value: '', label: 'Inherit catalog default' },
                ...kindModels.map(m => ({
                  value: m.model,
                  label: `${m.provider} — ${m.label || m.model}${m.recommended_default ? ' (catalog default)' : ''}`,
                })),
                ...(currentModel && !inList ? [{ value: currentModel, label: `${currentModel} (off-catalog)` }] : []),
              ];
              return (
                <FieldRow
                  key={role}
                  label={role === 'primary' ? 'Primary (reasoning)' : 'Fast (summarization)'}
                  noBorder={i === 1}
                >
                  <Select value={currentModel} options={options} onChange={v => updateModel(role, v)} />
                </FieldRow>
              );
            })}
          </div>
        </SectionCard>

        {/* Default machine */}
        <MachineConfigEditor
          title="Default machine"
          note="The machine every new agent gets. Any image can override these in its own config; unset fields fall back here."
          value={defaults.machine}
          onApply={updateMachine}
        />

        {keyError && (
          <div className="rounded-xl px-4 py-3 text-sm" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
            {keyError}
          </div>
        )}

        {/* Default plugin set */}
        <SectionCard icon={Boxes} title="Default plugin set">
          <div>
            <p className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>
              Baked into new images by default. Each image can override this in its
              own config. Set a <b>default key</b> per plugin to bind a gateway pool
              service — in <b>proxy</b> mode the real key never reaches the machine.
            </p>
            <PluginSetEditor value={defaults.plugin_set} onChange={updatePluginSet} keying={keying} />
          </div>
        </SectionCard>

        {/* Supported plugins (List B) */}
        <SectionCard icon={Plug} title="Supported plugins">
          <div>
            <p className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>
              Opt-in plugins we offer with a default key, even before a user installs
              them. Bind a key here, then when the user installs it, it'll have a
              provisioned key by default.
            </p>
            <SupportedPluginsEditor
              entries={supported}
              keying={supportedKeying}
              onChanged={fetchKeys}
              onError={setKeyError}
            />
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

/* ---- local primitives (match ImageConfigPage styling) ---- */

function SectionCard({ icon: Icon, title, children }: {
  icon: React.ElementType; title: string; children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border overflow-hidden" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
      <div className="flex items-center gap-2.5 px-5 py-3.5 border-b" style={{ borderColor: 'var(--ink-lighter)' }}>
        <Icon size={16} style={{ color: 'var(--moon)' }} />
        <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{title}</span>
      </div>
      <div className="px-5 py-4">{children}</div>
    </div>
  );
}

function FieldRow({ label, children, noBorder }: { label: string; children: React.ReactNode; noBorder?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2" style={noBorder ? undefined : { borderBottom: '1px solid var(--ink-lighter)' }}>
      <span className="text-sm" style={{ color: 'var(--text-dim)' }}>{label}</span>
      {children}
    </div>
  );
}

function Select({ value, options, onChange }: {
  value: string | number;
  options: { value: string | number; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="rounded-lg px-3 py-2 text-sm font-medium outline-none appearance-none cursor-pointer"
      style={{ background: 'var(--ink-light)', color: 'var(--text)', border: '1px solid var(--ink-lighter)', minWidth: 220 }}
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}
