import type { ReactNode } from 'react';

export interface InfoRow {
  label: string;
  value: ReactNode;
  hint?: string;
}

export function InfoCard({ title, rows }: { title: string; rows: InfoRow[] }) {
  return (
    <section
      className="rounded-2xl p-5 border"
      style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}
    >
      <h3 className="text-sm font-semibold uppercase tracking-wider mb-4" style={{ color: 'var(--text-dim)' }}>
        {title}
      </h3>
      <dl className="space-y-3">
        {rows.map((row, i) => (
          <div key={i} className="flex items-baseline gap-4 text-sm">
            <dt className="w-40 flex-shrink-0" style={{ color: 'var(--text-dim)' }}>
              {row.label}
            </dt>
            <dd className="flex-1 break-all" style={{ color: 'var(--text)' }}>
              {row.value}
              {row.hint && (
                <span className="ml-2 text-xs" style={{ color: 'var(--text-dim)', opacity: 0.7 }}>
                  {row.hint}
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
