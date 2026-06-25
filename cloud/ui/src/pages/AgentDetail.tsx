import { useEffect, useState, useCallback } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import {
  Moon, LogOut, ChevronLeft, Loader2, ExternalLink,
  Square, Play, RotateCcw, AlertTriangle, RefreshCw, Pencil, Check, X, Trash2,
} from 'lucide-react';
import { InfoCard } from '../components/InfoCard';
import type { InfoRow } from '../components/InfoCard';
import { ComingSoonCard } from '../components/ComingSoonCard';
import type { ComingSoonRow } from '../components/ComingSoonCard';
import { SizePresetSelect } from '../components/SizePresetSelect';

interface DetailPayload {
  agent: {
    id: string;
    name: string;
    slug: string;
    status: string;
    runtime_kind: string | null;
    error_message: string | null;
    error_at: string | null;
    created_at: string;
    last_active_at: string | null;
  };
  account: { id: string; slug: string; name: string; plan: string };
  creator: { email: string | null; name: string | null };
  routing: { public_url: string | null; internal_url: string | null; slug: string | null };
  storage: {
    postgres: { host: string | null; schema: string | null };
    r2: { prefix: string | null; object_count: number; size_bytes: number; configured: boolean };
    volume: { mount: string; size_gb: number };
    vault_key_ref: string | null;
  };
  compute: {
    kind?: string;
    machine_id?: string;
    app?: string;
    region?: string;
    region_label?: string;
    image?: string;
    size?: { cpu_kind?: string; cpus?: number; memory_mb?: number };
    state?: string;
    created_at?: string;
    last_started_at?: string;
    error?: string;
    image_version?: string;
    image_cache_warmed_at?: string | null;
  };
  metrics_cached_at: string | null;
  coming_soon: {
    activity: ComingSoonRow[];
    spend: ComingSoonRow[];
  };
}

