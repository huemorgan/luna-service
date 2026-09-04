// Plan 102 — coupon management: mint single-use credit coupons, see who
// redeemed what. Used coupons stay listed forever with the redeeming
// account + user.

import { useCallback, useEffect, useState } from 'react';
import { Check, Copy, Loader2, RefreshCw, Ticket, Trash2, Undo2 } from 'lucide-react';

interface CouponRow {
  id: string;
  code: string;
  credits: number;
  expires_days: number | null;
  reason: string;
  created_at: string | null;
  status: 'active' | 'sent' | 'used';
  sent_at: string | null;
  redeemed_at: string | null;
  redeemed_account: { id: string; slug: string; name: string } | null;
  redeemed_by: { id: string; email: string; name: string | null } | null;
  grant_id: string | null;
}

const API = '/api/admin/pricing/coupons';
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

export default function CouponsPage() {
  const [coupons, setCoupons] = useState<CouponRow[]>([]);
  const [loading, setLoading] = useState(true);

  const [credits, setCredits] = useState('');
  const [code, setCode] = useState('');
  const [expiresDays, setExpiresDays] = useState('');
  const [count, setCount] = useState('1');
  const [reason, setReason] = useState('');
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    const res = await fetch(API);
    if (res.ok) setCoupons(await res.json());
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleCreate = async () => {
    setCreating(true);
    setCreateErr(null);
    const res = await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        credits: Number(credits),
        code: Number(count) > 1 ? null : (code.trim() || null),
        expires_days: expiresDays.trim() ? Number(expiresDays) : null,
        count: Math.max(1, Number(count) || 1),
        reason: reason.trim(),
      }),
    });
    if (res.ok) {
      setCredits(''); setCode(''); setExpiresDays(''); setCount('1'); setReason('');
      await fetchAll();
    } else {
      const body = await res.json().catch(() => null);
      setCreateErr(body?.detail ?? `Create failed (${res.status})`);
    }
    setCreating(false);
  };

  const handleDelete = async (c: CouponRow) => {
    if (!window.confirm(`Delete unused coupon ${c.code} (${c.credits.toLocaleString()} credits)?`)) return;
    const res = await fetch(`${API}/${c.id}`, { method: 'DELETE' });
    if (res.ok) await fetchAll();
  };

  const handleCopy = async (c: CouponRow) => {
    try {
      await navigator.clipboard.writeText(c.code);
      setCopiedId(c.id);
      setTimeout(() => setCopiedId(prev => (prev === c.id ? null : prev)), 1500);
    } catch { /* clipboard unavailable */ }
  };

  const handleSent = async (c: CouponRow, sent: boolean) => {
    const res = await fetch(`${API}/${c.id}/sent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sent }),
    });
    if (res.ok) await fetchAll();
  };

  const canCreate = Number(credits) > 0 && reason.trim().length > 0
    && Number(count) >= 1 && !creating;

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
          <Ticket size={20} style={{ color: 'var(--moon)' }} />
          Coupons
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
        Single-use credit coupons. Customers redeem them on the billing page; the
        credits arrive as a gift lot (expiry from the coupon, or the pricing
        default of 90 days). Used coupons are permanent records.
      </p>

      {/* ── Create ── */}
      <div className="rounded-2xl p-5 border mb-8" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
        <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text)' }}>New coupon</h3>
        <div className="flex items-center gap-2 flex-wrap">
          <input value={credits} onChange={e => setCredits(e.target.value)} type="number" min={1}
            placeholder="Credits *" className={inputCls} style={{ ...inputStyle, width: '8.5rem' }} />
          <input value={code} onChange={e => setCode(e.target.value)} disabled={Number(count) > 1}
            placeholder={Number(count) > 1 ? 'Codes generated' : 'Code (blank = generated)'}
            className={`${inputCls} font-mono ${Number(count) > 1 ? 'opacity-50' : ''}`}
            style={{ ...inputStyle, width: '15rem' }} />
          <input value={expiresDays} onChange={e => setExpiresDays(e.target.value)} type="number" min={1}
            placeholder="Credit lifetime, days" className={inputCls} style={{ ...inputStyle, width: '11rem' }} />
          <input value={count} onChange={e => setCount(e.target.value)} type="number" min={1} max={500}
            title="How many coupons to mint with these values"
            placeholder="Count" className={inputCls} style={{ ...inputStyle, width: '6rem' }} />
          <input value={reason} onChange={e => setReason(e.target.value)}
            placeholder="Reason *" className={inputCls} style={{ ...inputStyle, minWidth: '16rem', flex: 1 }} />
          <button onClick={handleCreate} disabled={!canCreate}
            className={`px-4 py-2 rounded-xl text-sm font-semibold transition-opacity ${
              canCreate ? 'hover:opacity-90' : 'cursor-not-allowed opacity-50'}`}
            style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
            {creating ? 'Creating…' : 'Create'}
          </button>
        </div>
        {createErr && (
          <p className="text-xs mt-2" style={{ color: '#ef4444' }}>{createErr}</p>
        )}
      </div>

      {/* ── List ── */}
      <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text)' }}>
        All coupons <span className="font-normal" style={{ color: 'var(--text-dim)' }}>({coupons.length})</span>
      </h3>
      {coupons.length === 0 ? (
        <div className="rounded-2xl p-8 border text-center" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          <p className="text-sm" style={{ color: 'var(--text-dim)' }}>No coupons yet.</p>
        </div>
      ) : (
        <div className="rounded-xl border overflow-x-auto" style={{ borderColor: 'var(--ink-lighter)' }}>
          <table className="w-full">
            <thead>
              <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--ink-lighter)' }}>
                <th className={thCls} style={thStyle}>Code</th>
                <th className={thCls} style={thStyle}>Credits</th>
                <th className={thCls} style={thStyle}>Status</th>
                <th className={thCls} style={thStyle}>Created</th>
                <th className={thCls} style={thStyle}>Reason</th>
                <th className={thCls} style={thStyle}>Redeemed</th>
                <th className={thCls} style={thStyle}>Account</th>
                <th className={thCls} style={thStyle}>Redeemed by</th>
                <th className="text-right text-xs font-medium px-4 py-3" style={thStyle}></th>
              </tr>
            </thead>
            <tbody>
              {coupons.map(c => (
                <tr key={c.id} className="border-t" style={{ borderColor: 'var(--ink-lighter)', background: 'var(--surface)' }}>
                  <td className="px-4 py-3 text-sm font-mono whitespace-nowrap" style={{ color: 'var(--text)' }}>
                    {c.code}
                    <button onClick={() => handleCopy(c)}
                      className="ml-2 p-1 rounded-md align-middle transition-all hover:scale-110"
                      style={{ color: copiedId === c.id ? '#22c55e' : 'var(--text-dim)' }}
                      title="Copy code">
                      {copiedId === c.id ? <Check size={13} /> : <Copy size={13} />}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-sm tabular-nums" style={{ color: 'var(--text)' }}>
                    {c.credits.toLocaleString()}
                    {c.expires_days != null && (
                      <span className="text-xs ml-1" style={{ color: 'var(--text-dim)' }}>/ {c.expires_days}d</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs px-2 py-0.5 rounded-full font-medium" style={{
                      color: c.status === 'used' ? '#eab308' : c.status === 'sent' ? '#3b82f6' : '#22c55e',
                      background: c.status === 'used' ? '#eab30822' : c.status === 'sent' ? '#3b82f622' : '#22c55e22',
                    }} title={c.status === 'sent' ? `Sent ${fmtTime(c.sent_at)}` : undefined}>
                      {c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-dim)' }}>{fmtTime(c.created_at)}</td>
                  <td className="px-4 py-3 text-xs max-w-xs truncate" style={{ color: 'var(--text-dim)' }} title={c.reason}>
                    {c.reason}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-dim)' }}>{fmtTime(c.redeemed_at)}</td>
                  <td className="px-4 py-3 text-sm" style={{ color: 'var(--text)' }}>
                    {c.redeemed_account ? (c.redeemed_account.name || c.redeemed_account.slug) : '—'}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text)' }}>
                    {c.redeemed_by ? (
                      <>
                        {c.redeemed_by.name && <span>{c.redeemed_by.name} · </span>}
                        <span style={{ color: 'var(--text-dim)' }}>{c.redeemed_by.email}</span>
                      </>
                    ) : '—'}
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    {c.status === 'active' && (
                      <button onClick={() => handleSent(c, true)}
                        className="text-xs px-2 py-1 rounded-lg mr-1 transition-all hover:scale-105"
                        style={{ border: '1px solid var(--ink-lighter)', color: '#3b82f6' }}
                        title="Mark as sent — you gave this code to someone">
                        Sent
                      </button>
                    )}
                    {c.status === 'sent' && (
                      <button onClick={() => handleSent(c, false)}
                        className="p-1.5 rounded-lg mr-1 transition-all hover:scale-110"
                        style={{ color: 'var(--text-dim)' }} title="Undo — mark as not sent">
                        <Undo2 size={14} />
                      </button>
                    )}
                    {c.status !== 'used' && (
                      <button onClick={() => handleDelete(c)}
                        className="p-1.5 rounded-lg transition-all hover:scale-110"
                        style={{ color: '#ef4444' }} title="Delete unused coupon">
                        <Trash2 size={14} />
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
