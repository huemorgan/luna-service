import { useEffect, useMemo, useState } from 'react';
import { Cpu, DollarSign, ArrowRight, Check, Loader2 } from 'lucide-react';

/* ------------------------------------------------------------------ */
/*  Machine config editor — shared by ImageConfigPage (per-image) and   */
/*  DefaultsPage (default machine params, Plan 036).                     */
/* ------------------------------------------------------------------ */

export interface MachineConfig {
  cpu_kind: string;
  cpus: number;
  memory_mb: number;
  region: string;
}

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
  { value: 8192, label: '8 GB' },
  { value: 16384, label: '16 GB' },
  { value: 32768, label: '32 GB' },
  { value: 65536, label: '64 GB' },
];

// Fly guest RAM limits per vCPU, by CPU kind. Dedicated ("performance") CPUs
// require ≥2048 MiB each (so 4 vCPU → 8192 MiB min); shared allow ≥256 MiB.
// Fly also caps RAM per CPU. An invalid pair (e.g. performance/4/1 GB) is what
// triggers Fly's `invalid config.guest.memory_mb, minimum required …` 400.
const MEM_PER_CPU: Record<'shared' | 'performance', { min: number; max: number }> = {
  shared: { min: 256, max: 2048 },
  performance: { min: 2048, max: 16384 },
};

function memBounds(cpuKind: string, cpus: number): { min: number; max: number } {
  const r = MEM_PER_CPU[cpuKind as 'shared' | 'performance'] ?? MEM_PER_CPU.shared;
  return { min: r.min * cpus, max: r.max * cpus };
}

function validMemoryOptions(cpuKind: string, cpus: number) {
  const { min, max } = memBounds(cpuKind, cpus);
  return MEMORY_OPTIONS.filter(o => o.value >= min && o.value <= max);
}

// Snap a memory value into the allowed range for the chosen CPU kind + count.
function clampMemory(cpuKind: string, cpus: number, mem: number): number {
  const opts = validMemoryOptions(cpuKind, cpus).map(o => o.value);
  if (opts.length === 0) return memBounds(cpuKind, cpus).min;
  if (opts.includes(mem)) return mem;
  if (mem < opts[0]) return opts[0];
  if (mem > opts[opts.length - 1]) return opts[opts.length - 1];
  return opts.find(o => o >= mem) ?? opts[opts.length - 1];
}

function fmtMem(mb: number): string {
  return mb >= 1024 ? `${mb / 1024} GB` : `${mb} MB`;
}

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

/* ---- Cost estimation (Fly.io pricing, per-month, 730h) ---- */

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

/* ---- local primitives (match ImageConfigPage / DefaultsPage styling) ---- */

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
      style={{ background: 'var(--ink-light)', color: 'var(--text)', border: '1px solid var(--ink-lighter)', minWidth: 140 }}
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

/* ------------------------------------------------------------------ */

export default function MachineConfigEditor({ value, onApply, title = 'Machine', note }: {
  value: MachineConfig;
  onApply: (machine: MachineConfig) => Promise<void>;
  title?: string;
  note?: string;
}) {
  const [draft, setDraft] = useState<MachineConfig>(() => ({
    ...value,
    memory_mb: clampMemory(value.cpu_kind, value.cpus, value.memory_mb),
  }));
  const [applying, setApplying] = useState(false);

  // Re-seed the draft whenever the persisted value changes (e.g. after load or
  // a successful save from elsewhere).
  useEffect(() => {
    setDraft({ ...value, memory_mb: clampMemory(value.cpu_kind, value.cpus, value.memory_mb) });
  }, [value.cpu_kind, value.cpus, value.memory_mb, value.region]);

  const changed = draft.cpu_kind !== value.cpu_kind
    || draft.cpus !== value.cpus
    || draft.memory_mb !== value.memory_mb
    || draft.region !== value.region;

  const currentCost = useMemo(
    () => estimateMonthlyCost(value.cpu_kind, value.cpus, value.memory_mb, value.region),
    [value.cpu_kind, value.cpus, value.memory_mb, value.region],
  );
  const draftCost = useMemo(
    () => estimateMonthlyCost(draft.cpu_kind, draft.cpus, draft.memory_mb, draft.region),
    [draft],
  );

  // Final guard so an out-of-range memory can never be applied (and turned into
  // a Fly 400 at agent-create time).
  const memValid = useMemo(() => {
    const { min, max } = memBounds(draft.cpu_kind, draft.cpus);
    return draft.memory_mb >= min && draft.memory_mb <= max;
  }, [draft]);

  const update = (field: keyof MachineConfig, val: string | number) => {
    const next = { ...draft, [field]: val } as MachineConfig;
    // Changing CPU kind or count can invalidate the current memory (Fly's
    // per-vCPU floor/ceiling). Snap memory back into the valid range.
    if (field === 'cpu_kind' || field === 'cpus') {
      next.memory_mb = clampMemory(next.cpu_kind, next.cpus, next.memory_mb);
    }
    setDraft(next);
  };

  const apply = async () => {
    if (!changed || !memValid) return;
    setApplying(true);
    try {
      await onApply(draft);
    } finally {
      setApplying(false);
    }
  };

  return (
    <SectionCard icon={Cpu} title={title}>
      {note && <p className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>{note}</p>}
      <div>
        <FieldRow label="CPU Kind">
          <Select value={draft.cpu_kind} options={CPU_KINDS} onChange={v => update('cpu_kind', v)} />
        </FieldRow>
        <FieldRow label="CPUs">
          <Select value={draft.cpus} options={CPU_COUNTS.map(c => ({ value: c, label: `${c} vCPU` }))} onChange={v => update('cpus', parseInt(v))} />
        </FieldRow>
        <FieldRow label="Memory">
          <div className="flex flex-col items-end gap-1">
            <Select
              value={draft.memory_mb}
              options={validMemoryOptions(draft.cpu_kind, draft.cpus)}
              onChange={v => update('memory_mb', parseInt(v))}
            />
            <span className="text-[10px]" style={{ color: 'var(--text-dim)' }}>
              {draft.cpu_kind === 'performance' ? 'Dedicated' : 'Shared'} {draft.cpus}× vCPU
              {' '}allows {fmtMem(memBounds(draft.cpu_kind, draft.cpus).min)}–
              {fmtMem(memBounds(draft.cpu_kind, draft.cpus).max)}
            </span>
          </div>
        </FieldRow>
        <FieldRow label="Region" noBorder>
          <Select value={draft.region} options={REGIONS} onChange={v => update('region', v)} />
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
              <span className="text-lg font-bold" style={{ color: changed ? 'var(--text-dim)' : 'var(--text)' }}>
                {formatCost(currentCost)}
              </span>
              {changed && (
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
            onClick={apply}
            disabled={!changed || applying || !memValid}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all hover:scale-105 disabled:opacity-30 disabled:hover:scale-100"
            style={{
              background: changed && memValid ? 'var(--moon)' : 'var(--ink-lighter)',
              color: changed && memValid ? 'var(--ink)' : 'var(--text-dim)',
            }}
          >
            {applying ? <Loader2 className="animate-spin" size={14} /> : <Check size={14} />}
            Apply
          </button>
        </div>
      </div>
    </SectionCard>
  );
}
