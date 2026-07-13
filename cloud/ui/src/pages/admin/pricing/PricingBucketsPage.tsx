import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Wallet, Loader2, Plus, Save } from 'lucide-react';
import { StatusPill } from './api';
import { useTargetVersion } from './useTargetVersion';

/** Credit buckets — trial gift, subscription/top-up products, migration gift.
 *  Burn order and expiration are ledger mechanics (039/001) shown for
 *  reference; Stripe bindings arrive in 039/007. */
export default function PricingBucketsPage() {
  const t = useTargetVersion();

  if (t.loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--moon)' }} />
      </div>
    );
  }

  return (
    <div className="max-w-4xl">
      <h2 className="text-xl font-bold flex items-center gap-2 mb-2" style={{ color: 'var(--text)' }}>
        <Wallet size={20} style={{ color: 'var(--moon)' }} />
        Credit Buckets
      </h2>
      <p className="text-sm mb-4" style={{ color: 'var(--text-dim)' }}>
        Products, trial, and migration gift of the {t.target?.status === 'draft' ? 'current draft' : 'newest published version'}.
        1 credit = $0.01, always. Paid credits equal payment × 100 — value lives in bonuses, never dollar discounts.
      </p>

      {t.target && (
        <div className="rounded-xl border px-4 py-3 mb-4 flex items-center gap-3 text-sm"
          style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
          <Link to={`/admin/pricing/versions/${t.target.id}`} className="font-semibold hover:underline"
            style={{ color: 'var(--text)' }}>
            v{t.target.version_number}{t.target.name ? ` — ${t.target.name}` : ''}
          </Link>
          <StatusPill status={t.target.status} />
          <span className="flex-1" />
          {!t.isDraft && (
            <button onClick={t.cloneNewestToDraft}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium"
              style={{ background: 'var(--ink)', color: 'var(--moon)' }}>
              <Plus size={12} /> Clone to draft to edit
            </button>
          )}
        </div>
      )}
      {t.error && (
        <div className="rounded-xl px-4 py-3 mb-4 text-sm" style={{ background: 'rgba(255,107,107,0.12)', color: '#ff6b6b' }}>
          {t.error}
        </div>
      )}
      {t.notice && (
        <div className="rounded-xl px-4 py-3 mb-4 text-sm" style={{ background: 'rgba(120,220,160,0.12)', color: '#78dca0' }}>
          {t.notice}
        </div>
      )}

      {t.target?.config ? <Editor t={t} /> : (
        <p className="text-sm" style={{ color: 'var(--text-dim)' }}>No pricing versions exist yet.</p>
      )}

      <div className="mt-8 rounded-xl border p-4 text-xs space-y-1" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)', color: 'var(--text-dim)' }}>
        <div className="font-semibold uppercase tracking-wide mb-1">Ledger mechanics (fixed, 039/001)</div>
        <div>Burn order: bonus → gift/free → paid → top-up, earliest expiry first.</div>
        <div>Expiration: bonus/gift lots carry expiry; paid and top-up credits do not expire.</div>
        <div>Stripe product/price bindings attach in phase 007 — placeholders until then.</div>
      </div>
    </div>
  );
}

type Target = ReturnType<typeof useTargetVersion>;

