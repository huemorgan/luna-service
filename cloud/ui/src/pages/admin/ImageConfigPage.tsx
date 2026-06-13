import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Loader2, Package, Cpu, Brain, Plug, Variable,
  Star, Check, Plus, Trash2, Lock, DollarSign, ArrowRight, Cable,
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
  services?: {
    composio?: { accounts_mode?: 'hosted' | 'user' | 'both' };
  };
}

const COMPOSIO_MODE_OPTIONS = [
  { value: 'both', label: 'Both — hosted tab + user can bring their own key' },
  { value: 'hosted', label: 'Hosted only — included with Luna Cloud' },
  { value: 'user', label: 'User only — user brings their own Composio key' },
];

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

const ALL_MODELS: { provider: string; model: string; label: string }[] = [
  { provider: 'anthropic', model: 'claude-sonnet-4-20250514', label: 'Anthropic — Claude Sonnet 4' },
  { provider: 'anthropic', model: 'claude-opus-4-20250514', label: 'Anthropic — Claude Opus 4' },
  { provider: 'anthropic', model: 'claude-opus-4-20250514-high', label: 'Anthropic — Claude Opus 4 High' },
  { provider: 'anthropic', model: 'claude-haiku-3-5-20241022', label: 'Anthropic — Claude Haiku 3.5' },
  { provider: 'openai', model: 'gpt-4o', label: 'OpenAI — GPT-4o' },
  { provider: 'openai', model: 'gpt-4o-mini', label: 'OpenAI — GPT-4o Mini' },
  { provider: 'openai', model: 'gpt-4-turbo', label: 'OpenAI — GPT-4 Turbo' },
  { provider: 'openai', model: 'o3', label: 'OpenAI — o3' },
  { provider: 'openai', model: 'o4-mini', label: 'OpenAI — o4-mini' },
];

/* ------------------------------------------------------------------ */
/*  Cost estimation (Fly.io pricing, per-month, 730h)                  */
/* ------------------------------------------------------------------ */

const REGION_MULTIPLIERS: Record<string, number> = {
  iad: 1.00, sjc: 1.04, lhr: 1.25, ams: 1.25,
  cdg: 1.25, nrt: 1.25, sin: 1.25, syd: 1.25, gru: 1.25,
};

function estimateMonthlyCost(cpuKind: string, cpus: number, memoryMb: number, region: string): number {
  const mult = REGION_MULTIPLIERS[region] ?? 1.04;
  const baseCpuRate = cpuKind === 'shared' ? 1.94 : 31.00;
  const baseRamPerCpu = cpuKind === 'shared' ? 256 : 2048;
  const cpuCost = cpus * baseCpuRate;
  const baseRamMb = cpus * baseRamPerCpu;
  const extraRamGb = Math.max(0, memoryMb - baseRamMb) / 1024;
  const ramCost = extraRamGb * 5.00;
  return (cpuCost + ramCost) * mult;
}

function formatCost(v: number): string {
  return `$${v.toFixed(2)}`;
}

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

