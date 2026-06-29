import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Hammer, Loader2 } from 'lucide-react';

interface StaleStatus {
  stale: boolean;
  main_version: string | null;
  main_image_id: string | null;
  current_count: number;
  baked_count: number;
}

/**
 * Plan 032 — sticky banner shown when the admin Defaults plugin set has drifted
 * from what the current main image actually baked. Plugin-set changes only take
 * effect after a rebake, so this surfaces the drift and offers a one-click
 * "Rebuild main". `refreshKey` lets the host page force a re-check after edits.
 */
export default function DefaultsStaleBanner({ refreshKey }: { refreshKey?: unknown }) {
  const navigate = useNavigate();
  const [status, setStatus] = useState<StaleStatus | null>(null);
  const [building, setBuilding] = useState(false);

  const check = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/defaults/stale');
      if (res.ok) setStatus(await res.json());
    } catch {
      /* best-effort; banner just stays hidden */
    }
  }, []);

  useEffect(() => { check(); }, [check, refreshKey]);

  const rebuild = async () => {
    setBuilding(true);
    try {
      // force=true rebakes the current main version in place (same Luna version,
      // updated defaults) instead of 409-ing on the already-built version.
      const res = await fetch('/api/admin/images/build?force=true', { method: 'POST' });
      if (res.ok) {
        navigate('/admin/images');
      } else {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        alert(`Build failed: ${err.detail || JSON.stringify(err)}`);
        setBuilding(false);
      }
    } catch (e: unknown) {
      alert(`Build error: ${e instanceof Error ? e.message : e}`);
      setBuilding(false);
    }
  };

  if (!status?.stale) return null;

  return (
    <div
      className="rounded-xl border p-4 mb-6 flex items-center justify-between gap-4 flex-wrap"
      style={{ background: 'rgba(250,204,21,0.08)', borderColor: 'rgba(250,204,21,0.35)' }}
    >
      <div className="flex items-start gap-2.5 min-w-0">
        <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" style={{ color: '#facc15' }} />
        <div>
          <div className="text-sm font-medium" style={{ color: 'var(--text)' }}>
            Default plugin set changed since main image
            {status.main_version ? ` v${status.main_version}` : ''} was built
          </div>
          <div className="text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>
            Plugin-set changes only apply to newly baked images. Rebuild main, then
            set it as Main and migrate agents to roll it out.
          </div>
        </div>
      </div>
      <button
        onClick={rebuild}
        disabled={building}
        className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:scale-105 disabled:opacity-50 flex-shrink-0"
        style={{ background: '#facc15', color: 'var(--ink)' }}
      >
        {building ? <Loader2 className="animate-spin" size={14} /> : <Hammer size={14} />}
        Rebuild main
      </button>
    </div>
  );
}
