/**
 * Fly Machines size presets.
 *
 * Sourced from Fly's public pricing page. Costs are approximate, monthly,
 * always-on. We render this as a *disabled* dropdown today — phase 007
 * will wire the actual resize call.
 */

export interface SizePreset {
  cpu_kind: 'shared' | 'performance';
  cpus: number;
  memory_mb: number;
  monthly_usd: number;
}

export const SIZE_PRESETS: SizePreset[] = [
  { cpu_kind: 'shared', cpus: 1, memory_mb: 256, monthly_usd: 1.94 },
  { cpu_kind: 'shared', cpus: 1, memory_mb: 512, monthly_usd: 2.16 },
  { cpu_kind: 'shared', cpus: 1, memory_mb: 1024, monthly_usd: 3.02 },
  { cpu_kind: 'shared', cpus: 2, memory_mb: 2048, monthly_usd: 6.04 },
  { cpu_kind: 'shared', cpus: 4, memory_mb: 4096, monthly_usd: 12.08 },
  { cpu_kind: 'shared', cpus: 8, memory_mb: 8192, monthly_usd: 24.16 },
  { cpu_kind: 'performance', cpus: 1, memory_mb: 2048, monthly_usd: 31.0 },
  { cpu_kind: 'performance', cpus: 2, memory_mb: 4096, monthly_usd: 62.0 },
  { cpu_kind: 'performance', cpus: 4, memory_mb: 8192, monthly_usd: 124.0 },
  { cpu_kind: 'performance', cpus: 8, memory_mb: 16384, monthly_usd: 248.0 },
];

export function presetKey(p: Pick<SizePreset, 'cpu_kind' | 'cpus' | 'memory_mb'>): string {
  return `${p.cpu_kind}-${p.cpus}x-${p.memory_mb}`;
}

export function formatPreset(p: SizePreset): string {
  const mem = p.memory_mb >= 1024 ? `${p.memory_mb / 1024} GB` : `${p.memory_mb} MB`;
  return `${p.cpu_kind}-cpu-${p.cpus}x · ${mem} · ~$${p.monthly_usd.toFixed(2)}/mo`;
}

export function SizePresetSelect({
  current,
}: {
  current: { cpu_kind?: string | null; cpus?: number | null; memory_mb?: number | null };
}) {
  const currentKey = current.cpu_kind && current.cpus && current.memory_mb
    ? presetKey({ cpu_kind: current.cpu_kind as 'shared' | 'performance', cpus: current.cpus, memory_mb: current.memory_mb })
    : presetKey({ cpu_kind: 'shared', cpus: 1, memory_mb: 1024 });

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <select
        value={currentKey}
        disabled
        aria-label="Machine size (coming soon)"
        title="Resize is coming in phase 007"
        className="text-sm px-3 py-1.5 rounded-lg cursor-not-allowed"
        style={{
          background: 'var(--ink)',
          color: 'var(--text)',
          border: '1px solid var(--ink-lighter)',
          opacity: 0.85,
          appearance: 'auto',
        }}
        onChange={() => {/* disabled — phase 007 wires this */}}
      >
        {SIZE_PRESETS.map((p) => (
          <option key={presetKey(p)} value={presetKey(p)}>
            {formatPreset(p)}
          </option>
        ))}
      </select>
      <span
        className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded"
        style={{ background: 'var(--ink-lighter)', color: 'var(--text-dim)' }}
      >
        Coming soon · phase 007
      </span>
    </div>
  );
}