function Editor({ t }: { t: Target }) {
  const config = t.target!.config!;
  const inputStyle = { background: 'var(--ink)', color: 'var(--text)', border: '1px solid var(--ink-lighter)' };

  const [trial, setTrial] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(config.trial).map(([k, v]) => [k, String(v)])));
  const [migration, setMigration] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(config.migration_gift).map(([k, v]) => [k, String(v)])));
  const [products, setProducts] = useState(() => config.products.map(p => ({
    ...p,
    price_usd_cents_s: String(p.price_usd_cents),
    paid_credits_s: String(p.paid_credits),
    bonus_credits_s: String(p.bonus_credits ?? 0),
  })));

  const save = () => t.saveConfig(c => {
    c.trial = Object.fromEntries(Object.entries(trial).map(([k, v]) => [k, Number(v)]));
    c.migration_gift = Object.fromEntries(Object.entries(migration).map(([k, v]) => [k, Number(v)]));
    c.products = products.map(({ price_usd_cents_s, paid_credits_s, bonus_credits_s, ...p }) => ({
      ...p,
      price_usd_cents: Number(price_usd_cents_s),
      paid_credits: Number(paid_credits_s),
      bonus_credits: Number(bonus_credits_s),
    }));
  });

  return (
    <>
      <div className="grid grid-cols-2 gap-4 mb-6">
        <NumberCard title="Trial (per new account)" values={trial} setValues={setTrial} readOnly={!t.isDraft} inputStyle={inputStyle} />
        <NumberCard title="Migration gift (existing users, 039/010)" values={migration} setValues={setMigration} readOnly={!t.isDraft} inputStyle={inputStyle} />
      </div>

      <h3 className="text-sm font-bold mb-2" style={{ color: 'var(--text)' }}>Products</h3>
      <div className="rounded-xl border overflow-hidden mb-3" style={{ borderColor: 'var(--ink-lighter)' }}>
        <table className="w-full text-xs" style={{ color: 'var(--text)' }}>
          <thead>
            <tr style={{ background: 'var(--surface)', color: 'var(--text-dim)' }}>
              <th className="text-left px-3 py-2 font-medium">Key</th>
              <th className="text-left px-3 py-2 font-medium">Kind</th>
              <th className="text-left px-3 py-2 font-medium">Interval</th>
              <th className="text-right px-3 py-2 font-medium">Price (¢)</th>
              <th className="text-right px-3 py-2 font-medium">Paid credits</th>
              <th className="text-right px-3 py-2 font-medium">Bonus credits</th>
              <th className="text-left px-3 py-2 font-medium">Stripe</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p, i) => (
              <tr key={p.key} style={{ background: i % 2 ? 'var(--surface)' : 'transparent' }}>
                <td className="px-3 py-2 font-mono font-semibold">{p.key}</td>
                <td className="px-3 py-2">{p.kind}</td>
                <td className="px-3 py-2">{(p.interval as string) ?? '—'}</td>
                <td className="px-3 py-2 text-right">
                  <NumCell value={p.price_usd_cents_s} readOnly={!t.isDraft}
                    onChange={v => setProducts(r => r.map((x, j) => j === i ? { ...x, price_usd_cents_s: v } : x))}
                    inputStyle={inputStyle} />
                </td>
                <td className="px-3 py-2 text-right">
                  <NumCell value={p.paid_credits_s} readOnly={!t.isDraft}
                    onChange={v => setProducts(r => r.map((x, j) => j === i ? { ...x, paid_credits_s: v } : x))}
                    inputStyle={inputStyle} />
                </td>
                <td className="px-3 py-2 text-right">
                  <NumCell value={p.bonus_credits_s} readOnly={!t.isDraft || p.kind === 'topup'}
                    onChange={v => setProducts(r => r.map((x, j) => j === i ? { ...x, bonus_credits_s: v } : x))}
                    inputStyle={inputStyle} />
                </td>
                <td className="px-3 py-2" style={{ color: 'var(--text-dim)' }}>not bound (007)</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {t.isDraft && (
        <button onClick={save}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold"
          style={{ background: 'var(--moon)', color: 'var(--ink)' }}>
          <Save size={12} /> Save to draft
        </button>
      )}
    </>
  );
}

function NumberCard({ title, values, setValues, readOnly, inputStyle }: {
  title: string;
  values: Record<string, string>;
  setValues: (f: (v: Record<string, string>) => Record<string, string>) => void;
  readOnly: boolean;
  inputStyle: React.CSSProperties;
}) {
  return (
    <div className="rounded-xl border p-4" style={{ background: 'var(--surface)', borderColor: 'var(--ink-lighter)' }}>
      <div className="text-xs font-semibold uppercase tracking-wide mb-3" style={{ color: 'var(--text-dim)' }}>{title}</div>
      <div className="space-y-2">
        {Object.entries(values).map(([k, v]) => (
          <label key={k} className="flex items-center justify-between gap-2 text-xs" style={{ color: 'var(--text)' }}>
            <span style={{ color: 'var(--text-dim)' }}>{k.replaceAll('_', ' ')}</span>
            <input type="number" value={v} readOnly={readOnly}
              onChange={e => setValues(x => ({ ...x, [k]: e.target.value }))}
              className="w-28 px-2 py-1 rounded-lg outline-none text-right" style={inputStyle} />
          </label>
        ))}
      </div>
    </div>
  );
}

function NumCell({ value, onChange, readOnly, inputStyle }: {
  value: string;
  onChange: (v: string) => void;
  readOnly: boolean;
  inputStyle: React.CSSProperties;
}) {
  return (
    <input type="number" value={value} readOnly={readOnly} onChange={e => onChange(e.target.value)}
      className="w-24 px-2 py-1 rounded-lg outline-none text-right" style={inputStyle} />
  );
}
