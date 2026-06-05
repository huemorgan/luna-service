import { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Loader2, Package, Cpu, Brain, Plug, Variable,
  Star, Check, Plus, Trash2, Lock,
} from 'lucide-react';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ImageInfo {
  id: string;
  version: string;
  registry_tag: string;
  is_main: boolean;
  build_status: string;
  git_sha: string | null;
  created_at: string | null;
  built_at: string | null;
  image_config: ImageConfig;
}

interface ImageConfig {
  machine: { cpu_kind: string; cpus: number; memory_mb: number; region: string };
  models: {
    primary: { provider: string; model: string };
    fast: { provider: string; model: string };
  };
  plugins: Record<string, boolean>;
  env: Record<string, string>;
}

interface PluginMeta {
  key: string;
  name: string;
  description: string;
  required: boolean;
}

/* ------------------------------------------------------------------ */
/*  Options                                                            */
/* ------------------------------------------------------------------ */

const CPU_KINDS = [
  { value: 'shared', label: 'Shared' },
  { value: 'performance', label: 'Performance' },
];

const CPU_COUNTS = [1, 2, 4, 8];

const MEMORY_OPTIONS = [
  { value: 256, label: '256 MB' },
  { value: 512, label: '512 MB' },
  { value: 1024, label: '1 GB' },
  { value: 2048, label: '2 GB' },
  { value: 4096, label: '4 GB' },
];

const REGIONS = [
  { value: 'sjc', label: 'San Jose (sjc)' },
  { value: 'iad', label: 'Ashburn (iad)' },
  { value: 'lhr', label: 'London (lhr)' },
  { value: 'ams', label: 'Amsterdam (ams)' },
  { value: 'cdg', label: 'Paris (cdg)' },
  { value: 'nrt', label: 'Tokyo (nrt)' },
  { value: 'sin', label: 'Singapore (sin)' },
  { value: 'syd', label: 'Sydney (syd)' },
  { value: 'gru', label: 'São Paulo (gru)' },
];

const PROVIDERS = [
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'openai', label: 'OpenAI' },
];

