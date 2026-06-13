import { useEffect, useState, useCallback } from 'react';
import { Server, Loader2, RefreshCw, ArrowUpCircle } from 'lucide-react';

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

export default function MachinesPage() {
  const [machines, setMachines] = useState<Machine[]>([]);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState<string | null>(null);
  const [migratingAll, setMigratingAll] = useState(false);
  const [migrateResult, setMigrateResult] = useState<{ updated: number; errors: { machine_id: string; agent: string; error: string }[] } | null>(null);

  const fetchMachines = useCallback(async () => {
    const res = await fetch('/api/admin/machines');
    if (res.ok) setMachines(await res.json());
    setLoading(false);
  }, []);

  useEffect(() => { fetchMachines(); }, [fetchMachines]);

  const handleUpdateImage = async (machineId: string) => {
    setUpdating(machineId);
    const res = await fetch(`/api/admin/machines/${machineId}/update-image`, { method: 'POST' });
    if (res.ok) await fetchMachines();
    setUpdating(null);
  };

  // Plan 016: per-machine Composio accounts-mode override.
  // value === "" means "Use image default" (clear the override).
  const handleSetComposioMode = async (machineId: string, value: string) => {
    setUpdating(machineId);
    const accounts_mode = value === '' ? null : value;
    await fetch(`/api/admin/machines/${machineId}/services/composio`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ accounts_mode }),
    });
    await fetchMachines();
    setUpdating(null);
  };

  const handleMigrateAll = async () => {
    setMigratingAll(true);
    setMigrateResult(null);
    const res = await fetch('/api/admin/machines/migrate-all', { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      setMigrateResult(data);
      await fetchMachines();
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
    <div className="max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <Server size={20} style={{ color: 'var(--moon)' }} />
          Machines
          <span className="text-sm font-normal" style={{ color: 'var(--text-dim)' }}>({machines.length})</span>
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchMachines}
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
          className="rounded-xl p-4 border mb-4 text-sm"
          style={{
            background: 'var(--surface)',
            borderColor: migrateResult.errors.length ? '#ef4444' : '#22c55e',
          }}
        >
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
      )}

      {machines.length === 0 && (
        <div className="rounded-2xl p-12 border text-center" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          <Server size={48} className="mx-auto mb-4" style={{ color: 'var(--moon)', opacity: 0.5 }} />
          <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--text)' }}>No machines</h3>
          <p className="text-sm" style={{ color: 'var(--text-dim)' }}>No agents with active runtimes found.</p>
        </div>
      )}

      {machines.length > 0 && (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--ink-lighter)' }}>
          <table className="w-full">
            <thead>
              <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
                <th className="text-left text-xs font-medium px-4 py-3" style={{ color: 'var(--text-dim)' }}>Agent</th>
                <th className="text-left text-xs font-medium px-4 py-3" style={{ color: 'var(--text-dim)' }}>State</th>
                <th className="text-left text-xs font-medium px-4 py-3" style={{ color: 'var(--text-dim)' }}>Region</th>
                <th className="text-left text-xs font-medium px-4 py-3" style={{ color: 'var(--text-dim)' }}>Version</th>
                <th className="text-left text-xs font-medium px-4 py-3" style={{ color: 'var(--text-dim)' }}>Machine ID</th>
                <th className="text-left text-xs font-medium px-4 py-3" style={{ color: 'var(--text-dim)' }}>Connectors mode</th>
                <th className="text-right text-xs font-medium px-4 py-3" style={{ color: 'var(--text-dim)' }}></th>
              </tr>
            </thead>
            <tbody>
              {machines.map(m => (
                <tr
                  key={m.agent_id}
                  className="border-t"
                  style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}
                >
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium" style={{ color: 'var(--text)' }}>{m.agent_name}</div>
                    <div className="text-xs" style={{ color: 'var(--text-dim)' }}>{m.agent_slug}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="flex items-center gap-1.5 text-xs capitalize">
                      <span className="w-2 h-2 rounded-full" style={{ background: STATE_COLORS[m.fly_state || ''] || '#94a3b8' }} />
                      <span style={{ color: 'var(--text)' }}>{m.fly_state || m.agent_status}</span>
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{m.fly_region || '—'}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs font-mono" style={{ color: m.image_version ? 'var(--text)' : 'var(--text-dim)' }}>
                      {m.image_version || 'unknown'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs font-mono" style={{ color: 'var(--text-dim)' }}>
                      {m.machine_id ? m.machine_id.slice(0, 12) : '—'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {m.machine_id && (
                      <div className="flex items-center gap-2">
                        <select
                          value={m.composio_accounts_mode_override ?? ''}
                          onChange={e => handleSetComposioMode(m.machine_id!, e.target.value)}
                          disabled={updating === m.machine_id}
                          className="rounded-lg px-2 py-1 text-xs outline-none disabled:opacity-50"
                          style={{
                            background: 'var(--ink-light)',
                            color: 'var(--text)',
                            border: '1px solid var(--ink-lighter)',
                          }}
                        >
                          <option value="">Use image default ({m.composio_accounts_mode})</option>
                          <option value="hosted">hosted</option>
                          <option value="user">user</option>
                          <option value="both">both</option>
                        </select>
                        {m.composio_accounts_mode_override && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded" style={{
                            background: 'rgba(201,184,255,0.15)', color: 'var(--moon)',
                          }}>override</span>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {m.machine_id && (
                      <button
                        onClick={() => handleUpdateImage(m.machine_id!)}
                        disabled={updating === m.machine_id}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:opacity-80 disabled:opacity-50 ml-auto"
                        style={{ border: '1px solid var(--ink-lighter)', color: 'var(--moon)' }}
                      >
                        {updating === m.machine_id ? <Loader2 className="animate-spin" size={12} /> : <ArrowUpCircle size={12} />}
                        Update
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
