import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Package, Loader2, Star, Hammer, RefreshCw, ExternalLink, ChevronDown, ChevronRight, AlertCircle, Trash2, RotateCcw, ArrowUpCircle, Settings, Play, GitBranch, AlertTriangle, Search, Check } from 'lucide-react';

interface LunaImage {
  id: string;
  version: string;
  registry_tag: string;
  is_main: boolean;
  build_status: string;
  build_run_id: string | null;
  build_error: string | null;
  git_sha: string | null;
  git_branch: string | null;
  created_at: string | null;
  built_at: string | null;
  agent_count: number;
  cache_warmed_at: string | null;
}

interface LunaBranch {
  name: string;
  commit_sha: string | null;
  merged: boolean;
  ahead_by: number;
  behind_by: number;
  committed_at: string | null;
}

interface UpdateCheck {
  submodule_version: string | null;
  latest_built: string | null;
  update_available: boolean;
  source?: string;
}

const STATUS_COLORS: Record<string, string> = {
  built: '#22c55e',
  building: '#facc15',
  pending: '#94a3b8',
  failed: '#ef4444',
};

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function branchHint(b: LunaBranch): string {
  if (b.name === 'main') return 'release';
  return b.merged ? 'merged' : `+${b.ahead_by} unmerged`;
}

function relativeDate(iso: string | null): string {
  if (!iso) return '';
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days <= 0) return 'today';
  if (days === 1) return '1d ago';
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return months < 12 ? `${months}mo ago` : `${Math.floor(months / 12)}y ago`;
}

