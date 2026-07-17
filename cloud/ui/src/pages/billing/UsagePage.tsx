// 046 — customer Usage page: per-channel 28-day credit bars (web chat,
// scheduled triggers, WhatsApp, Telegram) sharing one y-scale, filterable
// per Luna. Credits only — no internal pricing ever reaches this page.

import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  ChevronLeft, Loader2, MessageSquare, Clock, Play,
  ChevronDown, ChevronRight, Pencil, Check, X,
} from 'lucide-react';
import AppHeader from '../../components/AppHeader';
import { API, credits, getJson, apiError } from './api';
import type { ChannelItem, ChannelSection, ChannelTrendPoint, ChannelUsage, UsageSummary } from './api';

const card = {
  background: 'var(--surface)',
  borderColor: 'var(--ink-lighter)',
} as const;

// Short "Jun 19" day label from a YYYY-MM-DD string.
function fmtDay(day: string): string {
  const d = new Date(day + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return day;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Alternating parity per day, flipping on each Monday so the chart background
// bands align with calendar weeks (handles partial weeks at the edges).
function weekParities(days: string[]): boolean[] {
  const out: boolean[] = [];
  let parity = false;
  let prevKey: string | null = null;
  for (const day of days) {
    const d = new Date(day + 'T00:00:00');
    const dow = (d.getDay() + 6) % 7; // 0 = Monday
    const monday = new Date(d);
    monday.setDate(d.getDate() - dow);
    const key = monday.toISOString().slice(0, 10);
    if (prevKey === null) prevKey = key;
    else if (key !== prevKey) { parity = !parity; prevKey = key; }
    out.push(parity);
  }
  return out;
}

// ── Shared-scale bar chart: hairline box, alternating week bands, hover ───────

function BarChart({ trend, yMax, height = 88 }: {
  trend: ChannelTrendPoint[];
  yMax: number;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const ceil = Math.max(1, yMax);
  if (trend.length === 0) {
    return <div className="text-sm py-6" style={{ color: 'var(--text-dim)' }}>No activity.</div>;
  }
  const bands = weekParities(trend.map(t => t.day));
  const last = trend.length - 1;
  return (
    <div>
      <div className="text-xs tabular-nums mb-1" style={{ color: 'var(--text-dim)' }}>
        {Math.round(ceil).toLocaleString()}
      </div>
      {/* Hairline box; week bands are the alternating cell backgrounds. */}
      <div className="relative border" style={{ borderColor: 'var(--ink-lighter)', height }}>
        <div className="flex items-end h-full">
          {trend.map((t, i) => {
            const hovered = hover === i;
            const band = bands[i] ? 'rgba(255,255,255,0.05)' : 'rgba(255,255,255,0.015)';
            const pct = t.credits > 0 ? Math.max(3, (t.credits / ceil) * 100) : 0;
            return (
              <div
                key={t.day}
                className="relative flex-1 h-full flex items-end justify-center"
                style={{ background: hovered ? 'rgba(255,255,255,0.09)' : band }}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(h => (h === i ? null : h))}
              >
                <div style={{
                  width: '68%',
                  height: `${pct}%`,
                  background: 'var(--moon)',
                  opacity: hover == null ? 0.8 : hovered ? 1 : 0.3,
                  transition: 'opacity 0.1s',
                }} />
                {hovered && (
                  <div
                    className="absolute left-1/2 -translate-x-1/2 z-10 px-2 py-1 rounded-md text-xs whitespace-nowrap pointer-events-none"
                    style={{
                      bottom: `calc(${Math.min(pct, 92)}% + 6px)`,
                      background: 'var(--surface)',
                      border: '1px solid var(--ink-lighter)',
                      color: 'var(--text)',
                    }}
                  >
                    <span className="font-semibold tabular-nums">{t.credits.toLocaleString()} cr</span>
                    <span className="ml-1.5" style={{ color: 'var(--text-dim)' }}>
                      {i === last ? 'today' : fmtDay(t.day)}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <div className="flex justify-between text-xs mt-1" style={{ color: 'var(--text-dim)' }}>
        <span>{fmtDay(trend[0].day)}</span>
        <span>Today</span>
      </div>
    </div>
  );
}

// ── Channel section: title + description in front of a boxed chart ────────────

function ChannelChart({ title, icon, description, section, yMax, children }: {
  title: string;
  icon: React.ReactNode;
  description: string;
  section: ChannelSection | undefined;
  yMax: number;
  children?: React.ReactNode;
}) {
  return (
    <section className="mb-8">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h3 className="text-base font-semibold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          {icon}{title}
        </h3>
        <span className="text-sm tabular-nums font-semibold" style={{ color: 'var(--text)' }}>
          {credits(section?.total ?? 0)}
        </span>
      </div>
      <p className="text-xs mt-0.5 mb-3" style={{ color: 'var(--text-dim)' }}>{description}</p>
      <BarChart trend={section?.trend ?? []} yMax={yMax} />
      {children}
    </section>
  );
}

// ── Optional per-item breakdown, indented, each item expandable to a chart ────

function ItemBreakdown({ section, yMax, label }: {
  section: ChannelSection | undefined; yMax: number; label: string;
}) {
  const [open, setOpen] = useState(false);
  const items: ChannelItem[] = section?.items ?? section?.triggers ?? [];
  if (items.length === 0) return null;
  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-xs hover:underline"
        style={{ color: 'var(--moon)' }}
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        {label}
      </button>
      {open && (
        <div className="mt-2 ml-4 border-l pl-4 space-y-0.5" style={{ borderColor: 'var(--ink-lighter)' }}>
          {items.map(t => <ItemRow key={t.key} item={t} yMax={yMax} />)}
        </div>
      )}
    </div>
  );
}

function ItemRow({ item, yMax }: { item: ChannelItem; yMax: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 text-sm py-1.5 text-left hover:opacity-80"
      >
        {open
          ? <ChevronDown size={13} style={{ color: 'var(--text-dim)' }} />
          : <ChevronRight size={13} style={{ color: 'var(--text-dim)' }} />}
        <span className="flex-1 truncate" style={{ color: 'var(--text)' }}>{item.name}</span>
        <span className="tabular-nums" style={{ color: 'var(--text)' }}>{credits(item.total)}</span>
      </button>
      {open && (
        <div className="ml-5 mb-3">
          <BarChart trend={item.trend} yMax={yMax} height={56} />
        </div>
      )}
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

  const [channels, setChannels] = useState<ChannelUsage | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showLimits, setShowLimits] = useState(false);

  // Fixed 28-day window (048: the day-range filter was removed).
  const agentParam = agent ? `&agent_id=${agent}` : '';

  const loadChannels = useCallback(() => {
    setError(null);
    getJson<ChannelUsage>(`${API}/usage/channels?range=28d${agentParam}`)
      .then(setChannels).catch(e => setError(e.message));
  }, [agentParam]);

  const loadSummary = useCallback(() => {
    getJson<UsageSummary>(`${API}/usage/summary?range=28d`).then(setUsage).catch(() => {});
  }, []);

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
      <AppHeader />

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
            {/* Luna filter — the only control (day range removed, always 28d) */}
            <select value={agent} onChange={e => setAgent(e.target.value)}
              className="px-3 py-1.5 rounded-lg text-sm border bg-transparent"
              style={{ borderColor: 'var(--ink-lighter)', color: 'var(--text)', colorScheme: 'dark' }}>
              <option value="">All Lunas</option>
              {lunas.map(l => (
                <option key={l.agent_id} value={l.agent_id}>{l.agent_name}</option>
              ))}
            </select>
            <span className="text-xs" style={{ color: 'var(--text-dim)' }}>Last 28 days</span>
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
            <ChannelChart title="Chat" icon={<MessageSquare size={16} />}
              description="Credit consumption from web chat usage."
              section={channels.sections.web} yMax={yMax} />

            <ChannelChart title="Scheduled triggers" icon={<Clock size={16} />}
              description="Credit consumption from triggered scheduling."
              section={channels.sections.scheduler} yMax={yMax}>
              <ItemBreakdown section={channels.sections.scheduler} yMax={yMax}
                label="Break down by trigger" />
            </ChannelChart>

            <ChannelChart title="Playbooks" icon={<Play size={16} />}
              description="Credit consumption from playbook automations."
              section={channels.sections.playbooks} yMax={yMax}>
              <ItemBreakdown section={channels.sections.playbooks} yMax={yMax}
                label="Break down by playbook" />
            </ChannelChart>

            <ChannelChart title="WhatsApp"
              icon={<span className="text-sm">🟢</span>}
              description="Credits consumed from WhatsApp conversations with the agent."
              section={channels.sections.whatsapp} yMax={yMax} />

            <ChannelChart title="Telegram"
              icon={<span className="text-sm">✈️</span>}
              description="Credits consumed from Telegram conversations with the agent."
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
