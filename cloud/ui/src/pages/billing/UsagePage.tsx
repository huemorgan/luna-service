// 046 — customer Usage page: per-channel 28-day credit bars (web chat,
// scheduled triggers, WhatsApp, Telegram) sharing one y-scale, filterable
// per Luna. Credits only — no internal pricing ever reaches this page.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Moon, LogOut, ChevronLeft, Loader2, MessageSquare, Clock,
  ChevronDown, ChevronRight, Pencil, Check, X,
} from 'lucide-react';
import { API, credits, getJson, apiError } from './api';
import type { ChannelSection, ChannelUsage, UsageSummary } from './api';

const card = {
  background: 'var(--surface)',
  borderColor: 'var(--ink-lighter)',
} as const;

type RangeKey = 'today' | '7d' | '28d' | 'custom';

function rangeQuery(range: RangeKey, start: string, end: string): string {
  if (range !== 'custom') return `range=${range}`;
  return `range=custom&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
}

function SectionTitle({ children, icon }: { children: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <h3 className="text-sm font-semibold uppercase tracking-wider flex items-center gap-2" style={{ color: 'var(--text-dim)' }}>
      {icon}{children}
    </h3>
  );
}

// ── Shared-scale bar chart ───────────────────────────────────────────────────

function BarChart({ trend, yMax, height = 96 }: {
  trend: Array<{ day: string; credits: number }>;
  yMax: number;
  height?: number;
}) {
  const ceil = Math.max(1, yMax);
  const ticks = [ceil, ceil / 2, 0];
  if (trend.length === 0) {
    return <div className="text-sm" style={{ color: 'var(--text-dim)' }}>No activity in this range.</div>;
  }
  return (
    <div className="flex gap-2">
      <div className="relative w-14 shrink-0 text-xs tabular-nums text-right"
        style={{ color: 'var(--text-dim)', height }}>
        {ticks.map(v => (
          <span key={v} className="absolute right-0 -translate-y-1/2"
            style={{ top: `${100 - (v / ceil) * 100}%` }}>
            {Math.round(v).toLocaleString()}
          </span>
        ))}
      </div>
      <div className="flex-1 min-w-0">
        <div className="relative" style={{ height }}>
          {ticks.map(v => (
            <div key={v} className="absolute inset-x-0"
              style={{ top: `${100 - (v / ceil) * 100}%`, height: 1, background: 'var(--ink-lighter)' }} />
          ))}
          <div className="absolute inset-0 flex items-end justify-around gap-1">
            {trend.map(t => (
              <div key={t.day} className="flex-1 flex justify-center items-end h-full" style={{ minWidth: 3 }}>
                <div className="w-full rounded-t"
                  title={`${t.day}: ${t.credits.toLocaleString()} cr`}
                  style={{
                    height: t.credits > 0 ? `${Math.max(2, (t.credits / ceil) * 100)}%` : 0,
                    background: 'var(--moon)', opacity: 0.75, minWidth: 3, maxWidth: 24,
                  }} />
              </div>
            ))}
          </div>
        </div>
        <div className="flex justify-between text-xs mt-1" style={{ color: 'var(--text-dim)' }}>
          <span>{trend[0].day}</span>
          <span>{trend[trend.length - 1].day}</span>
        </div>
      </div>
    </div>
  );
}

function ChannelCard({ title, icon, section, yMax, children }: {
  title: string;
  icon: React.ReactNode;
  section: ChannelSection | undefined;
  yMax: number;
  children?: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl p-5 border mb-6" style={card}>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <SectionTitle icon={icon}>{title}</SectionTitle>
        <span className="text-sm tabular-nums font-semibold" style={{ color: 'var(--text)' }}>
          {credits(section?.total ?? 0)}
        </span>
      </div>
      <BarChart trend={section?.trend ?? []} yMax={yMax} />
      {children}
    </section>
  );
}

// ── Scheduled triggers (expandable) ──────────────────────────────────────────

function SchedulerTriggers({ section, yMax }: { section: ChannelSection | undefined; yMax: number }) {
  const [open, setOpen] = useState<string | null>(null);
  const triggers = section?.triggers ?? [];
  if (triggers.length === 0) return null;
  return (
    <div className="mt-5 pt-4 border-t" style={{ borderColor: 'var(--ink-lighter)' }}>
      <div className="text-xs uppercase tracking-wider mb-2" style={{ color: 'var(--text-dim)' }}>
        Triggers
      </div>
      <div className="space-y-1">
        {triggers.map(t => (
          <div key={t.key}>
            <button
              onClick={() => setOpen(open === t.key ? null : t.key)}
              className="w-full flex items-center gap-3 text-sm py-2 text-left hover:opacity-80">
              {open === t.key
                ? <ChevronDown size={14} style={{ color: 'var(--text-dim)' }} />
                : <ChevronRight size={14} style={{ color: 'var(--text-dim)' }} />}
              <span className="flex-1 truncate" style={{ color: 'var(--text)' }}>{t.name}</span>
              <span className="tabular-nums" style={{ color: 'var(--text)' }}>{credits(t.total)}</span>
            </button>
            {open === t.key && (
              <div className="ml-6 mb-3">
                <BarChart trend={t.trend} yMax={yMax} height={72} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Per-Luna limit editor (owner-only) ───────────────────────────────────────

function Progress({ used, limit, warnPct }: { used: number; limit: number | null; warnPct: number | null }) {
  if (limit == null || limit <= 0) {
    return <span className="text-xs" style={{ color: 'var(--text-dim)' }}>no limit</span>;
  }
  const pct = Math.min(100, Math.round((used / limit) * 100));
  const warn = warnPct != null && pct >= warnPct;
  const full = used >= limit;
  const color = full ? '#ff6b6b' : warn ? '#ffc864' : 'var(--moon)';
  return (
    <div className="flex items-center gap-2 min-w-[130px]">
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--ink-lighter)' }}>
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="text-xs tabular-nums" style={{ color: 'var(--text-dim)' }}>{pct}%</span>
    </div>
  );
}

function LimitEditor({ luna, onSaved }: {
  luna: UsageSummary['per_luna'][number];
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [daily, setDaily] = useState('');
  const [monthly, setMonthly] = useState('');
  const [warnPct, setWarnPct] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const begin = () => {
    setDaily(luna.daily.limit_credits?.toString() ?? '');
    setMonthly(luna.monthly.limit_credits?.toString() ?? '');
    setWarnPct(luna.warning_threshold_pct?.toString() ?? '');
    setError(null);
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    const num = (s: string) => (s.trim() === '' ? null : Number(s));
    const res = await fetch(`${API}/limits/${luna.agent_id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        daily_limit_credits: num(daily),
        monthly_limit_credits: num(monthly),
        warning_threshold_pct: num(warnPct),
      }),
    });
    setSaving(false);
    if (!res.ok) { setError(await apiError(res)); return; }
    setEditing(false);
    onSaved();
  };

  if (!editing) {
    return (
      <button onClick={begin} className="p-1.5 rounded-lg hover:opacity-80 transition-opacity"
        title="Edit limits" style={{ color: 'var(--text-dim)' }}>
        <Pencil size={14} />
      </button>
    );
  }
  const inputCls = 'w-24 px-2 py-1 rounded-lg text-sm border bg-transparent';
  const inputStyle = { borderColor: 'var(--ink-lighter)', color: 'var(--text)' } as const;
  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-dim)' }}>
        <label>daily</label>
        <input className={inputCls} style={inputStyle} value={daily}
          onChange={e => setDaily(e.target.value)} placeholder="none" inputMode="numeric" />
        <label>monthly</label>
        <input className={inputCls} style={inputStyle} value={monthly}
          onChange={e => setMonthly(e.target.value)} placeholder="none" inputMode="numeric" />
        <label>warn %</label>
        <input className={inputCls} style={inputStyle} value={warnPct}
          onChange={e => setWarnPct(e.target.value)} placeholder="80" inputMode="numeric" />
        <button onClick={save} disabled={saving} className="p-1.5 rounded-lg" style={{ color: '#78dca0' }}>
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
        </button>
        <button onClick={() => setEditing(false)} className="p-1.5 rounded-lg" style={{ color: 'var(--text-dim)' }}>
          <X size={14} />
        </button>
      </div>
      {error && <div className="text-xs" style={{ color: '#ff6b6b' }}>{error}</div>}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function UsagePage() {
  const [params, setParams] = useSearchParams();
  const agent = params.get('agent') ?? '';

  const [range, setRange] = useState<RangeKey>('28d');
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');

  const [channels, setChannels] = useState<ChannelUsage | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showLimits, setShowLimits] = useState(false);

  const query = useMemo(() => {
    if (range === 'custom' && (!customStart || !customEnd)) return null;
    return rangeQuery(
      range,
      customStart && `${customStart}T00:00:00+00:00`,
      customEnd && `${customEnd}T23:59:59+00:00`,
    );
  }, [range, customStart, customEnd]);

  const agentParam = agent ? `&agent_id=${agent}` : '';

  const loadChannels = useCallback(() => {
    if (!query) return;
    setError(null);
    getJson<ChannelUsage>(`${API}/usage/channels?${query}${agentParam}`)
      .then(setChannels).catch(e => setError(e.message));
  }, [query, agentParam]);

  const loadSummary = useCallback(() => {
    if (!query) return;
    getJson<UsageSummary>(`${API}/usage/summary?${query}`).then(setUsage).catch(() => {});
  }, [query]);

  useEffect(loadChannels, [loadChannels]);
  useEffect(loadSummary, [loadSummary]);

  const setAgent = (id: string) => {
    const next = new URLSearchParams(params);
    if (id) next.set('agent', id); else next.delete('agent');
    setParams(next);
  };

  const yMax = channels?.y_max ?? 1;
  const lunas = usage?.per_luna ?? [];
  const activeLuna = lunas.find(l => l.agent_id === agent);
  const filteredLunas = agent ? lunas.filter(l => l.agent_id === agent) : lunas;

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
        <div className="flex items-center gap-2">
          <Link to="/dashboard/usage" className="px-3 py-1.5 rounded-lg text-sm font-semibold"
            style={{ background: 'var(--ink-light)', color: 'var(--text)' }}>Usage</Link>
          <Link to="/dashboard/billing" className="px-3 py-1.5 rounded-lg text-sm hover:opacity-80"
            style={{ color: 'var(--text-dim)' }}>Billing</Link>
          <a href="/auth/logout" className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm hover:opacity-80" style={{ color: 'var(--text-dim)' }}>
            <LogOut size={14} /> Sign out
          </a>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        <nav className="mb-6 flex items-center gap-2 text-sm" style={{ color: 'var(--text-dim)' }}>
          <Link to="/dashboard" className="inline-flex items-center gap-1 hover:underline">
            <ChevronLeft size={14} /> Dashboard
          </Link>
          <span>/</span>
          <span style={{ color: 'var(--text)' }}>Usage</span>
        </nav>

        <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
          <h2 className="text-2xl font-bold" style={{ color: 'var(--text)' }}>Usage</h2>
          <div className="flex items-center gap-3 flex-wrap">
            {/* Luna filter */}
            <select value={agent} onChange={e => setAgent(e.target.value)}
              className="px-3 py-1.5 rounded-lg text-sm border bg-transparent"
              style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)', colorScheme: 'dark' }}>
              <option value="">All Lunas</option>
              {lunas.map(l => (
                <option key={l.agent_id} value={l.agent_id}>{l.agent_name}</option>
              ))}
            </select>
            {/* Range */}
            <div className="flex items-center gap-1 text-sm">
              {(['today', '7d', '28d', 'custom'] as RangeKey[]).map(k => (
                <button key={k} onClick={() => setRange(k)}
                  className="px-3 py-1.5 rounded-lg transition-colors"
                  style={range === k
                    ? { background: 'var(--moon)', color: 'var(--ink)', fontWeight: 600 }
                    : { color: 'var(--text-dim)' }}>
                  {k === 'today' ? 'Today' : k === 'custom' ? 'Custom' : `Last ${k.replace('d', ' days')}`}
                </button>
              ))}
            </div>
            {range === 'custom' && (
              <div className="flex items-center gap-2">
                <input type="date" value={customStart} onChange={e => setCustomStart(e.target.value)}
                  className="px-2 py-1 rounded-lg border bg-transparent text-sm"
                  style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)', colorScheme: 'dark' }} />
                <span style={{ color: 'var(--text-dim)' }}>→</span>
                <input type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)}
                  className="px-2 py-1 rounded-lg border bg-transparent text-sm"
                  style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)', colorScheme: 'dark' }} />
              </div>
            )}
          </div>
        </div>

        {agent && activeLuna && (
          <div className="text-sm mb-4" style={{ color: 'var(--text-dim)' }}>
            Showing <span style={{ color: 'var(--text)' }}>{activeLuna.agent_name}</span> only ·{' '}
            <button onClick={() => setAgent('')} className="hover:underline" style={{ color: 'var(--moon)' }}>
              show all Lunas
            </button>
          </div>
        )}

        {error && (
          <div className="rounded-xl px-4 py-3 border text-sm mb-6" style={{
            background: 'rgba(255,107,107,0.08)', borderColor: 'rgba(255,107,107,0.4)', color: '#ff6b6b',
          }}>{error}</div>
        )}

        {!channels && !error && (
          <div className="flex items-center gap-2 py-16 justify-center" style={{ color: 'var(--text-dim)' }}>
            <Loader2 size={18} className="animate-spin" /> Loading usage…
          </div>
        )}

        {channels && (
          <>
            <ChannelCard title="Chat" icon={<MessageSquare size={14} />}
              section={channels.sections.web} yMax={yMax} />

            <ChannelCard title="Scheduled triggers" icon={<Clock size={14} />}
              section={channels.sections.scheduler} yMax={yMax}>
              <SchedulerTriggers section={channels.sections.scheduler} yMax={yMax} />
            </ChannelCard>

            <ChannelCard title="WhatsApp"
              icon={<span className="text-xs">🟢</span>}
              section={channels.sections.whatsapp} yMax={yMax} />

            <ChannelCard title="Telegram"
              icon={<span className="text-xs">✈️</span>}
              section={channels.sections.telegram} yMax={yMax} />

            {/* Per-Luna limits — collapsed by default */}
            <section className="rounded-2xl p-5 border mb-8" style={card}>
              <button type="button" onClick={() => setShowLimits(s => !s)}
                className="flex items-center gap-1.5 text-xs uppercase tracking-wider hover:underline"
                style={{ color: 'var(--text-dim)' }}>
                <span className="inline-block transition-transform"
                  style={{ transform: showLimits ? 'rotate(90deg)' : 'none' }}>▸</span>
                Set spending limits per Luna
              </button>
              {showLimits && (
                <div className="mt-4 space-y-3">
                  {filteredLunas.map(l => (
                    <div key={l.agent_id} className="flex items-center justify-between gap-4 text-sm flex-wrap">
                      <span className="min-w-[120px]" style={{ color: 'var(--text)' }}>{l.agent_name}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-xs w-12" style={{ color: 'var(--text-dim)' }}>daily</span>
                        <span className="text-xs tabular-nums w-28" style={{ color: 'var(--text)' }}>
                          {l.daily.used_credits.toLocaleString()}{l.daily.limit_credits != null && ` / ${l.daily.limit_credits.toLocaleString()}`} cr
                        </span>
                        <Progress used={l.daily.used_credits} limit={l.daily.limit_credits} warnPct={l.warning_threshold_pct} />
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs w-14" style={{ color: 'var(--text-dim)' }}>monthly</span>
                        <span className="text-xs tabular-nums w-28" style={{ color: 'var(--text)' }}>
                          {l.monthly.used_credits.toLocaleString()}{l.monthly.limit_credits != null && ` / ${l.monthly.limit_credits.toLocaleString()}`} cr
                        </span>
                        <Progress used={l.monthly.used_credits} limit={l.monthly.limit_credits} warnPct={l.warning_threshold_pct} />
                      </div>
                      <LimitEditor luna={l} onSaved={loadSummary} />
                    </div>
                  ))}
                  {filteredLunas.length === 0 && (
                    <div className="text-sm" style={{ color: 'var(--text-dim)' }}>No Lunas yet.</div>
                  )}
                  <p className="text-xs" style={{ color: 'var(--text-dim)' }}>
                    Limits cap what each Luna can spend (hosting excluded). Only the account owner can change them.
                  </p>
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