const STATUS_DOT: Record<string, string> = {
  running: '#22c55e',
  provisioning: '#facc15',
  pending: '#94a3b8',
  stopped: '#94a3b8',
  error: '#ef4444',
};

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<DetailPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState('');
  const [savingName, setSavingName] = useState(false);
  const [deleteDraft, setDeleteDraft] = useState('');
  const [deleting, setDeleting] = useState(false);

  const fetchDetails = useCallback(async () => {
    if (!id) return;
    try {
      const res = await fetch(`/api/agents/${id}/details`);
      if (res.status === 401) { window.location.href = '/'; return; }
      if (res.status === 404) { setError('Agent not found'); setData(null); return; }
      if (!res.ok) { setError(`Failed to load (${res.status})`); return; }
      const payload: DetailPayload = await res.json();
      setData(payload);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Network error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [id]);

  useEffect(() => { fetchDetails(); }, [fetchDetails]);

  useEffect(() => {
    if (!data || data.agent.status !== 'provisioning') return;
    const t = setInterval(fetchDetails, 4000);
    return () => clearInterval(t);
  }, [data, fetchDetails]);

  const handleRefresh = () => { setRefreshing(true); fetchDetails(); };

  const handleAction = async (action: 'start' | 'stop' | 'retry') => {
    if (!id) return;
    setActionLoading(true);
    try {
      const res = await fetch(`/api/agents/${id}/${action}`, { method: 'POST' });
      if (res.ok) await fetchDetails();
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--ink)' }}>
        <Loader2 className="animate-spin" size={32} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen p-10" style={{ background: 'var(--ink)' }}>
        <Link to="/dashboard" className="inline-flex items-center gap-1 text-sm mb-6" style={{ color: 'var(--text-dim)' }}>
          <ChevronLeft size={14} /> Dashboard
        </Link>
        <div className="rounded-2xl p-8 border text-center" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          <AlertTriangle size={32} className="mx-auto mb-3" style={{ color: '#ef4444' }} />
          <h2 className="text-lg font-semibold mb-2" style={{ color: 'var(--text)' }}>{error || 'Agent not found'}</h2>
        </div>
      </div>
    );
  }

  const { agent, account, creator, routing, storage, compute, coming_soon, metrics_cached_at } = data;
  const dotColor = STATUS_DOT[agent.status] || '#94a3b8';

  const handleRename = async () => {
    if (!id) return;
    const newName = nameDraft.trim();
    if (!newName || newName === agent.name) { setEditingName(false); return; }
    setSavingName(true);
    try {
      const res = await fetch(`/api/agents/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName }),
      });
      if (res.ok) {
        await fetchDetails();
        setEditingName(false);
      } else {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        alert(`Rename failed: ${err.detail || JSON.stringify(err)}`);
      }
    } finally {
      setSavingName(false);
    }
  };

  const handleDelete = async () => {
    if (!id || deleteDraft.trim() !== agent.name) return;
    setDeleting(true);
    try {
      const res = await fetch(`/api/agents/${id}`, { method: 'DELETE' });
      if (res.ok) {
        navigate('/dashboard');
      } else {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        alert(`Delete failed: ${err.detail || res.statusText}`);
        setDeleting(false);
      }
    } catch (e) {
      alert(`Delete failed: ${e instanceof Error ? e.message : 'Network error'}`);
      setDeleting(false);
    }
  };

  const identityRows: InfoRow[] = [
    { label: 'Slug', value: <code className="font-mono">{agent.slug}</code> },
    {
      label: 'URL',
      value: routing.public_url ? (
        <a href={routing.public_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 hover:underline" style={{ color: 'var(--moon)' }}>
          {routing.public_url} <ExternalLink size={12} />
        </a>
      ) : '—',
    },
    { label: 'Account', value: <span>{account.name} <span style={{ color: 'var(--text-dim)' }}>· {account.plan}</span></span> },
    { label: 'Created by', value: creator.email || '—' },
    { label: 'Created at', value: fmtDate(agent.created_at) },
  ];

  const computeRows: InfoRow[] = compute.machine_id ? [
    { label: 'Machine ID', value: <code className="font-mono text-xs">{compute.machine_id}</code> },
    { label: 'App', value: compute.app || '—' },
    {
      label: 'Region',
      value: compute.region ? (
        <span>{compute.region}{compute.region_label && compute.region_label !== compute.region ? ` (${compute.region_label})` : ''}</span>
      ) : '—',
    },
    { label: 'Image', value: <code className="font-mono text-xs break-all">{compute.image_version ? `v${compute.image_version}` : (compute.image || '—')}</code> },
    {
      label: 'Image cache',
      value: compute.image_cache_warmed_at ? (
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full inline-block" style={{ background: '#22c55e' }} />
          <span style={{ color: '#22c55e' }}>Warm</span>
          <span className="text-xs" style={{ color: 'var(--text-dim)' }}>· {timeAgo(compute.image_cache_warmed_at)}</span>
        </span>
      ) : (
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full inline-block" style={{ background: '#6b7280' }} />
          <span style={{ color: 'var(--text-dim)' }}>Cold</span>
        </span>
      ),
    },
    { label: 'Size', value: <SizePresetSelect current={compute.size || {}} /> },
    {
      label: 'State',
      value: (
        <span className="inline-flex items-center gap-2">
          <span className="w-2 h-2 rounded-full inline-block" style={{ background: STATUS_DOT[compute.state || ''] || dotColor }} />
          {compute.state || '—'}
          {compute.error && <span className="text-xs" style={{ color: '#ef4444' }}>· {compute.error}</span>}
        </span>
      ),
    },
    { label: 'Last started', value: timeAgo(compute.last_started_at), hint: compute.last_started_at ? fmtDate(compute.last_started_at) : undefined },
  ] : [
    { label: 'Runtime', value: agent.runtime_kind || 'not provisioned' },
    { label: 'State', value: compute.error ? <span style={{ color: '#ef4444' }}>{compute.error}</span> : 'no machine info available' },
  ];

  const r2Display = !storage.r2.configured
    ? <span style={{ color: 'var(--text-dim)' }}>{storage.r2.prefix || '—'} <span className="text-xs">· not yet in use</span></span>
    : <span>{storage.r2.prefix} <span style={{ color: 'var(--text-dim)' }} className="text-xs">· {fmtBytes(storage.r2.size_bytes)} · {storage.r2.object_count} object{storage.r2.object_count === 1 ? '' : 's'}</span></span>;

  const storageRows: InfoRow[] = [
    { label: 'Postgres schema', value: <code className="font-mono text-xs">{storage.postgres.schema || '—'}</code> },
    { label: 'Postgres host', value: <code className="font-mono text-xs">{storage.postgres.host || '—'}</code> },
    { label: 'Volume', value: <span>{storage.volume.mount} <span style={{ color: 'var(--text-dim)' }} className="text-xs">· {storage.volume.size_gb} GB</span></span> },
    { label: 'R2 prefix', value: r2Display },
    {
      label: 'Vault key',
      value: storage.vault_key_ref ? (
        <span>derived <span style={{ color: 'var(--text-dim)' }} className="text-xs font-mono">· ref {storage.vault_key_ref.slice(-8)}</span></span>
      ) : <span>derived <span style={{ color: 'var(--text-dim)' }} className="text-xs">· per-tenant from root key</span></span>,
    },
  ];

  return (
    <div className="min-h-screen" style={{ background: 'var(--ink)' }}>
      <header
        className="flex items-center justify-between px-6 py-4 border-b"
        style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}
      >
        <div className="flex items-center gap-3">
          <Moon size={24} style={{ color: 'var(--moon)' }} />
          <span className="text-lg font-semibold" style={{ color: 'var(--text)' }}>Luna Service</span>
        </div>
        <a href="/auth/logout" className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors hover:opacity-80" style={{ color: 'var(--text-dim)' }}>
          <LogOut size={14} />
          Sign out
        </a>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        {/* Breadcrumb */}
        <nav className="mb-6 flex items-center gap-2 text-sm" style={{ color: 'var(--text-dim)' }}>
          <Link to="/dashboard" className="inline-flex items-center gap-1 hover:underline">
            <ChevronLeft size={14} /> Dashboard
          </Link>
          <span style={{ opacity: 0.5 }}>›</span>
          <span style={{ color: 'var(--text)' }}>{agent.name}</span>
        </nav>

        {/* Title + actions */}
        <div className="flex items-start justify-between mb-2 flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-3" style={{ color: 'var(--text)' }}>
              <span className="w-3 h-3 rounded-full inline-block" style={{ background: dotColor }} />
              {editingName ? (
                <span className="flex items-center gap-2">
                  <input
                    autoFocus
                    value={nameDraft}
                    onChange={e => setNameDraft(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') handleRename();
                      if (e.key === 'Escape') setEditingName(false);
                    }}
                    disabled={savingName}
                    maxLength={100}
                    className="px-2 py-1 rounded-lg text-2xl font-bold outline-none disabled:opacity-60"
                    style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--moon)' }}
                  />
                  <button onClick={handleRename} disabled={savingName} title="Save" className="p-1.5 rounded-lg transition-colors hover:opacity-80 disabled:opacity-50" style={{ color: 'var(--moon)' }}>
                    {savingName ? <Loader2 className="animate-spin" size={18} /> : <Check size={18} />}
                  </button>
                  <button onClick={() => setEditingName(false)} disabled={savingName} title="Cancel" className="p-1.5 rounded-lg transition-colors hover:opacity-80 disabled:opacity-50" style={{ color: 'var(--text-dim)' }}>
                    <X size={18} />
                  </button>
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  {agent.name}
                  <button
                    onClick={() => { setNameDraft(agent.name); setEditingName(true); }}
                    title="Rename"
                    className="p-1 rounded-lg transition-colors hover:bg-[var(--ink-light)]"
                    style={{ color: 'var(--text-dim)' }}
                  >
                    <Pencil size={16} />
                  </button>
                </span>
              )}
            </h1>
            <p className="text-sm mt-1" style={{ color: 'var(--text-dim)' }}>
              <span className="capitalize">{agent.status}</span>
              {agent.created_at && <> · Created {timeAgo(agent.created_at)}</>}
              {agent.last_active_at && <> · Last active {timeAgo(agent.last_active_at)}</>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {routing.public_url && agent.status === 'running' && (
              <a
                href={routing.public_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all hover:scale-105"
                style={{ background: 'var(--moon)', color: 'var(--ink)' }}
              >
                <ExternalLink size={14} /> Open
              </a>
            )}
            {agent.status === 'running' && (
              <button onClick={() => handleAction('stop')} disabled={actionLoading} className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs transition-colors hover:opacity-80 disabled:opacity-50" style={{ color: 'var(--text-dim)', border: '1px solid var(--ink-lighter)' }}>
                <Square size={12} /> Stop
              </button>
            )}
            {agent.status === 'stopped' && (
              <button onClick={() => handleAction('start')} disabled={actionLoading} className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs transition-colors hover:opacity-80 disabled:opacity-50" style={{ color: 'var(--text-dim)', border: '1px solid var(--ink-lighter)' }}>
                <Play size={12} /> Start
              </button>
            )}
            {agent.status === 'error' && (
              <button onClick={() => handleAction('retry')} disabled={actionLoading} className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium transition-colors hover:opacity-80 disabled:opacity-50" style={{ color: '#facc15', border: '1px solid rgba(250,204,21,0.3)' }}>
                <RotateCcw size={12} /> Retry
              </button>
            )}
            <button onClick={handleRefresh} disabled={refreshing} className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs transition-colors hover:opacity-80 disabled:opacity-50" style={{ color: 'var(--text-dim)', border: '1px solid var(--ink-lighter)' }} title="Refresh live metrics">
              <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} /> Refresh
            </button>
          </div>
        </div>

        {agent.status === 'error' && agent.error_message && (
          <div className="mt-3 mb-4 flex items-start gap-2 px-4 py-3 rounded-xl text-xs" style={{ background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
            <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" style={{ color: '#ef4444' }} />
            <span style={{ color: '#fca5a5' }}>{agent.error_message}</span>
          </div>
        )}

        {/* Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-6">
          <InfoCard title="Identity & Routing" rows={identityRows} />
          <InfoCard title="Compute (Fly Machine)" rows={computeRows} />
          <InfoCard title="Storage" rows={storageRows} />
          <div className="grid grid-cols-1 gap-4">
            <ComingSoonCard
              title="Activity"
              description="Live usage signals — needs the metering pipeline."
              rows={coming_soon.activity}
            />
            <ComingSoonCard
              title="Spend"
              description="Cost breakdown and limits — needs metering + billing."
              rows={coming_soon.spend}
            />
          </div>
        </div>

        <div className="mt-6 text-xs flex items-center justify-between" style={{ color: 'var(--text-dim)', opacity: 0.6 }}>
          <span>
            Metrics cached at: {metrics_cached_at ? fmtDate(metrics_cached_at) : '—'}
            <span className="ml-2">(60 s TTL)</span>
          </span>
          <code className="font-mono">{agent.id}</code>
        </div>

        {/* Danger zone — delete only lives here, behind a type-the-name failsafe */}
        <div
          className="mt-8 rounded-2xl border p-5"
          style={{ background: 'rgba(239,68,68,0.04)', borderColor: 'rgba(239,68,68,0.25)' }}
        >
          <h3 className="text-sm font-semibold flex items-center gap-2 mb-1" style={{ color: '#f87171' }}>
            <AlertTriangle size={15} /> Danger zone
          </h3>
          <p className="text-xs mb-4" style={{ color: 'var(--text-dim)' }}>
            Deleting <strong style={{ color: 'var(--text)' }}>{agent.name}</strong> destroys its
            machine and removes the agent. This cannot be undone. Type the agent's name to confirm.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 sm:items-center">
            <input
              type="text"
              value={deleteDraft}
              onChange={e => setDeleteDraft(e.target.value)}
              placeholder={agent.name}
              disabled={deleting}
              className="flex-1 max-w-xs px-3 py-2 rounded-lg text-sm outline-none disabled:opacity-60"
              style={{ background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' }}
            />
            <button
              onClick={handleDelete}
              disabled={deleting || deleteDraft.trim() !== agent.name}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ background: deleteDraft.trim() === agent.name ? '#ef4444' : 'transparent', color: deleteDraft.trim() === agent.name ? 'white' : 'var(--text-dim)', border: '1px solid rgba(239,68,68,0.4)' }}
            >
              {deleting ? <Loader2 className="animate-spin" size={14} /> : <Trash2 size={14} />}
              Delete agent
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
