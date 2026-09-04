// Plan 088 — service API keys: mint scoped keys for machine callers (a Luna
// keeps one in its vault). Secret is shown exactly once at creation; revoked
// keys stay listed for audit.

import { useCallback, useEffect, useState } from 'react';
import { Check, Copy, KeySquare, Loader2, RefreshCw, ShieldOff } from 'lucide-react';

interface KeyRow {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  state: 'active' | 'expired' | 'revoked';
  expires_at: string | null;
  created_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
}

interface ScopeDef { scope: string; label: string }

const API = '/api/admin/service-keys';
const thCls = 'text-left text-xs font-medium px-4 py-3';
const thStyle = { color: 'var(--text-dim)' } as const;
const inputCls = 'px-3 py-2 rounded-xl text-sm border bg-transparent outline-none';
const inputStyle = {
  background: 'var(--surface)', borderColor: 'var(--ink-lighter)', color: 'var(--text)',
} as const;

function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

const STATE_COLORS: Record<KeyRow['state'], string> = {
  active: '#22c55e', expired: '#eab308', revoked: '#ef4444',
};

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<KeyRow[]>([]);
  const [scopeDefs, setScopeDefs] = useState<ScopeDef[]>([]);
  const [loading, setLoading] = useState(true);

  const [name, setName] = useState('');
  const [expires, setExpires] = useState('');
  const [scopes, setScopes] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState<string | null>(null);

  // One-time reveal of the last-created secret.
  const [revealed, setRevealed] = useState<{ id: string; key: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const fetchAll = useCallback(async () => {
    const [kRes, sRes] = await Promise.all([fetch(API), fetch(`${API}/scopes`)]);
    if (kRes.ok) setKeys((await kRes.json()).keys);
    if (sRes.ok) setScopeDefs((await sRes.json()).scopes);
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const toggleScope = (s: string) => {
    setScopes(prev => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s); else next.add(s);
      return next;
    });
  };

  const handleCreate = async () => {
    setCreating(true);
    setCreateErr(null);
    const res = await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name.trim(),
        scopes: Array.from(scopes),
        expires_at: expires ? new Date(`${expires}T23:59:59`).toISOString() : null,
      }),
    });
    if (res.ok) {
      const body = await res.json();
      setRevealed({ id: body.id, key: body.key });
      setCopied(false);
      setName(''); setExpires(''); setScopes(new Set());
      await fetchAll();
    } else {
      const body = await res.json().catch(() => null);
      setCreateErr(body?.detail ?? `Create failed (${res.status})`);
    }
    setCreating(false);
  };

  const handleRevoke = async (k: KeyRow) => {
    if (!window.confirm(`Revoke key "${k.name}" (${k.key_prefix}…)? Callers using it stop working immediately.`)) return;
    const res = await fetch(`${API}/${k.id}/revoke`, { method: 'POST' });
    if (res.ok) {
      if (revealed?.id === k.id) setRevealed(null);
      await fetchAll();
    }
  };

  const handleCopy = async () => {
    if (!revealed) return;
    try {
      await navigator.clipboard.writeText(revealed.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable */ }
  };

  const canCreate = name.trim().length > 0 && scopes.size > 0 && !creating;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  return (
    <div className="max-w-6xl">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <KeySquare size={20} style={{ color: 'var(--moon)' }} />
          API Keys
        </h2>
        <button
          onClick={fetchAll}
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-all hover:scale-105"
          style={{ border: '1px solid var(--ink-lighter)', color: 'var(--text-dim)' }}
        >
          <RefreshCw size={14} />
        </button>
      </div>
      <p className="text-xs mb-6 max-w-3xl leading-relaxed" style={{ color: 'var(--text-dim)' }}>
        Keys for machine callers of the luna-service admin API (send as{' '}
        <code>x-api-key</code>). Permissions are coarse — a checkbox grants a whole
        section. The secret is shown once, at creation. Revoking is immediate.
      </p>

      {/* ── Create ── */}
      <div className="rounded-2xl p-5 border mb-4" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
        <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text)' }}>New key</h3>
        <div className="flex items-center gap-2 flex-wrap">
          <input value={name} onChange={e => setName(e.target.value)}
            placeholder="Name * (who uses it)" className={inputCls} style={{ ...inputStyle, minWidth: '16rem' }} />
          <label className="text-xs flex items-center gap-2" style={{ color: 'var(--text-dim)' }}>
            Expires
            <input value={expires} onChange={e => setExpires(e.target.value)} type="date"
              className={inputCls} style={inputStyle} title="Blank = never expires" />
          </label>
          <button onClick={handleCreate} disabled={!canCreate}
            className={`px-4 py-2 rounded-xl text-sm font-semibold transition-opacity ${
              canCreate ? 'hover:opacity-90' : 'cursor-not-allowed opacity-50'}`}
            style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
            {creating ? 'Creating…' : 'Create key'}
          </button>
        </div>
        <div className="flex items-center gap-4 flex-wrap mt-3">
          {scopeDefs.map(s => (
            <label key={s.scope} className="flex items-center gap-2 text-sm cursor-pointer" style={{ color: 'var(--text)' }}>
              <input type="checkbox" checked={scopes.has(s.scope)} onChange={() => toggleScope(s.scope)} />
              {s.label}
              <code className="text-xs" style={{ color: 'var(--text-dim)' }}>{s.scope}</code>
            </label>
          ))}
        </div>
        {createErr && (
          <p className="text-xs mt-2" style={{ color: '#ef4444' }}>{createErr}</p>
        )}
      </div>

      {/* ── One-time secret reveal ── */}
      {revealed && (
        <div className="rounded-2xl p-4 border mb-8 flex items-center gap-3 flex-wrap"
          style={{ background: '#22c55e11', borderColor: '#22c55e55' }}>
          <span className="text-xs font-semibold" style={{ color: '#22c55e' }}>
            Key created — copy it now, it will not be shown again:
          </span>
          <code className="text-sm font-mono px-2 py-1 rounded-lg" style={{ background: 'var(--surface)', color: 'var(--text)' }}>
            {revealed.key}
          </code>
          <button onClick={handleCopy}
            className="p-1.5 rounded-lg transition-all hover:scale-110"
            style={{ color: copied ? '#22c55e' : 'var(--text-dim)' }} title="Copy key">
            {copied ? <Check size={15} /> : <Copy size={15} />}
          </button>
        </div>
      )}

      {/* ── List ── */}
      <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text)' }}>
        All keys <span className="font-normal" style={{ color: 'var(--text-dim)' }}>({keys.length})</span>
      </h3>
      {keys.length === 0 ? (
        <div className="rounded-2xl p-8 border text-center" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          <p className="text-sm" style={{ color: 'var(--text-dim)' }}>No keys yet.</p>
        </div>
      ) : (
        <div className="rounded-xl border overflow-x-auto" style={{ borderColor: 'var(--ink-lighter)' }}>
          <table className="w-full">
            <thead>
              <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
                <th className={thCls} style={thStyle}>Name</th>
                <th className={thCls} style={thStyle}>Key</th>
                <th className={thCls} style={thStyle}>Permissions</th>
                <th className={thCls} style={thStyle}>State</th>
                <th className={thCls} style={thStyle}>Created</th>
                <th className={thCls} style={thStyle}>Expires</th>
                <th className={thCls} style={thStyle}>Last used</th>
                <th className="text-right text-xs font-medium px-4 py-3" style={thStyle}></th>
              </tr>
            </thead>
            <tbody>
              {keys.map(k => (
                <tr key={k.id} className="border-t" style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}>
                  <td className="px-4 py-3 text-sm" style={{ color: 'var(--text)' }}>{k.name}</td>
                  <td className="px-4 py-3 text-sm font-mono whitespace-nowrap" style={{ color: 'var(--text-dim)' }}>
                    {k.key_prefix}…
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text)' }}>
                    {k.scopes.map(s => (
                      <span key={s} className="inline-block px-2 py-0.5 mr-1 rounded-full"
                        style={{ background: 'var(--ink-light)', color: 'var(--text-dim)' }}>
                        {scopeDefs.find(d => d.scope === s)?.label ?? s}
                      </span>
                    ))}
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs px-2 py-0.5 rounded-full font-medium"
                      style={{ color: STATE_COLORS[k.state], background: `${STATE_COLORS[k.state]}22` }}>
                      {k.state}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-dim)' }}>{fmtTime(k.created_at)}</td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-dim)' }}>{k.expires_at ? fmtTime(k.expires_at) : 'never'}</td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-dim)' }}>{fmtTime(k.last_used_at)}</td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    {k.state !== 'revoked' && (
                      <button onClick={() => handleRevoke(k)}
                        className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg ml-auto transition-all hover:scale-105"
                        style={{ border: '1px solid var(--ink-lighter)', color: '#ef4444' }}
                        title="Revoke — callers using this key stop working immediately">
                        <ShieldOff size={12} /> Revoke
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
