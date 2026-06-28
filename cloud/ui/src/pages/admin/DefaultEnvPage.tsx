import { useEffect, useState } from 'react';
import { Loader2, ListTree } from 'lucide-react';
import DefaultsTabs from './DefaultsTabs';
import EnvVarsTable, { EnvLegend } from '../../components/EnvVarsTable';
import type { EnvEntry } from '../../components/EnvVarsTable';

/** Plan 029 — Defaults → Env vars. The env-var template every NEW machine
 *  receives. Dynamic per-agent values render as {{placeholders}}. */
export default function DefaultEnvPage() {
  const [entries, setEntries] = useState<EnvEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/admin/defaults/env')
      .then(async r => (r.ok ? r.json() : Promise.reject(await r.text())))
      .then(d => setEntries(d.entries))
      .catch(e => setError(String(e)));
  }, []);

  return (
    <div>
      <DefaultsTabs />
      <div className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <ListTree size={20} style={{ color: 'var(--moon)' }} /> Default env vars
        </h1>
        <p className="text-sm mt-1" style={{ color: 'var(--text-dim)' }}>
          The environment every new machine is provisioned with. Values shown as
          <code className="mx-1">{'{{…}}'}</code> are injected per-machine at provision
          time (per-agent tokens, isolated DB, derived secrets) — they are not fixed here.
        </p>
      </div>

      <div style={{ maxWidth: 820 }}>
        {error && (
          <div className="rounded-xl px-4 py-3 mb-4 text-sm" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
            {error}
          </div>
        )}
        {entries == null && !error ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
          </div>
        ) : entries ? (
          <>
            <EnvVarsTable entries={entries} />
            <EnvLegend />
          </>
        ) : null}
      </div>
    </div>
  );
}
