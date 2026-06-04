export interface ComingSoonRow {
  key: string;
  label: string;
  phase: string;
}

export function ComingSoonCard({
  title,
  rows,
  description,
}: {
  title: string;
  rows: ComingSoonRow[];
  description?: string;
}) {
  return (
    <section
      className="rounded-2xl p-5 border"
      style={{
        background: 'var(--surface)',
        borderColor: 'var(--ink-lighter)',
        opacity: 0.78,
      }}
      aria-label={`${title} — coming soon`}
    >
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-semibold uppercase tracking-wider" style={{ color: 'var(--text-dim)' }}>
          {title}
        </h3>
        <span
          className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded"
          style={{ background: 'var(--ink-lighter)', color: 'var(--text-dim)' }}
        >
          Coming soon
        </span>
      </div>
      {description && (
        <p className="text-xs mb-3" style={{ color: 'var(--text-dim)', opacity: 0.7 }}>
          {description}
        </p>
      )}
      <ul className="space-y-2 mt-3">
        {rows.map((r) => (
          <li
            key={r.key}
            className="flex items-center justify-between text-sm"
            title={`Coming in phase ${r.phase}`}
            aria-label={`${r.label} — coming in phase ${r.phase}`}
          >
            <span style={{ color: 'var(--text-dim)' }}>{r.label}</span>
            <span
              className="font-mono text-xs px-2 py-0.5 rounded"
              style={{ background: 'var(--ink)', color: 'var(--text-dim)', opacity: 0.6 }}
            >
              · · · phase {r.phase}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
