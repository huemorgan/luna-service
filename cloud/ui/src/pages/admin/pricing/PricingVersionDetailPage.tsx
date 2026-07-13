import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeft, Loader2, Save, Upload, Archive, AlertTriangle, Copy,
} from 'lucide-react';
import { API, StatusPill, apiError } from './api';
import type { PricingVersion } from './api';

/** Draft editing is raw validated JSON: the server is the single validator
 *  (floats, tier lists, SKU formulas, product invariants) and its message is
 *  surfaced verbatim. Structured editors live in the LLM & services /
 *  Credit buckets pages; this page is the whole-document view. */
export default function PricingVersionDetailPage() {
  const { versionId } = useParams();
  const [version, setVersion] = useState<PricingVersion | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [configText, setConfigText] = useState('');
  const [name, setName] = useState('');
  const [notes, setNotes] = useState('');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    const res = await fetch(`${API}/versions/${versionId}`);
    if (res.ok) {
      const v: PricingVersion = await res.json();
      setVersion(v);
      setConfigText(JSON.stringify(v.config, null, 2));
      setName(v.name ?? '');
      setNotes(v.notes ?? '');
    }
    setLoading(false);
  }, [versionId]);

  useEffect(() => { refresh(); }, [refresh]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }
  if (!version) return <p className="text-sm" style={{ color: 'var(--text-dim)' }}>Version not found.</p>;

  const isDraft = version.status === 'draft';
  const inputStyle = { background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };

  const act = async (fn: () => Promise<Response>, okMsg: string) => {
    setSaving(true);
    setError(null);
    setNotice(null);
    const res = await fn();
    setSaving(false);
    if (res.ok) { setNotice(okMsg); refresh(); }
    else setError(await apiError(res));
  };

  const saveDraft = () => {
    let config: unknown;
    try {
      config = JSON.parse(configText);
    } catch (e) {
      setError(`Invalid JSON: ${(e as Error).message}`);
      return;
    }
    act(() => fetch(`${API}/versions/${version.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config, name: name || null, notes: notes || null }),
    }), 'Draft saved and validated.');
  };

  const publish = () => act(() => fetch(`${API}/versions/${version.id}/publish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  }), 'Published — this version is now immutable.');

  const retire = () => act(() => fetch(`${API}/versions/${version.id}/retire`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  }), 'Retired.');

  const clone = () => act(() => fetch(`${API}/versions/${version.id}/clone`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  }), 'Cloned into a new draft — see the versions list.');

  return (
    <div className="max-w-4xl">
      <Link to="/admin/pricing/versions" className="flex items-center gap-2 text-sm mb-4 hover:opacity-80"
        style={{ color: 'var(--text-dim)' }}>
        <ArrowLeft size={14} /> All versions
      </Link>

      <div className="flex items-center gap-3 mb-2">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text)' }}>
          v{version.version_number}{version.name ? ` — ${version.name}` : ''}
        </h2>
        <StatusPill status={version.status} />
      </div>
      <p className="text-xs mb-6 font-mono" style={{ color: 'var(--text-dim)' }}>
        hash {version.config_hash.slice(0, 16)}…
        {version.published_at ? ` · published ${new Date(version.published_at).toLocaleString()}` : ''}
      </p>

      {error && (
        <div className="rounded-xl px-4 py-3 mb-4 text-sm" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-xl px-4 py-3 mb-4 text-sm" style={{ background: 'rgba(120,220,160,0.12)', color: '#78dca0' }}>
          {notice}
        </div>
      )}

      {(version.uncovered_models?.length ?? 0) > 0 && (
        <div className="rounded-xl px-4 py-3 mb-4 text-sm flex items-start gap-2"
          style={{ background: 'rgba(255,200,100,0.12)', color: '#ffc864' }}>
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>
            Enabled gateway models in neither tier list (publish will be rejected):{' '}
            <code>{version.uncovered_models!.join(', ')}</code>
          </span>
        </div>
      )}

      {version.diff_vs_parent && Object.keys(version.diff_vs_parent).length > 0 && (
        <div className="rounded-xl border p-4 mb-6" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          <div className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-dim)' }}>
            Diff vs parent
          </div>
          <table className="w-full text-xs" style={{ color: 'var(--text)' }}>
            <tbody>
              {Object.entries(version.diff_vs_parent).map(([path, d]) => (
                <tr key={path}>
                  <td className="py-1 pr-3 font-mono" style={{ color: 'var(--text-dim)' }}>{path}</td>
                  <td className="py-1 pr-3 font-mono" style={{ color: '#ff6b6b' }}>{JSON.stringify(d.from)}</td>
                  <td className="py-1 font-mono" style={{ color: '#78dca0' }}>{JSON.stringify(d.to)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {isDraft && (
        <div className="flex items-center gap-2 mb-3">
          <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="Name"
            className="w-52 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} />
          <input type="text" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Notes"
            className="flex-1 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} />
        </div>
      )}

      <textarea
        value={configText}
        onChange={e => setConfigText(e.target.value)}
        readOnly={!isDraft}
        spellCheck={false}
        rows={28}
        className="w-full px-3 py-2 rounded-xl text-xs outline-none font-mono mb-4"
        style={{ ...inputStyle, opacity: isDraft ? 1 : 0.75 }}
      />

      <div className="flex items-center gap-2 flex-wrap">
        {isDraft && (
          <button onClick={saveDraft} disabled={saving}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
            style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
            {saving ? <Loader2 className="animate-spin" size={12} /> : <Save size={12} />} Save draft
          </button>
        )}
        {(isDraft || version.status === 'published') && (
          <input type="text" value={reason} onChange={e => setReason(e.target.value)}
            placeholder="Reason (required to publish/retire)"
            className="w-72 px-2.5 py-1.5 rounded-lg text-xs outline-none" style={inputStyle} />
        )}
        {isDraft && (
          <button onClick={publish} disabled={saving || !reason.trim()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
            style={{ background: 'rgba(120,220,160,0.2)', color: '#78dca0' }}>
            <Upload size={12} /> Publish
          </button>
        )}
        {version.status === 'published' && (
          <button onClick={retire} disabled={saving || !reason.trim()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
            style={{ background: 'rgba(160,160,160,0.2)', color: '#a0a0a0' }}>
            <Archive size={12} /> Retire
          </button>
        )}
        <button onClick={clone} disabled={saving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-50"
          style={{ background: 'var(--ink)', color: 'var(--moon)' }}>
          <Copy size={12} /> Clone to draft
        </button>
      </div>
    </div>
  );
}