function FieldRow({ label, children, noBorder }: { label: string; children: React.ReactNode; noBorder?: boolean }) {
  return (
    <div
      className="flex items-center justify-between py-2"
      style={noBorder ? undefined : { borderBottom: '1px solid var(--ink-lighter)' }}
    >
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

  type MachineConfig = ImageConfig['machine'];
  const [machineDraft, setMachineDraft] = useState<MachineConfig | null>(null);
  const [applyingMachine, setApplyingMachine] = useState(false);

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
    if (cfgRes.ok) {
      const cfg = await cfgRes.json();
      setConfig(cfg);
      setMachineDraft(cfg.machine);
    }
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

  const machineChanged = useMemo(() => {
    if (!config || !machineDraft) return false;
    return config.machine.cpu_kind !== machineDraft.cpu_kind
      || config.machine.cpus !== machineDraft.cpus
      || config.machine.memory_mb !== machineDraft.memory_mb
      || config.machine.region !== machineDraft.region;
  }, [config, machineDraft]);

  const currentCost = useMemo(() => {
    if (!config) return 0;
    const m = config.machine;
    return estimateMonthlyCost(m.cpu_kind, m.cpus, m.memory_mb, m.region);
  }, [config]);

  const draftCost = useMemo(() => {
    if (!machineDraft) return 0;
    return estimateMonthlyCost(machineDraft.cpu_kind, machineDraft.cpus, machineDraft.memory_mb, machineDraft.region);
  }, [machineDraft]);

  const updateMachineDraft = (field: string, value: string | number) => {
    if (!machineDraft) return;
    setMachineDraft({ ...machineDraft, [field]: value });
  };

  const applyMachine = async () => {
    if (!machineDraft || !config) return;
    setApplyingMachine(true);
    const next = { ...config, machine: machineDraft };
    setConfig(next);
    await save({ machine: machineDraft });
    setApplyingMachine(false);
  };

  const updateModel = (role: 'primary' | 'fast', modelKey: string) => {
    if (!config) return;
    const entry = ALL_MODELS.find(m => m.model === modelKey);
    const provider = entry?.provider || config.models[role].provider;
    const next = {
      ...config,
      models: { ...config.models, [role]: { provider, model: modelKey } },
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

  const updateComposioMode = (mode: 'hosted' | 'user' | 'both') => {
    if (!config) return;
    const services = { ...(config.services || {}), composio: { accounts_mode: mode } };
    const next = { ...config, services };
    setConfig(next);
    save({ services });
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
        {machineDraft && (
        <SectionCard icon={Cpu} title="Machine">
          <div>
            <FieldRow label="CPU Kind">
              <Select value={machineDraft.cpu_kind} options={CPU_KINDS} onChange={v => updateMachineDraft('cpu_kind', v)} />
            </FieldRow>
            <FieldRow label="CPUs">
              <Select value={machineDraft.cpus} options={CPU_COUNTS.map(c => ({ value: c, label: `${c} vCPU` }))} onChange={v => updateMachineDraft('cpus', parseInt(v))} />
            </FieldRow>
            <FieldRow label="Memory">
              <Select value={machineDraft.memory_mb} options={MEMORY_OPTIONS} onChange={v => updateMachineDraft('memory_mb', parseInt(v))} />
            </FieldRow>
            <FieldRow label="Region" noBorder>
              <Select value={machineDraft.region} options={REGIONS} onChange={v => updateMachineDraft('region', v)} />
            </FieldRow>
          </div>

          {/* Cost + Apply */}
          <div className="mt-4 pt-3 border-t" style={{ borderColor: 'var(--ink-lighter)' }}>
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-1.5 text-xs font-medium mb-1" style={{ color: 'var(--text-dim)' }}>
                  <DollarSign size={12} /> Estimated monthly cost
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-lg font-bold" style={{ color: machineChanged ? 'var(--text-dim)' : 'var(--text)' }}>
                    {formatCost(currentCost)}
                  </span>
                  {machineChanged && (
                    <>
                      <ArrowRight size={14} style={{ color: 'var(--text-dim)' }} />
                      <span className="text-lg font-bold" style={{ color: draftCost > currentCost ? '#facc15' : '#4ade80' }}>
                        {formatCost(draftCost)}
                      </span>
                      <span className="text-xs px-1.5 py-0.5 rounded" style={{
                        background: draftCost > currentCost ? 'rgba(250,204,21,0.1)' : 'rgba(74,222,128,0.1)',
                        color: draftCost > currentCost ? '#facc15' : '#4ade80',
                      }}>
                        {draftCost > currentCost ? '+' : ''}{formatCost(draftCost - currentCost)}/mo
                      </span>
                    </>
                  )}
                </div>
                <div className="flex items-center gap-3 mt-0.5">
                  <span className="text-[10px]" style={{ color: 'var(--text-dim)' }}>per agent, running 24/7</span>
                  <span className="text-[10px]" style={{ color: 'var(--text-dim)' }}>· $0.15/mo when stopped</span>
                </div>
              </div>
              <button
                onClick={applyMachine}
                disabled={!machineChanged || applyingMachine}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all hover:scale-105 disabled:opacity-30 disabled:hover:scale-100"
                style={{
                  background: machineChanged ? 'var(--moon)' : 'var(--ink-lighter)',
                  color: machineChanged ? 'var(--ink)' : 'var(--text-dim)',
                }}
              >
                {applyingMachine ? <Loader2 className="animate-spin" size={14} /> : <Check size={14} />}
                Apply
              </button>
            </div>
          </div>
        </SectionCard>
        )}

        {/* ---- Models ---- */}
        <SectionCard icon={Brain} title="Models">
          <div>
            {(['primary', 'fast'] as const).map((role, i) => {
              const currentModel = config.models[role].model;
              const inList = ALL_MODELS.some(m => m.model === currentModel);
              const options = inList
                ? ALL_MODELS.map(m => ({ value: m.model, label: m.label }))
                : [{ value: currentModel, label: currentModel }, ...ALL_MODELS.map(m => ({ value: m.model, label: m.label }))];

              return (
                <FieldRow key={role} label={role === 'primary' ? 'Primary Model' : 'Fast Model'} noBorder={i === 1}>
                  <Select value={currentModel} options={options} onChange={v => updateModel(role, v)} />
                </FieldRow>
              );
            })}
          </div>
        </SectionCard>

        {/* ---- Plugins ---- */}
        <SectionCard icon={Plug} title="Plugins">
          <div>
            {plugins.map((p, i) => {
              const enabled = config.plugins[p.key] !== false;
              const isLast = i === plugins.length - 1;
              return (
                <div
                  key={p.key}
                  className="flex items-center justify-between py-3"
                  style={{
                    opacity: enabled || p.required ? 1 : 0.5,
                    borderBottom: isLast ? undefined : '1px solid var(--ink-lighter)',
                  }}
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

        {/* ---- Services (plan 016) ---- */}
        <SectionCard icon={Cable} title="Services">
          <div>
            <FieldRow label="Composio · Connectors mode" noBorder>
              <Select
                value={config.services?.composio?.accounts_mode || 'both'}
                options={COMPOSIO_MODE_OPTIONS}
                onChange={v => updateComposioMode(v as 'hosted' | 'user' | 'both')}
              />
            </FieldRow>
            <p className="text-xs mt-2" style={{ color: 'var(--text-dim)' }}>
              Default for new machines built from this image. Each machine can override
              this on the Machines page.
            </p>
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
