import { useCallback, useEffect, useState } from 'react';
import { API, apiError } from './api';
import type { PricingConfig, PricingVersion } from './api';

/** The structured editor pages (LLM & services, Credit buckets) operate on the
 *  newest draft when one exists, else show the newest published version
 *  read-only. Edits always PUT the full config — the server re-validates and
 *  re-hashes; published versions are never touched. */
export function useTargetVersion() {
  const [target, setTarget] = useState<PricingVersion | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const res = await fetch(`${API}/versions`);
    if (!res.ok) { setLoading(false); return; }
    const versions: PricingVersion[] = (await res.json()).versions;
    const pick = versions.find(v => v.status === 'draft')
      ?? versions.find(v => v.status === 'published')
      ?? null;
    if (pick) {
      const detail = await fetch(`${API}/versions/${pick.id}`);
      if (detail.ok) setTarget(await detail.json());
    } else {
      setTarget(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const isDraft = target?.status === 'draft';

  const saveConfig = async (mutate: (config: PricingConfig) => void) => {
    if (!target || !isDraft || !target.config) return;
    setError(null);
    setNotice(null);
    const config = JSON.parse(JSON.stringify(target.config)) as PricingConfig;
    mutate(config);
    const res = await fetch(`${API}/versions/${target.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config }),
    });
    if (res.ok) { setNotice('Saved and validated.'); refresh(); }
    else setError(await apiError(res));
  };

  const cloneNewestToDraft = async () => {
    if (!target) return;
    setError(null);
    const res = await fetch(`${API}/versions/${target.id}/clone`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (res.ok) refresh();
    else setError(await apiError(res));
  };

  return { target, isDraft, loading, error, notice, setError, setNotice, saveConfig, cloneNewestToDraft, refresh };
}
