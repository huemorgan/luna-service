import { useEffect, useState, useCallback } from 'react';
import { Package, Loader2, Star, Hammer, RefreshCw, ExternalLink, ChevronDown, ChevronRight, AlertCircle, Trash2, RotateCcw } from 'lucide-react';

interface LunaImage {
  id: string;
  version: string;
  registry_tag: string;
  is_main: boolean;
  build_status: string;
  build_run_id: string | null;
  build_error: string | null;
  git_sha: string | null;
  created_at: string | null;
  built_at: string | null;
  agent_count: number;
}

interface UpdateCheck {
  submodule_version: string | null;
  latest_built: string | null;
  update_available: boolean;
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

function ImageCard({ img, settingMain, onSetMain, onDelete, onRetry }: {
  img: LunaImage;
  settingMain: string | null;
  onSetMain: (id: string) => void;
  onDelete: (id: string) => void;
  onRetry: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasDetails = img.build_error || img.git_sha || img.registry_tag || img.build_run_id;

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
        onClick={() => hasDetails && setExpanded(!expanded)}
      >
        <div className="flex items-center gap-4">
          <div
            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
            style={{ background: STATUS_COLORS[img.build_status] || '#94a3b8' }}
          />
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>v{img.version}</span>
              {img.is_main && (
                <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full" style={{ background: 'rgba(201,184,255,0.15)', color: 'var(--moon)' }}>
                  <Star size={10} /> Main
                </span>
              )}
              <span className="text-xs capitalize px-2 py-0.5 rounded-full" style={{ background: 'var(--ink-light)', color: STATUS_COLORS[img.build_status] }}>
                {img.build_status}
              </span>
            </div>
            <div className="flex items-center gap-3 mt-1">
              <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{formatDate(img.built_at || img.created_at)}</span>
              {img.git_sha && (
                <span className="text-xs font-mono" style={{ color: 'var(--text-dim)' }}>{img.git_sha.slice(0, 7)}</span>
              )}
              <span className="text-xs" style={{ color: 'var(--text-dim)' }}>{img.agent_count} agent{img.agent_count !== 1 ? 's' : ''}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {img.build_status === 'failed' && (
            <button
              onClick={(e) => { e.stopPropagation(); onRetry(); }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:opacity-80"
              style={{ border: '1px solid var(--ink-lighter)', color: 'var(--moon)' }}
            >
              <RotateCcw size={12} /> Retry
            </button>
          )}
          {img.build_status === 'built' && !img.is_main && (
            <button
              onClick={(e) => { e.stopPropagation(); onSetMain(img.id); }}
              disabled={settingMain === img.id}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:opacity-80 disabled:opacity-50"
              style={{ border: '1px solid var(--ink-lighter)', color: 'var(--moon)' }}
            >
              {settingMain === img.id ? <Loader2 className="animate-spin" size={12} /> : <Star size={12} />}
              Set as Main
            </button>
          )}
          {hasDetails && (
            expanded
              ? <ChevronDown size={16} style={{ color: 'var(--text-dim)' }} />
              : <ChevronRight size={16} style={{ color: 'var(--text-dim)' }} />
          )}
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
            {img.build_status === 'failed' && (
              <button
                onClick={(e) => { e.stopPropagation(); onRetry(); }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:opacity-80"
                style={{ border: '1px solid var(--ink-lighter)', color: 'var(--moon)' }}
              >
                <RotateCcw size={12} /> Retry Build
              </button>
            )}
            {!img.is_main && img.build_status !== 'building' && (
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(img.id); }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:opacity-80"
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
  const [images, setImages] = useState<LunaImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [updateCheck, setUpdateCheck] = useState<UpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [building, setBuilding] = useState(false);
  const [settingMain, setSettingMain] = useState<string | null>(null);

  const fetchImages = useCallback(async () => {
    const res = await fetch('/api/admin/images');
    if (res.ok) setImages(await res.json());
    setLoading(false);
  }, []);

  useEffect(() => { fetchImages(); }, [fetchImages]);

  // Poll while any image is building
  useEffect(() => {
    const hasBuilding = images.some(i => i.build_status === 'building');
    if (!hasBuilding) return;
    const interval = setInterval(fetchImages, 5000);
    return () => clearInterval(interval);
  }, [images, fetchImages]);

  const handleCheckUpdate = async () => {
    setChecking(true);
    const res = await fetch('/api/admin/images/check-update');
    if (res.ok) setUpdateCheck(await res.json());
    setChecking(false);
  };

  const handleBuild = async () => {
    setBuilding(true);
    const res = await fetch('/api/admin/images/build', { method: 'POST' });
    if (res.ok) {
      await fetchImages();
      setUpdateCheck(null);
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

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
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
                Submodule version: <span style={{ color: 'var(--text)' }}>{updateCheck.submodule_version || 'unknown'}</span>
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
            />
          ))}
        </div>
      )}
    </div>
  );
}