const MODEL_OPTIONS: Record<string, { value: string; label: string }[]> = {
  anthropic: [
    { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
    { value: 'claude-opus-4-20250514', label: 'Claude Opus 4' },
    { value: 'claude-haiku-3-5-20241022', label: 'Claude Haiku 3.5' },
  ],
  openai: [
    { value: 'gpt-4o', label: 'GPT-4o' },
    { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
    { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
    { value: 'o3', label: 'o3' },
    { value: 'o4-mini', label: 'o4-mini' },
  ],
};

/* ------------------------------------------------------------------ */
/*  Shared UI pieces                                                   */
/* ------------------------------------------------------------------ */

function Toggle({ on, disabled, onChange }: { on: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={disabled}
      onClick={() => !disabled && onChange(!on)}
      className="relative rounded-full transition-colors"
      style={{
        width: 44,
        height: 24,
        background: on ? '#4ade80' : '#2a2a3a',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        flexShrink: 0,
      }}
    >
      <span
        className="absolute rounded-full transition-all duration-200"
        style={{
          width: 18,
          height: 18,
          top: 3,
          left: on ? 23 : 3,
          background: on ? 'white' : '#6b6b80',
        }}
      />
    </button>
  );
}

function Select({ value, options, onChange, fullWidth }: {
  value: string | number;
  options: { value: string | number; label: string }[];
  onChange: (v: string) => void;
  fullWidth?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="rounded-lg px-3 py-2 text-sm font-medium outline-none appearance-none cursor-pointer"
      style={{
        background: 'var(--ink-light)',
        color: 'var(--text)',
        border: '1px solid var(--ink-lighter)',
        width: fullWidth ? '100%' : undefined,
        minWidth: fullWidth ? undefined : 140,
      }}
    >
      {options.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

function SectionCard({ icon: Icon, title, children }: {
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="rounded-2xl border overflow-hidden"
      style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}
    >
      <div
        className="flex items-center gap-2.5 px-5 py-3.5 border-b"
        style={{ borderColor: 'var(--ink-lighter)' }}
      >
        <Icon size={16} style={{ color: 'var(--moon)' }} />
        <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{title}</span>
      </div>
      <div className="px-5 py-4">
        {children}
      </div>
    </div>
  );
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm" style={{ color: 'var(--text-dim)' }}>{label}</span>
      {children}
    </div>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

/* ------------------------------------------------------------------ */
/*  Main page                                                          */
/* ------------------------------------------------------------------ */

export default function ImageConfigPage() {
  const { imageId } = useParams<{ imageId: string }>();
  const navigate = useNavigate();

  const [image, setImage] = useState<ImageInfo | null>(null);
  const [config, setConfig] = useState<ImageConfig | null>(null);
  const [plugins, setPlugins] = useState<PluginMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const saveTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const fetchData = useCallback(async () => {
    const [imgRes, cfgRes, plugRes] = await Promise.all([
      fetch('/api/admin/images'),
      fetch(`/api/admin/images/${imageId}/config`),
      fetch('/api/admin/plugin-meta'),
    ]);
    if (imgRes.ok) {
      const imgs: ImageInfo[] = await imgRes.json();
      setImage(imgs.find(i => i.id === imageId) || null);
    }
    if (cfgRes.ok) setConfig(await cfgRes.json());
    if (plugRes.ok) setPlugins(await plugRes.json());
    setLoading(false);
  }, [imageId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const save = useCallback(async (patch: Partial<ImageConfig>) => {
    setSaveStatus('saving');
    clearTimeout(saveTimer.current);

    await fetch(`/api/admin/images/${imageId}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });

    setSaveStatus('saved');
    saveTimer.current = setTimeout(() => setSaveStatus('idle'), 2000);
  }, [imageId]);

  const updateMachine = (field: string, value: string | number) => {
    if (!config) return;
    const next = { ...config, machine: { ...config.machine, [field]: value } };
    setConfig(next);
    save({ machine: next.machine });
  };

  const updateModel = (role: 'primary' | 'fast', field: string, value: string) => {
    if (!config) return;
    const updated = { ...config.models[role], [field]: value };
    if (field === 'provider') {
      const models = MODEL_OPTIONS[value] || [];
      if (models.length > 0) updated.model = models[0].value;
    }
    const next = {
      ...config,
      models: { ...config.models, [role]: updated },
    };
    setConfig(next);
    save({ models: next.models });
  };

  const togglePlugin = (key: string, value: boolean) => {
    if (!config) return;
    const next = { ...config, plugins: { ...config.plugins, [key]: value } };
    setConfig(next);
    save({ plugins: next.plugins });
  };

  const updateEnv = (entries: Record<string, string>) => {
    if (!config) return;
    const next = { ...config, env: entries };
    setConfig(next);
    save({ env: entries });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  if (!image || !config) {
    return (
      <div className="max-w-3xl">
        <button onClick={() => navigate('/admin/images')} className="flex items-center gap-2 text-sm mb-6 hover:opacity-80 transition-opacity" style={{ color: 'var(--text-dim)' }}>
          <ArrowLeft size={16} /> Back to Images
        </button>
        <div className="text-center py-12" style={{ color: 'var(--text-dim)' }}>Image not found.</div>
      </div>
    );
  }

  const envEntries = Object.entries(config.env);

  return (
    <div className="max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/admin/images')}
            className="flex items-center justify-center w-8 h-8 rounded-lg transition-colors hover:opacity-80"
            style={{ background: 'var(--ink-light)', color: 'var(--text-dim)' }}
          >
            <ArrowLeft size={16} />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <Package size={18} style={{ color: 'var(--moon)' }} />
              <h2 className="text-lg font-bold" style={{ color: 'var(--text)' }}>v{image.version}</h2>
              {image.is_main && (
                <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full" style={{ background: 'rgba(201,184,255,0.15)', color: 'var(--moon)' }}>
                  <Star size={10} /> Main
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 mt-0.5">
              <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{formatDate(image.built_at || image.created_at)}</span>
              {image.git_sha && <span className="text-xs font-mono" style={{ color: 'var(--text-dim)' }}>{image.git_sha.slice(0, 7)}</span>}
            </div>
          </div>
        </div>

        {/* Save indicator */}
        <div className="flex items-center gap-2 text-xs h-7 px-3 rounded-full transition-all duration-300" style={{
          background: saveStatus === 'saved' ? 'rgba(34,197,94,0.1)' : saveStatus === 'saving' ? 'rgba(201,184,255,0.08)' : 'transparent',
          color: saveStatus === 'saved' ? '#22c55e' : saveStatus === 'saving' ? 'var(--moon)' : 'transparent',
          opacity: saveStatus === 'idle' ? 0 : 1,
        }}>
          {saveStatus === 'saving' && <Loader2 className="animate-spin" size={12} />}
          {saveStatus === 'saved' && <Check size={12} />}
          {saveStatus === 'saving' ? 'Saving...' : saveStatus === 'saved' ? 'Saved' : ''}
        </div>
      </div>

      <div className="space-y-4">
        {/* ---- Machine ---- */}
        <SectionCard icon={Cpu} title="Machine">
          <div className="divide-y" style={{ borderColor: 'var(--ink-lighter)' }}>
            <FieldRow label="CPU Kind">
              <Select value={config.machine.cpu_kind} options={CPU_KINDS} onChange={v => updateMachine('cpu_kind', v)} />
            </FieldRow>
            <FieldRow label="CPUs">
              <Select value={config.machine.cpus} options={CPU_COUNTS.map(c => ({ value: c, label: `${c} vCPU` }))} onChange={v => updateMachine('cpus', parseInt(v))} />
            </FieldRow>
            <FieldRow label="Memory">
              <Select value={config.machine.memory_mb} options={MEMORY_OPTIONS} onChange={v => updateMachine('memory_mb', parseInt(v))} />
            </FieldRow>
            <FieldRow label="Region">
              <Select value={config.machine.region} options={REGIONS} onChange={v => updateMachine('region', v)} />
            </FieldRow>
          </div>
        </SectionCard>

        {/* ---- Models ---- */}
        <SectionCard icon={Brain} title="Models">
          <div className="divide-y" style={{ borderColor: 'var(--ink-lighter)' }}>
            {(['primary', 'fast'] as const).map(role => {
              const provider = config.models[role].provider;
              const models = MODEL_OPTIONS[provider] || [];
              const currentModel = config.models[role].model;
              const modelInList = models.some(m => m.value === currentModel);
              const modelOptions = modelInList ? models : [{ value: currentModel, label: currentModel }, ...models];

              return (
                <div key={role} className="py-3 first:pt-0 last:pb-0">
                  <div className="text-xs font-semibold mb-3 uppercase tracking-wider" style={{ color: 'var(--moon-dim)' }}>
                    {role === 'primary' ? 'Primary Model' : 'Fast Model'}
                  </div>
                  <div className="space-y-2">
                    <FieldRow label="Provider">
                      <Select
                        value={provider}
                        options={PROVIDERS}
                        onChange={v => updateModel(role, 'provider', v)}
                      />
                    </FieldRow>
                    <FieldRow label="Model">
                      <Select
                        value={currentModel}
                        options={modelOptions}
                        onChange={v => updateModel(role, 'model', v)}
                      />
                    </FieldRow>
                  </div>
                </div>
              );
            })}
          </div>
        </SectionCard>

        {/* ---- Plugins ---- */}
        <SectionCard icon={Plug} title="Plugins">
          <div className="divide-y" style={{ borderColor: 'var(--ink-lighter)' }}>
            {plugins.map(p => {
              const enabled = config.plugins[p.key] !== false;
              return (
                <div
                  key={p.key}
                  className="flex items-center justify-between py-3"
                  style={{ opacity: enabled || p.required ? 1 : 0.5 }}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>{p.name}</span>
                      {p.required && (
                        <span className="flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded font-medium" style={{ background: 'rgba(201,184,255,0.1)', color: 'var(--moon-dim)' }}>
                          <Lock size={8} /> Required
                        </span>
                      )}
                    </div>
                    <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{p.description}</span>
                  </div>
                  <Toggle
                    on={enabled}
                    disabled={p.required}
                    onChange={v => togglePlugin(p.key, v)}
                  />
                </div>
              );
            })}
          </div>
        </SectionCard>

        {/* ---- Environment ---- */}
        <SectionCard icon={Variable} title="Environment">
          <div className="space-y-2">
            {envEntries.length === 0 && (
              <div className="text-xs py-2" style={{ color: 'var(--text-dim)' }}>
                No environment overrides set.
              </div>
            )}

            {envEntries.map(([key, value], i) => (
              <div key={i} className="flex items-center gap-2">
                <input
                  type="text"
                  value={key}
                  placeholder="KEY"
                  onChange={e => {
                    const entries = Object.entries(config.env);
                    entries[i] = [e.target.value, value];
                    updateEnv(Object.fromEntries(entries));
                  }}
                  className="rounded-lg px-3 py-2 text-sm font-mono outline-none flex-1"
                  style={{
                    background: 'var(--ink-light)',
                    color: 'var(--text)',
                    border: '1px solid var(--ink-lighter)',
                    maxWidth: 200,
                  }}
                />
                <span style={{ color: 'var(--text-dim)' }}>=</span>
                <input
                  type="text"
                  value={value}
                  placeholder="value"
                  onChange={e => {
                    const entries = Object.entries(config.env);
                    entries[i] = [key, e.target.value];
                    updateEnv(Object.fromEntries(entries));
                  }}
                  className="rounded-lg px-3 py-2 text-sm font-mono outline-none flex-1"
                  style={{
                    background: 'var(--ink-light)',
                    color: 'var(--text)',
                    border: '1px solid var(--ink-lighter)',
                  }}
                />
                <button
                  onClick={() => {
                    const entries = Object.entries(config.env).filter((_, j) => j !== i);
                    updateEnv(Object.fromEntries(entries));
                  }}
                  className="p-2 rounded-lg transition-colors hover:opacity-80"
                  style={{ color: '#ef4444' }}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}

            <button
              onClick={() => updateEnv({ ...config.env, '': '' })}
              className="flex items-center gap-1.5 text-xs font-medium mt-2 px-3 py-2 rounded-lg transition-colors hover:opacity-80"
              style={{ color: 'var(--moon)', border: '1px solid var(--ink-lighter)' }}
            >
              <Plus size={12} /> Add variable
            </button>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
