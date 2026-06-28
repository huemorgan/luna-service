import { Lock, Zap } from 'lucide-react';

export interface EnvEntry {
  name: string;
  value: string | null;
  placeholder: string | null;
  source: string;
  secret: boolean;
  dynamic: boolean;
}

const SOURCE_LABEL: Record<string, string> = {
  platform: 'platform',
  gateway: 'gateway',
  models: 'models',
  plugins: 'plugins',
  files: 'files',
  'image-config': 'image config',
  live: 'live',
};

/** Read-only table of env vars. Secrets are shown masked (the backend already
 *  masks them); dynamic per-agent values render their placeholder in muted
 *  italics so it's clear the real value is injected at provision time. */
export default function EnvVarsTable({ entries }: { entries: EnvEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className="text-xs py-3" style={{ color: 'var(--text-dim)' }}>
        No env vars to show.
      </p>
    );
  }
  return (
    <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--ink-lighter)' }}>
      <table className="w-full text-xs">
        <thead>
          <tr style={{ background: 'var(--ink)', color: 'var(--text-dim)' }}>
            <th className="text-left font-medium px-3 py-2">Variable</th>
            <th className="text-left font-medium px-3 py-2">Value</th>
            <th className="text-left font-medium px-3 py-2 w-px whitespace-nowrap">Source</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={e.name} style={{ background: i % 2 ? 'var(--ink)' : 'transparent', borderTop: '1px solid var(--ink-lighter)' }}>
              <td className="px-3 py-1.5 align-top">
                <span className="font-mono" style={{ color: 'var(--text)' }}>{e.name}</span>
                <span className="inline-flex items-center gap-1 ml-2 align-middle">
                  {e.secret && <Lock size={10} style={{ color: '#f0a868' }} aria-label="secret" />}
                  {e.dynamic && <Zap size={10} style={{ color: '#7aa2ff' }} aria-label="dynamic" />}
                </span>
              </td>
              <td className="px-3 py-1.5 align-top">
                {e.placeholder != null ? (
                  <span className="font-mono italic" style={{ color: 'var(--text-dim)' }}>{e.placeholder}</span>
                ) : (
                  <span className="font-mono break-all" style={{ color: e.value === '' ? 'var(--text-dim)' : 'var(--text)' }}>
                    {e.value === '' ? '(empty)' : e.value}
                  </span>
                )}
              </td>
              <td className="px-3 py-1.5 align-top whitespace-nowrap">
                <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'var(--surface)', color: 'var(--text-dim)' }}>
                  {SOURCE_LABEL[e.source] || e.source}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EnvLegend() {
  return (
    <div className="flex items-center gap-4 text-[11px] mt-2" style={{ color: 'var(--text-dim)' }}>
      <span className="inline-flex items-center gap-1"><Lock size={10} style={{ color: '#f0a868' }} /> secret (masked)</span>
      <span className="inline-flex items-center gap-1"><Zap size={10} style={{ color: '#7aa2ff' }} /> dynamic — injected per machine at provision time</span>
    </div>
  );
}
