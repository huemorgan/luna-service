import { useEffect, useState, useCallback } from 'react';
import { Package, Loader2, Star, Hammer, RefreshCw, ExternalLink } from 'lucide-react';

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
            <div
              key={img.id}
              className="flex items-center justify-between px-5 py-4 rounded-xl border"
              style={{
                background: 'var(--surface)',
                borderColor: img.is_main ? 'var(--moon)' : 'var(--ink-lighter)',
                boxShadow: img.is_main ? '0 0 20px rgba(201,184,255,0.08)' : 'none',
              }}
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
                  {img.build_error && (
                    <div className="text-xs mt-1" style={{ color: '#ef4444' }}>{img.build_error}</div>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2">
                {img.build_run_id && (
                  <a
                    href={`https://github.com/huemorgan/luna-service/actions/runs/${img.build_run_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs transition-colors hover:opacity-80"
                    style={{ color: 'var(--text-dim)' }}
                  >
                    <ExternalLink size={12} /> Logs
                  </a>
                )}
                {img.build_status === 'built' && !img.is_main && (
                  <button
                    onClick={() => handleSetMain(img.id)}
                    disabled={settingMain === img.id}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:opacity-80 disabled:opacity-50"
                    style={{ border: '1px solid var(--ink-lighter)', color: 'var(--moon)' }}
                  >
                    {settingMain === img.id ? <Loader2 className="animate-spin" size={12} /> : <Star size={12} />}
                    Set as Main
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