function BranchPicker({ branches, selected, onSelect, disabled }: {
  branches: LunaBranch[];
  selected: string;
  onSelect: (name: string) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // main pinned on top, the rest by last commit descending (unknown dates last)
  const sorted = useMemo(() => {
    const list = branches.length ? branches : [{ name: 'main', commit_sha: null, merged: true, ahead_by: 0, behind_by: 0, committed_at: null }];
    return [...list].sort((a, b) => {
      if (a.name === 'main') return -1;
      if (b.name === 'main') return 1;
      return (b.committed_at || '').localeCompare(a.committed_at || '') || a.name.localeCompare(b.name);
    });
  }, [branches]);

  const filtered = useMemo(
    () => sorted.filter(b => b.name.toLowerCase().includes(query.trim().toLowerCase())),
    [sorted, query],
  );

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  useEffect(() => {
    if (open) {
      setQuery('');
      setHighlight(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => { setHighlight(0); }, [query]);

  const pick = (name: string) => {
    onSelect(name);
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { setOpen(false); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setHighlight(h => Math.min(h + 1, filtered.length - 1)); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setHighlight(h => Math.max(h - 1, 0)); }
    if (e.key === 'Enter' && filtered[highlight]) { e.preventDefault(); pick(filtered[highlight].name); }
  };

  const current = sorted.find(b => b.name === selected);

  return (
    <div ref={rootRef} className="relative" style={{ minWidth: 260 }}>
      <button
        onClick={() => !disabled && setOpen(o => !o)}
        disabled={disabled}
        className="flex items-center justify-between gap-2 w-full rounded-lg px-3 py-2 text-sm font-medium cursor-pointer disabled:opacity-50"
        style={{ background: 'var(--ink-light)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' }}
      >
        <span className="truncate font-mono">{selected}</span>
        <span className="flex items-center gap-2 flex-shrink-0">
          <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{current ? branchHint(current) : ''}</span>
          <ChevronDown size={14} style={{ color: 'var(--text-dim)' }} />
        </span>
      </button>

      {open && (
        <div
          className="absolute z-50 mt-1 w-full rounded-lg border overflow-hidden"
          style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)', boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }}
          onKeyDown={onKeyDown}
        >
          <div className="flex items-center gap-2 px-3 py-2" style={{ borderBottom: '1px solid var(--ink-lighter)' }}>
            <Search size={13} style={{ color: 'var(--text-dim)' }} className="flex-shrink-0" />
            <input
              ref={inputRef}
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search branches…"
              className="w-full bg-transparent text-sm outline-none"
              style={{ color: 'var(--text)' }}
            />
          </div>
          <div className="max-h-72 overflow-y-auto py-1">
            {filtered.length === 0 && (
              <div className="px-3 py-2 text-xs" style={{ color: 'var(--text-dim)' }}>No branches match</div>
            )}
            {filtered.map((b, i) => (
              <button
                key={b.name}
                onClick={() => pick(b.name)}
                onMouseEnter={() => setHighlight(i)}
                className="flex items-center justify-between gap-2 w-full px-3 py-1.5 text-left text-sm"
                style={{
                  background: i === highlight ? 'var(--ink-light)' : 'transparent',
                  color: 'var(--text)',
                }}
              >
                <span className="flex items-center gap-1.5 min-w-0">
                  {b.name === selected
                    ? <Check size={12} className="flex-shrink-0" style={{ color: 'var(--moon)' }} />
                    : <span className="w-3 flex-shrink-0" />}
                  <span className="truncate font-mono">{b.name}</span>
                </span>
                <span className="flex items-center gap-2 flex-shrink-0 text-xs" style={{ color: 'var(--text-dim)' }}>
                  <span style={b.name !== 'main' && !b.merged ? { color: '#facc15' } : undefined}>{branchHint(b)}</span>
                  {b.committed_at && <span>{relativeDate(b.committed_at)}</span>}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

interface StaleStatus {
  stale: boolean;
  main_version: string | null;
  main_image_id: string | null;
  current_count: number;
  baked_count: number;
  rebake_state: 'none' | 'building' | 'ready';
  rebake_version: string | null;
  rebake_image_id: string | null;
}

function ImageCard({ img, settingMain, onSetMain, onDelete, onRetry, onConfigure, onTestAgent, testingAgent, onWarmCache, warmingCache, staleStatus, onRebake, rebaking }: {
  img: LunaImage;
  settingMain: string | null;
  onSetMain: (id: string) => void;
  onDelete: (id: string) => void;
  onRetry: () => void;
  onConfigure: (id: string) => void;
  onTestAgent: (id: string) => void;
  testingAgent: string | null;
  onWarmCache: (id: string) => void;
  warmingCache: string | null;
  staleStatus: StaleStatus | null;
  onRebake: () => void;
  rebaking: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{
        background: 'var(--surface)',
        borderColor: img.is_main ? 'var(--moon)' : 'var(--ink-lighter)',
        boxShadow: img.is_main ? '0 0 20px rgba(201,184,255,0.08)' : 'none',
      }}
    >
      <div
        className="flex items-center justify-between px-5 py-4 cursor-pointer select-none"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-4">
          <div
            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
            style={{ background: STATUS_COLORS[img.build_status] || '#94a3b8' }}
          />
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>v{img.version}</span>
              <span className="text-xs capitalize px-2 py-0.5 rounded-full" style={{ background: 'var(--ink-light)', color: STATUS_COLORS[img.build_status] }}>
                {img.build_status}
              </span>
              {img.build_status === 'built' && img.is_main && (
                <span
                  className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
                  style={{ border: '1px solid rgba(201,184,255,0.3)', color: 'var(--moon)' }}
                >
                  <Star size={10} /> Main
                </span>
              )}
              {img.git_branch && img.git_branch !== 'main' && (
                <span
                  className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium font-mono"
                  style={{ border: '1px solid rgba(250,204,21,0.3)', color: '#facc15', background: 'rgba(250,204,21,0.06)' }}
                  title="Experimental build from a non-main Luna branch"
                >
                  <GitBranch size={10} /> {img.git_branch}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 mt-1">
              <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{formatDate(img.built_at || img.created_at)}</span>
              {img.git_sha && (
                <span className="text-xs font-mono" style={{ color: 'var(--text-dim)' }}>{img.git_sha.slice(0, 7)}</span>
              )}
              <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{img.agent_count} agent{img.agent_count !== 1 ? 's' : ''}</span>
              {img.build_status === 'built' && (
                img.cache_warmed_at ? (
                  <span className="flex items-center gap-1 text-xs" style={{ color: '#22c55e' }}>
                    <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ background: '#22c55e' }} />
                    Cache warm
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--text-dim)', opacity: 0.6 }}>
                    <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ background: '#6b7280' }} />
                    Cache cold
                  </span>
                )
              )}
            </div>
            {/* Inline: rebaking indicator on the building image */}
            {img.build_status === 'building' && staleStatus?.rebake_state === 'building' && staleStatus?.rebake_version === img.version && (
              <div className="flex items-center gap-1.5 mt-1.5 text-xs" style={{ color: '#facc15' }}>
                <Loader2 className="animate-spin" size={11} />
                Baking with current defaults… ready to promote when done.
              </div>
            )}
            {/* Inline: stale defaults warning on the main image */}
            {img.is_main && img.build_status === 'built' && staleStatus?.stale && staleStatus?.rebake_state === 'none' && (
              <div className="flex items-center gap-1.5 mt-1.5 text-xs" style={{ color: '#facc15' }}>
                <AlertTriangle size={11} />
                Defaults changed since this image was built.
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {expanded
            ? <ChevronDown size={16} style={{ color: 'var(--text-dim)' }} />
            : <ChevronRight size={16} style={{ color: 'var(--text-dim)' }} />
          }
        </div>
      </div>

      {expanded && (
        <div className="px-5 pb-4 space-y-3" style={{ borderTop: '1px solid var(--ink-lighter)' }}>
          <div className="pt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs">
            <span style={{ color: 'var(--text-dim)' }}>Registry</span>
            <span className="font-mono" style={{ color: 'var(--text)' }}>{img.registry_tag}</span>

            {img.git_sha && <>
              <span style={{ color: 'var(--text-dim)' }}>Git SHA</span>
              <span className="font-mono" style={{ color: 'var(--text)' }}>{img.git_sha}</span>
            </>}

            <span style={{ color: 'var(--text-dim)' }}>Created</span>
            <span style={{ color: 'var(--text)' }}>{formatDate(img.created_at)}</span>

            {img.built_at && <>
              <span style={{ color: 'var(--text-dim)' }}>Built</span>
              <span style={{ color: 'var(--text)' }}>{formatDate(img.built_at)}</span>
            </>}

            {img.build_run_id && <>
              <span style={{ color: 'var(--text-dim)' }}>Actions</span>
              <a
                href={`https://github.com/huemorgan/luna-service/actions/runs/${img.build_run_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 hover:underline"
                style={{ color: 'var(--moon)' }}
                onClick={(e) => e.stopPropagation()}
              >
                Run #{img.build_run_id} <ExternalLink size={10} />
              </a>
            </>}
          </div>

          {img.build_error && (
            <div
              className="flex items-start gap-2 rounded-lg px-3 py-2.5 text-xs"
              style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}
            >
              <AlertCircle size={14} className="flex-shrink-0 mt-0.5" style={{ color: '#ef4444' }} />
              <span style={{ color: '#fca5a5' }}>{img.build_error}</span>
            </div>
          )}

          <div className="flex items-center gap-2 pt-1">
            {img.build_status === 'built' && (
              <button
                onClick={(e) => { e.stopPropagation(); onConfigure(img.id); }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:bg-[var(--ink-light)]"
                style={{ border: '1px solid var(--ink-lighter)', color: 'var(--moon)' }}
              >
                <Settings size={12} /> Configure
              </button>
            )}
            {img.build_status === 'built' && (
              <button
                onClick={(e) => { e.stopPropagation(); onTestAgent(img.id); }}
                disabled={testingAgent === img.id}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:bg-[var(--ink-light)] disabled:opacity-50"
                style={{ border: '1px solid var(--ink-lighter)', color: 'var(--moon)' }}
              >
                {testingAgent === img.id ? <Loader2 className="animate-spin" size={12} /> : <Play size={12} />}
                Test Agent
              </button>
            )}
            {img.build_status === 'built' && !img.cache_warmed_at && (
              <button
                onClick={(e) => { e.stopPropagation(); onWarmCache(img.id); }}
                disabled={warmingCache === img.id}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:bg-[var(--ink-light)] disabled:opacity-50"
                style={{ border: '1px solid var(--ink-lighter)', color: 'var(--moon)' }}
              >
                {warmingCache === img.id ? <Loader2 className="animate-spin" size={12} /> : <RefreshCw size={12} />}
                Warm Cache
              </button>
            )}
            {img.build_status === 'built' && !img.is_main && (
              <button
                onClick={(e) => { e.stopPropagation(); onSetMain(img.id); }}
                disabled={settingMain === img.id}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:bg-[var(--ink-light)] disabled:opacity-50"
                style={{ border: '1px solid var(--ink-lighter)', color: 'var(--moon)' }}
              >
                {settingMain === img.id ? <Loader2 className="animate-spin" size={12} /> : <Star size={12} />}
                Set as Main
              </button>
            )}
            {img.is_main && img.build_status === 'built' && staleStatus?.stale && staleStatus?.rebake_state === 'none' && (
              <button
                onClick={(e) => { e.stopPropagation(); onRebake(); }}
                disabled={rebaking}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:bg-[rgba(250,204,21,0.08)] disabled:opacity-50"
                style={{ border: '1px solid rgba(250,204,21,0.3)', color: '#facc15' }}
              >
                {rebaking ? <Loader2 className="animate-spin" size={12} /> : <Hammer size={12} />}
                Bake new image
              </button>
            )}
            {img.build_status === 'failed' && (
              <button
                onClick={(e) => { e.stopPropagation(); onRetry(); }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:bg-[var(--ink-light)]"
                style={{ border: '1px solid var(--ink-lighter)', color: 'var(--moon)' }}
              >
                <RotateCcw size={12} /> Retry Build
              </button>
            )}
            {!img.is_main && img.build_status !== 'building' && (
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(img.id); }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:bg-[rgba(239,68,68,0.08)]"
                style={{ border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444' }}
              >
                <Trash2 size={12} /> Delete
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ImagesPage() {
  const navigate = useNavigate();
  const [images, setImages] = useState<LunaImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [updateCheck, setUpdateCheck] = useState<UpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [building, setBuilding] = useState(false);
  const [settingMain, setSettingMain] = useState<string | null>(null);
  const [migrating, setMigrating] = useState(false);
  const [migrateResult, setMigrateResult] = useState<{ updated: number; errors: { agent: string; error: string }[] } | null>(null);
  const [testingAgent, setTestingAgent] = useState<string | null>(null);
  const [warmingCache, setWarmingCache] = useState<string | null>(null);
  const [branches, setBranches] = useState<LunaBranch[]>([]);
  const [selectedBranch, setSelectedBranch] = useState('main');
  const [branchesLoading, setBranchesLoading] = useState(false);
  const [staleStatus, setStaleStatus] = useState<StaleStatus | null>(null);
  const [rebaking, setRebaking] = useState(false);

  const fetchImages = useCallback(async () => {
    const res = await fetch('/api/admin/images');
    if (res.ok) setImages(await res.json());
    setLoading(false);
  }, []);

  const fetchBranches = useCallback(async () => {
    setBranchesLoading(true);
    const res = await fetch('/api/admin/luna/branches');
    if (res.ok) setBranches((await res.json()).branches || []);
    setBranchesLoading(false);
  }, []);

  const fetchStaleStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/defaults/stale');
      if (res.ok) setStaleStatus(await res.json());
    } catch { /* best-effort */ }
  }, []);

  useEffect(() => { fetchImages(); fetchBranches(); fetchStaleStatus(); }, [fetchImages, fetchBranches, fetchStaleStatus]);

  // Poll while any image is building
  useEffect(() => {
    const hasBuilding = images.some(i => i.build_status === 'building');
    if (!hasBuilding) return;
    const interval = setInterval(() => { fetchImages(); fetchStaleStatus(); }, 5000);
    return () => clearInterval(interval);
  }, [images, fetchImages, fetchStaleStatus]);

  const handleCheckUpdate = async () => {
    setChecking(true);
    const res = await fetch('/api/admin/images/check-update');
    if (res.ok) setUpdateCheck(await res.json());
    setChecking(false);
  };

  const handleBuild = async () => {
    setBuilding(true);
    try {
      const version = updateCheck?.submodule_version;
      const url = version
        ? `/api/admin/images/build?version=${encodeURIComponent(version)}`
        : '/api/admin/images/build';
      const res = await fetch(url, { method: 'POST' });
      if (res.ok) {
        await fetchImages();
        setUpdateCheck(null);
      } else {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        alert(`Build failed: ${err.detail || JSON.stringify(err)}`);
      }
    } catch (e: unknown) {
      alert(`Build error: ${e instanceof Error ? e.message : e}`);
    }
    setBuilding(false);
  };

  const handleBuildBranch = async () => {
    setBuilding(true);
    try {
      const res = await fetch(
        `/api/admin/images/build?branch=${encodeURIComponent(selectedBranch)}`,
        { method: 'POST' },
      );
      if (res.ok) {
        await fetchImages();
      } else {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        alert(`Build failed: ${err.detail || JSON.stringify(err)}`);
      }
    } catch (e: unknown) {
      alert(`Build error: ${e instanceof Error ? e.message : e}`);
    }
    setBuilding(false);
  };

  const handleSetMain = async (imageId: string) => {
    setSettingMain(imageId);
    const res = await fetch(`/api/admin/images/${imageId}/set-main`, { method: 'POST' });
    if (res.ok) await fetchImages();
    setSettingMain(null);
  };

  const handleDelete = async (imageId: string) => {
    const res = await fetch(`/api/admin/images/${imageId}`, { method: 'DELETE' });
    if (res.ok) await fetchImages();
  };

  const handleRetry = async () => {
    setBuilding(true);
    const res = await fetch('/api/admin/images/build', { method: 'POST' });
    if (res.ok) {
      await fetchImages();
      setUpdateCheck(null);
    }
    setBuilding(false);
  };

  const handleMigrateAll = async () => {
    setMigrating(true);
    setMigrateResult(null);
    const res = await fetch('/api/admin/machines/migrate-all', { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      setMigrateResult({ updated: data.updated, errors: data.errors || [] });
      await fetchImages();
    }
    setMigrating(false);
  };

  const handleTestAgent = async (imageId: string) => {
    const img = images.find(i => i.id === imageId);
    const name = `Test ${img?.version || 'Agent'}`;
    setTestingAgent(imageId);
    try {
      const res = await fetch(`/api/admin/images/${imageId}/test-agent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (res.ok) {
        const data = await res.json();
        alert(`Test agent created: ${data.slug}\nGo to Dashboard to open it once provisioning completes.`);
      } else {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        alert(`Failed: ${err.detail || JSON.stringify(err)}`);
      }
    } catch (e: unknown) {
      alert(`Error: ${e instanceof Error ? e.message : e}`);
    }
    setTestingAgent(null);
  };

  const handleWarmCache = async (imageId: string) => {
    setWarmingCache(imageId);
    try {
      const res = await fetch(`/api/admin/images/${imageId}/warm-cache`, { method: 'POST' });
      if (res.ok) {
        await fetchImages();
      } else {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        alert(`Warming failed: ${err.detail || JSON.stringify(err)}`);
      }
    } catch (e: unknown) {
      alert(`Error: ${e instanceof Error ? e.message : e}`);
    }
    setWarmingCache(null);
  };

  const handleRebake = async () => {
    setRebaking(true);
    try {
      const res = await fetch('/api/admin/images/rebake', { method: 'POST' });
      if (res.ok) {
        await fetchImages();
        await fetchStaleStatus();
      } else {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        alert(`Bake failed: ${err.detail || JSON.stringify(err)}`);
      }
    } catch (e: unknown) {
      alert(`Bake error: ${e instanceof Error ? e.message : e}`);
    }
    setRebaking(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <Package size={20} style={{ color: 'var(--moon)' }} />
          Luna Images
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={handleCheckUpdate}
            disabled={checking}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all hover:scale-105 disabled:opacity-50"
            style={{ border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}
          >
            {checking ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
            Check for Updates
          </button>
        </div>
      </div>

      {/* Build from a Luna branch (experimental builds on production) */}
      <div
        className="rounded-2xl p-4 border mb-6"
        style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}
      >
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-2 min-w-0">
            <GitBranch size={16} style={{ color: 'var(--moon)' }} />
            <div>
              <div className="text-sm font-medium" style={{ color: 'var(--text)' }}>Build from branch</div>
              <div className="text-xs" style={{ color: 'var(--text-dim)' }}>
                Test an experimental Luna branch. Non-main builds are tagged
                <span className="font-mono"> version-branch-sha</span> and never become Main automatically.
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <BranchPicker
              branches={branches}
              selected={selectedBranch}
              onSelect={setSelectedBranch}
              disabled={branchesLoading}
            />
            <button
              onClick={() => { fetchBranches(); }}
              disabled={branchesLoading}
              title="Refresh branch list"
              className="flex items-center justify-center w-9 h-9 rounded-lg transition-colors hover:bg-[var(--ink-light)] disabled:opacity-50"
              style={{ border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}
            >
              {branchesLoading ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
            </button>
            <button
              onClick={handleBuildBranch}
              disabled={building}
              className="flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-semibold transition-all hover:scale-105 disabled:opacity-50"
              style={{ background: 'var(--moon)', color: 'var(--ink)' }}
            >
              {building ? <Loader2 className="animate-spin" size={14} /> : <Hammer size={14} />}
              Build {selectedBranch === 'main' ? 'main' : 'branch'}
            </button>
          </div>
        </div>
      </div>

      {updateCheck && (
        <div
          className="rounded-2xl p-5 border mb-6"
          style={{
            background: 'var(--surface)',
            borderColor: updateCheck.update_available ? 'var(--moon)' : 'var(--ink-lighter)',
          }}
        >
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm" style={{ color: 'var(--text-dim)' }}>
                Latest version
                {updateCheck.source === 'github'
                  ? <span className="text-[10px] ml-1" style={{ color: '#22c55e' }}>(github)</span>
                  : <span className="text-[10px] ml-1" style={{ color: '#facc15' }}>(github error — local fallback)</span>
                }
                : <span style={{ color: 'var(--text)' }}>{updateCheck.submodule_version || 'unknown'}</span>
              </div>
              <div className="text-sm mt-1" style={{ color: 'var(--text-dim)' }}>
                Latest built: <span style={{ color: 'var(--text)' }}>{updateCheck.latest_built || 'none'}</span>
              </div>
            </div>
            {updateCheck.update_available ? (
              <button
                onClick={handleBuild}
                disabled={building}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all hover:scale-105 disabled:opacity-50"
                style={{ background: 'var(--moon)', color: 'var(--ink)' }}
              >
                {building ? <Loader2 className="animate-spin" size={14} /> : <Hammer size={14} />}
                Build {updateCheck.submodule_version}
              </button>
            ) : (
              <span className="text-sm px-3 py-1.5 rounded-lg" style={{ color: '#22c55e', background: 'rgba(34,197,94,0.1)' }}>
                Up to date
              </span>
            )}
          </div>
        </div>
      )}

      {images.length === 0 && (
        <div className="rounded-2xl p-12 border text-center" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          <Package size={48} className="mx-auto mb-4" style={{ color: 'var(--moon)', opacity: 0.5 }} />
          <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--text)' }}>No images yet</h3>
          <p className="text-sm" style={{ color: 'var(--text-dim)' }}>
            Check for updates to build your first Luna image.
          </p>
        </div>
      )}

      {images.length > 0 && (
        <div className="space-y-2">
          {images.map(img => (
            <ImageCard
              key={img.id}
              img={img}
              settingMain={settingMain}
              onSetMain={handleSetMain}
              onDelete={handleDelete}
              onRetry={handleRetry}
              onConfigure={(id) => navigate(`/admin/images/${id}`)}
              onTestAgent={handleTestAgent}
              testingAgent={testingAgent}
              onWarmCache={handleWarmCache}
              warmingCache={warmingCache}
              staleStatus={staleStatus}
              onRebake={handleRebake}
              rebaking={rebaking}
            />
          ))}
        </div>
      )}

      {(() => {
        const mainImage = images.find(i => i.is_main && i.build_status === 'built');
        const totalAgents = images.reduce((sum, i) => sum + i.agent_count, 0);
        const outdatedAgents = mainImage ? totalAgents - mainImage.agent_count : 0;
        if (!mainImage || outdatedAgents <= 0) return null;
        return (
          <div
            className="rounded-xl border p-4 mt-4 flex items-center justify-between"
            style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}
          >
            <div>
              <div className="text-sm font-medium" style={{ color: 'var(--text)' }}>
                {outdatedAgents} agent{outdatedAgents !== 1 ? 's' : ''} on older images
              </div>
              <div className="text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>
                Migrate all to v{mainImage.version}
              </div>
            </div>
            <button
              onClick={handleMigrateAll}
              disabled={migrating}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:scale-105 disabled:opacity-50"
              style={{ background: 'var(--moon)', color: 'var(--ink)' }}
            >
              {migrating ? <Loader2 className="animate-spin" size={14} /> : <ArrowUpCircle size={14} />}
              Migrate All
            </button>
          </div>
        );
      })()}

      {migrateResult && (
        <div
          className="rounded-xl border p-4 mt-3"
          style={{
            background: 'var(--surface)',
            borderColor: migrateResult.errors.length > 0 ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)',
          }}
        >
          <div className="text-sm" style={{ color: 'var(--text)' }}>
            Updated {migrateResult.updated} agent{migrateResult.updated !== 1 ? 's' : ''}
            {migrateResult.errors.length > 0 && (
              <span style={{ color: '#ef4444' }}> — {migrateResult.errors.length} failed</span>
            )}
          </div>
          {migrateResult.errors.map((err, i) => (
            <div key={i} className="text-xs mt-1 flex items-center gap-1" style={{ color: '#fca5a5' }}>
              <AlertCircle size={10} /> {err.agent}: {err.error}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
